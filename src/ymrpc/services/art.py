"""Кэш обложек на диске: скачивание по URL и сохранение миниатюр SMTC."""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import logging
import socket
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx

from ..constants import COVER_MAX_BYTES, HTTP_USER_AGENT, art_cache_dir

logger = logging.getLogger(__name__)

_MAX_REDIRECTS = 5
_IMAGE_MAGIC = {
    b"\xff\xd8\xff": (".jpg", "image/jpeg"),
    b"\x89PNG\r\n\x1a\n": (".png", "image/png"),
    b"GIF87a": (".gif", "image/gif"),
    b"GIF89a": (".gif", "image/gif"),
}
_DECLARED_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp", "image/gif"}


def _detect_image(data: bytes) -> tuple[str, str] | None:
    for magic, result in _IMAGE_MAGIC.items():
        if data.startswith(magic):
            return result
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp", "image/webp"
    return None


def _is_global_address(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return address.is_global and not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


class ArtCache:
    def __init__(self, directory: Path | None = None):
        self.directory = directory or art_cache_dir()
        self.directory.mkdir(parents=True, exist_ok=True)
        self._client: httpx.AsyncClient | None = None
        self._validated_hosts: set[str] = set()

    def _http(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(10, connect=5),
                headers={"User-Agent": HTTP_USER_AGENT},
                follow_redirects=False,
                trust_env=False,
            )
        return self._client

    def path_for(self, key: str) -> Path | None:
        for suffix in (".jpg", ".png", ".webp", ".gif"):
            candidate = self.directory / (hashlib.sha1(key.encode("utf-8")).hexdigest() + suffix)
            if candidate.exists():
                return candidate
        return None

    async def _ensure_public_url(self, url: str) -> None:
        try:
            parts = urlsplit(url)
            port = parts.port
        except ValueError as error:
            raise ValueError("invalid cover url") from error
        if parts.scheme != "https" or parts.username or parts.password:
            raise ValueError("cover url must use https without credentials")
        if port not in (None, 443):
            raise ValueError("unexpected cover url port")
        host = (parts.hostname or "").lower().rstrip(".")
        if not host or host == "localhost" or host.endswith(".local") or host.endswith(".localhost"):
            raise ValueError("local cover url is not allowed")
        if host in self._validated_hosts:
            return
        try:
            ipaddress.ip_address(host)
        except ValueError:
            loop = asyncio.get_running_loop()
            try:
                infos = await asyncio.wait_for(
                    loop.getaddrinfo(host, 443, type=socket.SOCK_STREAM), timeout=5
                )
            except (OSError, TimeoutError) as error:
                raise ValueError("cover host cannot be resolved") from error
            addresses = {info[4][0] for info in infos}
            if not addresses or any(not _is_global_address(item) for item in addresses):
                raise ValueError("cover host resolves to a non-public address") from None
        else:
            if not _is_global_address(host):
                raise ValueError("non-public cover address")
        self._validated_hosts.add(host)

    async def _fetch(self, url: str) -> httpx.Response | None:
        current = url
        for _ in range(_MAX_REDIRECTS + 1):
            await self._ensure_public_url(current)
            response = await self._http().get(current, follow_redirects=False)
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("location")
                if not location:
                    return None
                current = urljoin(current, location)
                continue
            return response
        return None

    async def from_url(self, url: str, key: str | None = None) -> Path | None:
        if not url:
            return None
        key = key or url
        existing = self.path_for(key)
        if existing is not None:
            return existing
        try:
            response = await self._fetch(url)
            if response is None or response.status_code != 200:
                return None
            content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
            if content_type and content_type not in _DECLARED_TYPES:
                return None
            data = response.content
            if not data or len(data) > COVER_MAX_BYTES:
                return None
            return self.save(data, content_type, key)
        except (httpx.HTTPError, OSError, ValueError, RuntimeError) as error:
            logger.debug("Не удалось скачать обложку: %s", error)
            return None

    def save(self, data: bytes, content_type: str, key: str) -> Path | None:
        if not data or len(data) > COVER_MAX_BYTES:
            return None
        declared = (content_type or "").split(";")[0].strip().lower()
        if declared and declared not in _DECLARED_TYPES:
            return None
        detected = _detect_image(data)
        if detected is None:
            return None
        suffix, _mime = detected
        target = self.directory / (hashlib.sha1(key.encode("utf-8")).hexdigest() + suffix)
        temporary = target.with_suffix(target.suffix + ".tmp")
        try:
            temporary.write_bytes(data)
            temporary.replace(target)
            return target
        except OSError as error:
            logger.debug("Не удалось сохранить обложку: %s", error)
            temporary.unlink(missing_ok=True)
            return None

    def cleanup(self, days: int = 30) -> None:
        cutoff = time.time() - days * 86400
        for file in self.directory.glob("*"):
            try:
                if file.is_file() and file.stat().st_mtime < cutoff:
                    file.unlink()
            except OSError:
                continue

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
