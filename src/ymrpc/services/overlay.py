"""Локальный HTTP-сервер: оверлей для OBS, SSE и JSON API."""

from __future__ import annotations

import contextlib
import json
import logging
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ..constants import COVER_MAX_BYTES, art_cache_dir, resource_path
from ..models import Period
from . import stats as stats_module

logger = logging.getLogger(__name__)

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
_ART_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def _valid_host_header(value: str | None) -> bool:
    """Защита от DNS rebinding: Host должен указывать на loopback."""
    if not value:
        return False
    value = value.strip().lower()
    if value.startswith("["):
        host, _, rest = value[1:].partition("]")
        if rest and (not rest.startswith(":") or not rest[1:].isdigit()):
            return False
        return host == "::1"
    host, separator, port = value.partition(":")
    if separator and (not port.isdigit() or not 0 < int(port) < 65536):
        return False
    return host in _LOOPBACK_HOSTS


def _loopback_origin(value: str | None) -> bool:
    if not value:
        return False
    try:
        parts = urlparse(value)
        _ = parts.port
    except ValueError:
        return False
    if parts.scheme != "http" or parts.username or parts.password:
        return False
    host = (parts.hostname or "").lower().rstrip(".")
    return host in _LOOPBACK_HOSTS


class OverlayState:
    """Потокобезопасный снимок состояния для HTTP-потока."""

    def __init__(self):
        self._lock = threading.Lock()
        self._data: dict = {"has_track": False, "status": "stopped"}
        self._art_path: Path | None = None
        self._version = 0

    def set(self, data: dict, art_path: str | Path | None = None) -> None:
        with self._lock:
            self._version += 1
            payload = dict(data)
            # Абсолютный путь никогда не попадает в публичный JSON.
            payload.pop("art_path", None)
            payload["updated_at"] = time.time()
            payload["version"] = self._version
            self._data = payload
            self._art_path = Path(art_path) if art_path else None

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._data)

    def art_path(self) -> Path | None:
        with self._lock:
            return self._art_path


class OverlayServer:
    def __init__(
        self,
        port: int = 8765,
        host: str = "127.0.0.1",
        state: OverlayState | None = None,
        stats_path: Path | None = None,
        art_dir: Path | None = None,
    ):
        self.host = host
        self.port = port
        self.state = state or OverlayState()
        self.stats_path = stats_path
        self.art_dir = (art_dir or art_cache_dir()).resolve()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.error = ""
        self._html = ""

    @property
    def running(self) -> bool:
        return self._server is not None

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/"

    def start(self) -> bool:
        if self._server is not None:
            return True
        self._stop.clear()
        self._html = _load_overlay()
        try:
            server = ThreadingHTTPServer((self.host, self.port), _handler_factory(self))
            server.daemon_threads = True
            self._server = server
        except OSError as error:
            self.error = str(error)
            logger.warning("Оверлей не запущен: %s", error)
            return False
        self._thread = threading.Thread(target=server.serve_forever, name="overlay", daemon=True)
        self._thread.start()
        logger.info("Оверлей запущен: %s", self.url)
        return True

    def stop(self) -> None:
        self._stop.set()
        server, self._server = self._server, None
        if server is not None:
            server.shutdown()
            server.server_close()
        thread, self._thread = self._thread, None
        if thread is not None and thread.is_alive():
            thread.join(timeout=2)

    def stopping(self) -> threading.Event:
        """Событие остановки для SSE-потоков."""
        return self._stop

    def snapshot(self) -> dict:
        return self.state.snapshot()

    def overlay_html(self) -> str:
        return self._html


def _load_overlay() -> str:
    path = resource_path("overlay/index.html")
    try:
        return path.read_text(encoding="utf-8")
    except OSError as error:
        logger.error("Не найден HTML оверлея: %s", error)
        return "<!doctype html><title>YMRPC Next</title><body style='background:#111;color:#fff'>Overlay HTML not found</body>"


def _handler_factory(server: OverlayServer):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):  # noqa: A003
            logger.debug("overlay: " + fmt, *args)

        def _host_allowed(self) -> bool:
            if _valid_host_header(self.headers.get("Host")):
                return True
            self._json({"error": "invalid host"}, HTTPStatus.MISDIRECTED_REQUEST)
            return False

        def _cors_headers(self) -> None:
            origin = self.headers.get("Origin")
            self.send_header("Vary", "Origin")
            if _loopback_origin(origin):
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")

        def _security_headers(self) -> None:
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")

        def do_OPTIONS(self):  # noqa: N802
            if not self._host_allowed():
                return
            self.send_response(HTTPStatus.NO_CONTENT)
            self._cors_headers()
            self._security_headers()
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self):  # noqa: N802
            if not self._host_allowed():
                return
            parsed = urlparse(self.path)
            path = parsed.path
            if path in ("/", "/index.html", "/overlay") or path == "/widget":
                self._html()
            elif path == "/api/now-playing":
                self._json(server.snapshot())
            elif path == "/api/stats":
                period = (parse_qs(parsed.query).get("period", ["week"])[0] or "week")
                try:
                    value = Period(period)
                except ValueError:
                    value = Period.WEEK
                self._json(stats_module.summary(server.stats_path, value))
            elif path == "/api/art":
                self._art(server)
            elif path == "/events":
                self._events(server)
            elif path == "/health":
                self._json({"ok": True, "version": server.snapshot().get("version", 0)})
            elif path == "/favicon.ico":
                self.send_response(HTTPStatus.NO_CONTENT)
                self._security_headers()
                self.send_header("Content-Length", "0")
                self.end_headers()
            else:
                self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)

        def _html(self):
            body = server.overlay_html().encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                "script-src 'self' 'unsafe-inline'; connect-src 'self'; object-src 'none'; "
                "base-uri 'none'; form-action 'none'; frame-ancestors 'self'",
            )
            self.send_header("X-Frame-Options", "SAMEORIGIN")
            self._security_headers()
            self._cors_headers()
            self.end_headers()
            self.wfile.write(body)

        def _json(self, payload: dict, status=HTTPStatus.OK):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self._security_headers()
            self._cors_headers()
            self.end_headers()
            self.wfile.write(body)

        def _art(self, server: OverlayServer):
            path = server.state.art_path()
            if path is None:
                self._json({"error": "no art"}, HTTPStatus.NOT_FOUND)
                return
            try:
                file = path.resolve(strict=True)
                if not file.is_relative_to(server.art_dir) or not file.is_file():
                    self._json({"error": "no art"}, HTTPStatus.NOT_FOUND)
                    return
                data = file.read_bytes()
            except (OSError, RuntimeError):
                self._json({"error": "no art"}, HTTPStatus.NOT_FOUND)
                return
            content_type = _ART_TYPES.get(file.suffix.lower())
            if content_type is None or not data or len(data) > COVER_MAX_BYTES:
                self._json({"error": "no art"}, HTTPStatus.NOT_FOUND)
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "public, max-age=86400")
            self._security_headers()
            self._cors_headers()
            self.end_headers()
            with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                self.wfile.write(data)

        def _events(self, server: OverlayServer):
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self._security_headers()
            self._cors_headers()
            self.end_headers()
            try:
                self.wfile.write(b"retry: 2000\n\n")
                stopping = server.stopping()
                while not stopping.is_set():
                    payload = json.dumps(server.snapshot(), ensure_ascii=False)
                    self.wfile.write(f"data: {payload}\n\n".encode())
                    self.wfile.flush()
                    if stopping.wait(1.0):
                        break
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, OSError):
                return

    return Handler

