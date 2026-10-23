"""Обновления: версии, выбор файла и загрузка."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import os

import httpx
import pytest

from ymrpc.models import UpdateInfo
from ymrpc.services import updater
from ymrpc.services.updater import (
    Updater,
    _safe_name,
    is_newer,
    launch_installer,
    parse_version,
)


def test_parse_version() -> None:
    assert parse_version("1.2.3") == (1, 2, 3, 0)
    assert parse_version("v1.2") == (1, 2, 0, 0)
    assert parse_version("1") == (1, 0, 0, 0)
    assert parse_version("10.20.30.40") == (10, 20, 30, 40)
    assert parse_version("2.0.0-beta.1") == (2, 0, 0, 0)
    assert parse_version("abc") == (0,)
    assert parse_version("") == (0,)


def test_is_newer() -> None:
    assert is_newer("0.1.0", "0.2.0") is True
    assert is_newer("0.1.0", "v0.1.0") is False
    assert is_newer("0.1.0", "0.1.0.1") is True
    assert is_newer("1.0.0", "0.9.9") is False
    assert is_newer("0.1.0", "0.1") is False


def test_safe_name() -> None:
    assert _safe_name("YMRPC Setup.exe") == "YMRPC_Setup.exe"
    assert _safe_name("../../evil?.exe") == "evil_.exe"
    assert _safe_name("C:\\temp\\evil.exe") == "evil.exe"
    assert _safe_name("") == "update.exe"
    assert _safe_name("..") == "update.exe"
    assert _safe_name("con.exe") == "_con.exe"
    assert len(_safe_name("x" * 500)) == 120
    assert len(_safe_name("x" * 500 + ".exe")) == 120
    assert _safe_name("x" * 500 + ".exe").endswith(".exe")


class FakeResponse:
    def __init__(self, status: int = 200, data=None, *, error: Exception | None = None):
        self.status_code = status
        self._data = data
        self._error = error

    def json(self):
        if self._error:
            raise self._error
        return self._data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPError(f"HTTP {self.status_code}")


class FakeClient:
    response: FakeResponse = FakeResponse()
    stream_response = None
    instances: list[FakeClient] = []

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.urls: list[str] = []
        FakeClient.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args) -> bool:
        return False

    async def get(self, url: str) -> FakeResponse:
        self.urls.append(url)
        return FakeClient.response

    def stream(self, method: str, url: str):
        return FakeClient.stream_response


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _check(monkeypatch, response: FakeResponse, current: str = "0.1.0", repo: str = "owner/repo"):
    FakeClient.response = response
    FakeClient.instances = []
    monkeypatch.setattr(updater.httpx, "AsyncClient", FakeClient)
    return asyncio.run(Updater(current).check(repo))


def test_check_skips_empty_repo(monkeypatch) -> None:
    assert _check(monkeypatch, FakeResponse(data={}), repo="") is None
    assert FakeClient.instances == []


def test_request_hook_is_async_and_validates_host() -> None:
    hook = updater._request_hook({"api.github.com"})
    allowed = httpx.Request("GET", "https://api.github.com/repos/owner/repo/releases/latest")
    assert asyncio.run(hook(allowed)) is None

    blocked = httpx.Request("GET", "https://evil.example/releases/latest")
    with pytest.raises(RuntimeError):
        asyncio.run(hook(blocked))


def test_check_handles_404(monkeypatch) -> None:
    assert _check(monkeypatch, FakeResponse(status=404, data={})) is None


def test_check_handles_server_error(monkeypatch) -> None:
    assert _check(monkeypatch, FakeResponse(status=500, data={})) is None


def test_check_handles_invalid_json(monkeypatch) -> None:
    response = FakeResponse(data=None, error=ValueError("bad json"))
    assert _check(monkeypatch, response) is None


def test_check_ignores_same_or_older_version(monkeypatch) -> None:
    data = {"tag_name": "v0.1.0", "html_url": "https://example.com"}
    assert _check(monkeypatch, FakeResponse(data=data)) is None
    data["tag_name"] = "v0.0.9"
    assert _check(monkeypatch, FakeResponse(data=data)) is None


def test_check_returns_update_and_prefers_installer(monkeypatch) -> None:
    base = "https://github.com/owner/repo/releases/download/v1.2.3/"
    data = {
        "tag_name": "v1.2.3",
        "html_url": "https://github.com/owner/repo/releases/tag/v1.2.3",
        "body": "Заметки",
        "assets": [
            {
                "name": "portable.exe",
                "size": 500,
                "browser_download_url": base + "portable.exe",
                "digest": _digest(b"portable"),
            },
            {
                "name": "YMRPC-Setup.exe",
                "size": 100,
                "browser_download_url": base + "setup.exe",
                "digest": _digest(b"setup"),
            },
            {
                "name": "archive.zip",
                "size": 900,
                "browser_download_url": base + "archive.zip",
                "digest": _digest(b"archive"),
            },
        ],
    }
    info = _check(monkeypatch, FakeResponse(data=data))
    assert info is not None
    assert info.version == "1.2.3"
    assert info.tag == "v1.2.3"
    assert info.asset_url == base + "setup.exe"
    assert info.asset_name == "YMRPC-Setup.exe"
    assert info.sha256 == hashlib.sha256(b"setup").hexdigest()
    assert info.notes == "Заметки"
    assert "releases/tag" in info.page_url


def test_check_falls_back_to_zip(monkeypatch) -> None:
    data = {
        "tag_name": "v2.0.0",
        "assets": [
            {
                "name": "build.zip",
                "size": 10,
                "browser_download_url": "https://github.com/owner/repo/releases/download/v2/build.zip",
                "digest": _digest(b"zip"),
            }
        ],
    }
    info = _check(monkeypatch, FakeResponse(data=data))
    assert info is not None
    assert info.asset_url.endswith("/build.zip")
    assert info.sha256 == hashlib.sha256(b"zip").hexdigest()


def test_check_ignores_asset_without_digest(monkeypatch) -> None:
    data = {
        "tag_name": "v2.0.0",
        "assets": [
            {
                "name": "app.exe",
                "size": 10,
                "browser_download_url": "https://github.com/owner/repo/releases/download/v2/app.exe",
            }
        ],
    }
    info = _check(monkeypatch, FakeResponse(data=data))
    assert info is not None
    assert info.asset_url is None
    assert info.sha256 == ""


def test_check_ignores_untrusted_asset_host(monkeypatch) -> None:
    data = {
        "tag_name": "v2.0.0",
        "assets": [
            {
                "name": "app.exe",
                "size": 10,
                "browser_download_url": "https://evil.example/app.exe",
                "digest": _digest(b"app"),
            }
        ],
    }
    info = _check(monkeypatch, FakeResponse(data=data))
    assert info is not None
    assert info.asset_url is None


def test_check_rejects_untrusted_page_url(monkeypatch) -> None:
    data = {
        "tag_name": "v2.0.0",
        "html_url": "https://evil.example/release",
        "assets": [],
    }
    info = _check(monkeypatch, FakeResponse(data=data))
    assert info is not None
    assert info.page_url == ""


def test_check_without_assets(monkeypatch) -> None:
    data = {"tag_name": "v2.0.0", "assets": []}
    info = _check(monkeypatch, FakeResponse(data=data))
    assert info is not None
    assert info.asset_url is None
    assert info.asset_name == ""


class FakeStream:
    def __init__(self, payload: bytes, total: int | None = None):
        self.payload = payload
        self.headers = {"content-length": str(len(payload) if total is None else total)}
        self.status_code = 200

    def raise_for_status(self) -> None:
        return None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args) -> bool:
        return False

    async def aiter_bytes(self, size: int):
        for index in range(0, len(self.payload), size):
            yield self.payload[index : index + size]


def _update(url: str = "https://github.com/owner/repo/releases/download/v1/app.exe", name: str = "app.exe") -> UpdateInfo:
    return UpdateInfo(
        version="1.0",
        tag="v1.0",
        page_url="",
        asset_url=url,
        asset_name=name,
        sha256=hashlib.sha256(b"abc" * 100).hexdigest(),
    )


def test_download_writes_file_and_reports_progress(monkeypatch, tmp_path) -> None:
    FakeClient.stream_response = FakeStream(b"abc" * 100)
    monkeypatch.setattr(updater.httpx, "AsyncClient", FakeClient)
    events: list[tuple[int, int, int]] = []
    target = asyncio.run(
        Updater("0.1.0").download(
            _update(),
            progress=lambda percent, done, total: events.append((percent, done, total)),
            target_dir=tmp_path,
        )
    )
    assert target == tmp_path / "app.exe"
    assert target.read_bytes() == b"abc" * 100
    assert not target.with_suffix(".exe.part").exists()
    assert events[-1] == (100, 300, 300)
    assert events[0][0] == 100  # один чанк


def test_download_requires_asset() -> None:
    update = UpdateInfo(version="1", tag="v1", page_url="")
    with pytest.raises(RuntimeError):
        asyncio.run(Updater("0.1.0").download(update))


def test_download_requires_digest(monkeypatch, tmp_path) -> None:
    FakeClient.stream_response = FakeStream(b"abc")
    monkeypatch.setattr(updater.httpx, "AsyncClient", FakeClient)
    update = UpdateInfo(
        version="1",
        tag="v1",
        page_url="",
        asset_url="https://github.com/owner/repo/releases/download/v1/app.exe",
        asset_name="app.exe",
    )
    with pytest.raises(RuntimeError):
        asyncio.run(Updater("0.1.0").download(update, target_dir=tmp_path))


def test_download_rejects_checksum_mismatch(monkeypatch, tmp_path) -> None:
    FakeClient.stream_response = FakeStream(b"abc")
    monkeypatch.setattr(updater.httpx, "AsyncClient", FakeClient)
    update = UpdateInfo(
        version="1",
        tag="v1",
        page_url="",
        asset_url="https://github.com/owner/repo/releases/download/v1/app.exe",
        asset_name="app.exe",
        sha256="0" * 64,
    )
    with pytest.raises(RuntimeError):
        asyncio.run(Updater("0.1.0").download(update, target_dir=tmp_path))
    assert not (tmp_path / "app.exe").exists()
    assert not (tmp_path / "app.exe.part").exists()


def test_download_rejects_too_large_update(monkeypatch, tmp_path) -> None:
    FakeClient.stream_response = FakeStream(b"x" * 100, total=100)
    monkeypatch.setattr(updater.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(updater, "UPDATE_MAX_BYTES", 10)
    with pytest.raises(RuntimeError):
        asyncio.run(Updater("0.1.0").download(_update(), target_dir=tmp_path))


def test_launch_installer(monkeypatch, tmp_path) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(updater.subprocess, "Popen", lambda args: calls.append(args))
    setup = tmp_path / "setup.exe"
    setup.write_bytes(b"MZ")
    assert launch_installer(setup) is True
    assert calls == [[str(setup)]]

    archive = tmp_path / "archive.zip"
    archive.write_bytes(b"PK")
    assert launch_installer(archive) is True
    assert calls[-1][:2] == ["explorer", "/select,"]

    def broken(args):
        raise OSError("nope")

    monkeypatch.setattr(updater.subprocess, "Popen", broken)
    assert launch_installer(setup) is False


def test_launch_installer_rejects_missing_and_outside_files(monkeypatch, tmp_path) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(updater.subprocess, "Popen", lambda args: calls.append(args))
    missing = tmp_path / "missing.exe"
    assert launch_installer(missing) is False

    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside.exe"
    outside.write_bytes(b"MZ")
    assert launch_installer(outside, allowed_root=allowed) is False
    assert calls == []


def test_launch_installer_rejects_other_extensions(monkeypatch, tmp_path) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(updater.subprocess, "Popen", lambda args: calls.append(args))
    script = tmp_path / "update.bat"
    script.write_text("echo hi", encoding="utf-8")
    assert launch_installer(script) is False
    assert calls == []


def test_portable_build_replaces_itself(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(updater.sys, "frozen", True, raising=False)
    monkeypatch.setattr(updater.sys, "executable", str(tmp_path / "old" / "YMRPC-Next.exe"))
    calls: list[tuple[list[str], dict]] = []
    monkeypatch.setattr(
        updater.subprocess, "Popen", lambda args, **kwargs: calls.append((args, kwargs))
    )
    downloaded = tmp_path / "YMRPC-Next.exe"
    downloaded.write_bytes(b"MZ")

    assert launch_installer(downloaded) is True
    args, kwargs = calls[0]
    assert args[0] == "powershell.exe"
    assert args[-2] == "-EncodedCommand"
    assert kwargs["close_fds"] is True

    script = base64.b64decode(args[-1]).decode("utf-16-le")
    assert f"Wait-Process -Id {os.getpid()}" in script
    assert str(downloaded) in script
    assert str(tmp_path / "old" / "YMRPC-Next.exe") in script
    assert "Copy-Item" in script
    assert "Start-Process" in script


def test_installer_is_not_self_replaced(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(updater.sys, "frozen", True, raising=False)
    calls: list[list[str]] = []
    monkeypatch.setattr(updater.subprocess, "Popen", lambda args, **kwargs: calls.append(args))
    setup = tmp_path / "YMRPC-Next-Setup.exe"
    setup.write_bytes(b"MZ")

    assert launch_installer(setup) is True
    assert calls == [[str(setup)]]

