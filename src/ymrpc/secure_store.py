"""Хранение OAuth-токена с шифрованием Windows DPAPI."""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import logging
import os
import sys
from pathlib import Path

from .constants import data_dir

logger = logging.getLogger(__name__)

CRYPTPROTECT_UI_FORBIDDEN = 0x1


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def _blob(data: bytes) -> tuple[_DataBlob, ctypes.Array]:
    buffer = ctypes.create_string_buffer(data, len(data))
    return _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer


def _require_windows() -> None:
    if sys.platform != "win32":
        raise OSError("Windows DPAPI is unavailable")


def _protect(data: bytes) -> bytes:
    _require_windows()
    source, _source_buffer = _blob(data)
    target = _DataBlob()
    if not ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(source),
        "YMRPC Next token",
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(target),
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(target.pbData)


def _unprotect(data: bytes) -> bytes:
    _require_windows()
    source, _source_buffer = _blob(data)
    target = _DataBlob()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(source),
        None,
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(target),
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(target.pbData)


class TokenStore:
    """Файл с токеном, зашифрованный DPAPI. Ошибка шифрования — отказ, без fallback."""

    def __init__(self, path: Path | None = None):
        self.path = path or (data_dir() / "token.bin")

    def load(self) -> str | None:
        if not self.path.exists():
            return None
        try:
            raw = self.path.read_bytes()
            token = _unprotect(raw).decode("utf-8").strip()
            return token or None
        except Exception as error:  # noqa: BLE001
            logger.warning("Не удалось расшифровать токен (%s); требуется повторный вход", error)
            return None

    def save(self, token: str) -> None:
        token = token.strip()
        if not token:
            raise ValueError("empty token")
        payload = _protect(token.encode("utf-8"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            temporary.write_bytes(payload)
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def delete(self) -> None:
        self.path.unlink(missing_ok=True)


def validate_token_format(token: str) -> bool:
    token = token.strip()
    if len(token) < 20 or len(token) > 4096:
        return False
    from urllib.parse import quote

    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._~+/-=")
    return all(ch in allowed for ch in token) and quote(token, safe="") != ""
