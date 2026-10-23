"""Хранение OAuth-токена: DPAPI, отказ при ошибке и валидация формата."""

from __future__ import annotations

import sys

import pytest

from ymrpc import secure_store
from ymrpc.secure_store import TokenStore, validate_token_format

TOKEN = "y0_" + "a" * 40


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI доступен только в Windows")
def test_dpapi_roundtrip_does_not_store_plaintext(tmp_path) -> None:
    path = tmp_path / "token.bin"
    store = TokenStore(path)
    store.save(TOKEN)

    assert store.load() == TOKEN
    raw = path.read_bytes()
    assert TOKEN.encode() not in raw
    assert not path.with_suffix(".bin.tmp").exists()

    store.delete()
    assert store.load() is None


def test_empty_token_is_rejected(tmp_path) -> None:
    with pytest.raises(ValueError):
        TokenStore(tmp_path / "token.bin").save("   ")


def test_corrupt_token_file_is_ignored(tmp_path) -> None:
    path = tmp_path / "token.bin"
    path.write_bytes(b"not a dpapi blob")
    assert TokenStore(path).load() is None


def test_protect_failure_is_fail_closed(monkeypatch, tmp_path) -> None:
    path = tmp_path / "token.bin"

    def broken(_data: bytes) -> bytes:
        raise OSError("DPAPI is unavailable")

    monkeypatch.setattr(secure_store, "_protect", broken)
    with pytest.raises(OSError):
        TokenStore(path).save(TOKEN)

    assert not path.exists()
    assert not path.with_suffix(".bin.tmp").exists()


@pytest.mark.parametrize(
    "token",
    [
        "y0_" + "a" * 40,
        "AQAA" + "b" * 40,
        "a" * 20,
        "abc.def-_~+/=" + "x" * 20,
    ],
)
def test_valid_token_formats(token: str) -> None:
    assert validate_token_format(token) is True


@pytest.mark.parametrize(
    "token",
    [
        "",
        "short",
        "a" * 19,
        "a" * 4097,
        "token with spaces " + "a" * 20,
        "токен" * 10,
        "a" * 20 + "\x00",
    ],
)
def test_invalid_token_formats(token: str) -> None:
    assert validate_token_format(token) is False
