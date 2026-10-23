"""Кэш обложек: SSRF-защита, проверка MIME и магических байтов."""

from __future__ import annotations

import asyncio
import os

import pytest

from ymrpc.services import art
from ymrpc.services.art import ArtCache, _detect_image, _is_global_address

PNG = b"\x89PNG\r\n\x1a\n" + b"payload"


class FakeResponse:
    def __init__(
        self,
        status: int = 200,
        content: bytes = b"",
        headers: dict[str, str] | None = None,
    ):
        self.status_code = status
        self.content = content
        self.headers = headers or {}


class FakeClient:
    def __init__(self, responses: list[FakeResponse]):
        self.responses = responses
        self.calls: list[str] = []
        self.is_closed = False

    async def get(self, url: str, follow_redirects: bool = False) -> FakeResponse:
        assert follow_redirects is False
        self.calls.append(url)
        return self.responses.pop(0)


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (PNG, (".png", "image/png")),
        (b"\xff\xd8\xff" + b"jpg", (".jpg", "image/jpeg")),
        (b"GIF89a" + b"gif", (".gif", "image/gif")),
        (b"RIFF\x00\x00\x00\x00WEBP" + b"webp", (".webp", "image/webp")),
        (b"<html>", None),
        (b"", None),
    ],
)
def test_detect_image(data: bytes, expected) -> None:
    assert _detect_image(data) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("8.8.8.8", True),
        ("1.1.1.1", True),
        ("127.0.0.1", False),
        ("10.0.0.1", False),
        ("192.168.1.1", False),
        ("169.254.1.1", False),
        ("::1", False),
        ("::ffff:127.0.0.1", False),
        ("not-an-ip", False),
    ],
)
def test_global_address_detection(value: str, expected: bool) -> None:
    assert _is_global_address(value) is expected


@pytest.mark.parametrize(
    "url",
    [
        "http://8.8.8.8/cover.png",
        "https://user:pass@8.8.8.8/cover.png",
        "https://8.8.8.8:8443/cover.png",
        "https://127.0.0.1/cover.png",
        "https://10.0.0.1/cover.png",
        "https://localhost/cover.png",
        "https://localhost./cover.png",
        "https://printer.local/cover.png",
        "not a url",
    ],
)
def test_cover_url_rejects_non_public_or_unsafe_targets(tmp_path, url: str) -> None:
    cache = ArtCache(tmp_path)
    with pytest.raises(ValueError):
        asyncio.run(cache._ensure_public_url(url))


def test_cover_url_accepts_public_ip(tmp_path) -> None:
    cache = ArtCache(tmp_path)
    asyncio.run(cache._ensure_public_url("https://8.8.8.8/cover.png"))


def test_save_checks_declared_type_and_magic_bytes(tmp_path) -> None:
    cache = ArtCache(tmp_path)
    saved = cache.save(PNG, "image/png", "track")
    assert saved is not None
    assert saved.suffix == ".png"
    assert saved.read_bytes() == PNG
    assert cache.path_for("track") == saved

    assert cache.save(b"<html>", "image/png", "html") is None
    assert cache.save(PNG, "text/html", "wrong-type") is None
    assert cache.save(b"", "image/png", "empty") is None


def test_save_rejects_oversized_cover(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(art, "COVER_MAX_BYTES", 8)
    cache = ArtCache(tmp_path)
    assert cache.save(PNG, "image/png", "big") is None


def test_from_url_rejects_redirect_to_private_address(tmp_path) -> None:
    cache = ArtCache(tmp_path)
    fake = FakeClient(
        [FakeResponse(302, headers={"location": "https://127.0.0.1/secret.png"})]
    )
    cache._client = fake

    assert asyncio.run(cache.from_url("https://8.8.8.8/cover.png", "redirect")) is None
    assert fake.calls == ["https://8.8.8.8/cover.png"]


def test_from_url_rejects_html_response(tmp_path) -> None:
    cache = ArtCache(tmp_path)
    fake = FakeClient(
        [FakeResponse(200, content=b"<html>", headers={"content-type": "text/html"})]
    )
    cache._client = fake

    assert asyncio.run(cache.from_url("https://8.8.8.8/cover.png", "html")) is None


def test_cleanup_removes_only_old_files(tmp_path) -> None:
    cache = ArtCache(tmp_path)
    old = tmp_path / "old.png"
    new = tmp_path / "new.png"
    old.write_bytes(PNG)
    new.write_bytes(PNG)
    ancient = 1_000_000
    os.utime(old, (ancient, ancient))

    cache.cleanup(days=30)

    assert not old.exists()
    assert new.exists()
