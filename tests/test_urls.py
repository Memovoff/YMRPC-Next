"""Проверки URL для локального оверлея, Discord и внешних ссылок."""

from __future__ import annotations

import pytest

from ymrpc.urls import is_https_url, is_loopback_http_url, is_public_https_url


@pytest.mark.parametrize(
    "value",
    [
        "http://127.0.0.1:8765/",
        "http://localhost:8765/widget?compact=1",
        "http://[::1]:8765/?theme=dark",
        "http://127.0.0.1/",
    ],
)
def test_loopback_http_urls_are_allowed(value: str) -> None:
    assert is_loopback_http_url(value) is True


@pytest.mark.parametrize(
    "value",
    [
        "",
        "https://127.0.0.1:8765/",
        "http://example.com/",
        "http://127.0.0.1.evil.example/",
        "http://user:pass@127.0.0.1:8765/",
        "http://127.0.0.1:99999/",
        "http://127.0.0.1:notaport/",
        "javascript:alert(1)",
        "file:///C:/Windows/System32/calc.exe",
        "http://" + "a" * 5000,
    ],
)
def test_unsafe_loopback_urls_are_rejected(value: str) -> None:
    assert is_loopback_http_url(value) is False


@pytest.mark.parametrize(
    "value",
    [
        "https://music.yandex.ru/track/1",
        "https://github.com/owner/repo/releases/tag/v1",
        "https://example.com/cover.jpg",
        "https://8.8.8.8/cover.jpg",
    ],
)
def test_public_https_urls_are_allowed(value: str) -> None:
    assert is_https_url(value) is True
    assert is_public_https_url(value) is True


@pytest.mark.parametrize(
    "value",
    [
        "",
        "http://example.com/cover.jpg",
        "https://localhost/cover.jpg",
        "https://127.0.0.1/cover.jpg",
        "https://10.0.0.1/cover.jpg",
        "https://192.168.1.1/cover.jpg",
        "https://[::1]/cover.jpg",
        "https://example.com:8443/cover.jpg",
        "https://user:pass@example.com/cover.jpg",
        "https://example.local/cover.jpg",
        "javascript:alert(1)",
    ],
)
def test_unsafe_https_urls_are_rejected(value: str) -> None:
    assert is_https_url(value) is False


def test_https_host_allowlist() -> None:
    assert is_https_url("https://github.com/owner/repo", {"github.com"}) is True
    assert is_https_url("https://api.github.com/repos/x/y", {"github.com"}) is False
    assert is_https_url("https://github.com.evil.example/", {"github.com"}) is False
    assert is_https_url("https://github.com:443/owner/repo", {"github.com"}) is True
