"""HTTP-сервер оверлея, JSON API и SSE."""

from __future__ import annotations

import http.client
import json
import socket
import sqlite3
import time
from pathlib import Path

import pytest

from ymrpc.services.overlay import OverlayServer, OverlayState
from ymrpc.services.stats import SCHEMA


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _get(port: int, path: str, headers: dict[str, str] | None = None) -> tuple[int, dict[str, str], bytes]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request("GET", path, headers=headers or {})
        response = connection.getresponse()
        body = response.read()
        headers = {key.lower(): value for key, value in response.getheaders()}
        return response.status, headers, body
    finally:
        connection.close()


@pytest.fixture
def overlay(tmp_path: Path):
    port = _free_port()
    art_dir = tmp_path / "art"
    art_dir.mkdir()
    server = OverlayServer(port=port, stats_path=tmp_path / "stats.db", art_dir=art_dir)
    assert server.start() is True
    try:
        yield server
    finally:
        server.stop()


def test_state_snapshot_is_a_copy_and_versions_grow() -> None:
    state = OverlayState()
    first = state.snapshot()
    assert first["has_track"] is False

    state.set({"has_track": True, "title": "Пыяла"})
    snapshot = state.snapshot()
    assert snapshot["title"] == "Пыяла"
    assert snapshot["version"] == 1
    assert "updated_at" in snapshot

    snapshot["title"] = "Изменено"
    assert state.snapshot()["title"] == "Пыяла"

    state.set({"has_track": False})
    assert state.snapshot()["version"] == 2


def test_health(overlay: OverlayServer) -> None:
    status, headers, body = _get(overlay.port, "/health")
    assert status == 200
    assert headers["content-type"].startswith("application/json")
    assert json.loads(body) == {"ok": True, "version": 0}
    assert "access-control-allow-origin" not in headers
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["referrer-policy"] == "no-referrer"


def test_cors_only_for_loopback_origin(overlay: OverlayServer) -> None:
    origin = f"http://127.0.0.1:{overlay.port}"
    status, headers, _ = _get(overlay.port, "/health", {"Origin": origin})
    assert status == 200
    assert headers["access-control-allow-origin"] == origin
    assert headers["vary"] == "Origin"

    status, headers, _ = _get(overlay.port, "/health", {"Origin": "https://evil.example"})
    assert status == 200
    assert "access-control-allow-origin" not in headers


def test_rejects_foreign_host_header(overlay: OverlayServer) -> None:
    status, _, body = _get(overlay.port, "/health", {"Host": "evil.example"})
    assert status == 421
    assert json.loads(body) == {"error": "invalid host"}


def test_now_playing(overlay: OverlayServer) -> None:
    overlay.state.set({"has_track": True, "title": "Пыяла", "status": "playing"})
    status, _, body = _get(overlay.port, "/api/now-playing")
    assert status == 200
    payload = json.loads(body)
    assert payload["title"] == "Пыяла"
    assert payload["status"] == "playing"
    assert payload["version"] == 1


@pytest.mark.parametrize("path", ["/", "/index.html", "/overlay", "/widget"])
def test_overlay_html(overlay: OverlayServer, path: str) -> None:
    status, headers, body = _get(overlay.port, path)
    assert status == 200
    assert headers["content-type"] == "text/html; charset=utf-8"
    assert headers["cache-control"] == "no-store"
    assert "default-src 'self'" in headers["content-security-policy"]
    assert headers["x-frame-options"] == "SAMEORIGIN"
    assert headers["x-content-type-options"] == "nosniff"
    assert b"<!doctype html>" in body.lower()
    assert b"YMRPC Next" in body


def test_unknown_path_returns_404(overlay: OverlayServer) -> None:
    status, _, body = _get(overlay.port, "/nope")
    assert status == 404
    assert json.loads(body) == {"error": "not found"}


def test_art_without_file(overlay: OverlayServer) -> None:
    status, _, body = _get(overlay.port, "/api/art")
    assert status == 404
    assert json.loads(body)["error"] == "no art"

    overlay.state.set({}, art_path=str(Path("missing.png")))
    status, _, _ = _get(overlay.port, "/api/art")
    assert status == 404


def test_art_serves_file(overlay: OverlayServer) -> None:
    art = overlay.art_dir / "cover.png"
    art.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    overlay.state.set({}, art_path=art)
    status, headers, body = _get(overlay.port, "/api/art")
    assert status == 200
    assert headers["content-type"] == "image/png"
    assert headers["cache-control"].startswith("public")
    assert body == art.read_bytes()


def test_art_rejects_file_outside_cache(overlay: OverlayServer, tmp_path: Path) -> None:
    secret = tmp_path / "secret.png"
    secret.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    overlay.state.set({}, art_path=secret)
    status, _, _ = _get(overlay.port, "/api/art")
    assert status == 404


def test_art_path_is_not_exposed(overlay: OverlayServer) -> None:
    overlay.state.set({"has_track": True, "art_path": "C:\\secret\\cover.png"})
    _, _, body = _get(overlay.port, "/api/now-playing")
    assert "art_path" not in json.loads(body)


def test_stats_endpoint(overlay: OverlayServer, tmp_path: Path) -> None:
    path = tmp_path / "stats.db"
    connection = sqlite3.connect(path)
    try:
        connection.executescript(SCHEMA)
        connection.execute(
            "INSERT INTO plays "
            "(track_key, title, artist, album, source, yandex_id, started_at, listened_ms, duration_ms, completed) "
            "VALUES ('a', 'A', 'Alpha', '', 'test', NULL, ?, 40000, 200000, 0)",
            (int(time.time()),),
        )
        connection.commit()
    finally:
        connection.close()

    status, _, body = _get(overlay.port, "/api/stats?period=all")
    assert status == 200
    payload = json.loads(body)
    assert payload["plays"] == 1
    assert payload["listened_ms"] == 40_000

    status, _, body = _get(overlay.port, "/api/stats?period=wrong")
    assert status == 200
    assert json.loads(body)["plays"] == 1


def test_sse_stream(overlay: OverlayServer) -> None:
    overlay.state.set({"has_track": True, "title": "Пыяла"})
    sock = socket.create_connection(("127.0.0.1", overlay.port), timeout=5)
    try:
        sock.sendall(b"GET /events HTTP/1.1\r\nHost: 127.0.0.1\r\nAccept: text/event-stream\r\n\r\n")
        data = b""
        while data.count(b"\n\n") < 2:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
    finally:
        sock.close()
    assert b"text/event-stream" in data
    assert b"retry: 2000" in data
    assert b"data: {" in data
    assert b'"title": "\\u041f' in data or "Пыяла".encode() in data


def test_start_is_idempotent_and_stop_is_safe(tmp_path: Path) -> None:
    port = _free_port()
    server = OverlayServer(port=port, stats_path=tmp_path / "stats.db")
    assert server.start() is True
    assert server.start() is True
    assert server.running is True
    assert server.url == f"http://127.0.0.1:{port}/"
    server.stop()
    assert server.running is False
    server.stop()


def test_missing_overlay_html_falls_back(monkeypatch, tmp_path: Path) -> None:
    from ymrpc.services import overlay as overlay_module

    monkeypatch.setattr(overlay_module, "resource_path", lambda name: tmp_path / "missing.html")
    server = OverlayServer(port=_free_port(), stats_path=tmp_path / "stats.db")
    html = server.overlay_html()
    # HTML загружается только при старте.
    assert html == ""
    assert server.start() is True
    try:
        assert "not found" in server.overlay_html()
    finally:
        server.stop()
