"""Проверка URL перед открытием в браузере и отправкой в Discord."""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _split(value: str):
    if not isinstance(value, str) or not value or len(value) > 4096:
        return None
    try:
        return urlsplit(value)
    except ValueError:
        return None


def _has_credentials(parts) -> bool:
    return parts.username is not None or parts.password is not None


def _public_ip(value: str) -> bool:
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


def is_loopback_http_url(value: str) -> bool:
    """Разрешён только HTTP-адрес локального оверлея."""
    parts = _split(value)
    if parts is None or parts.scheme != "http" or _has_credentials(parts):
        return False
    try:
        _ = parts.port
    except ValueError:
        return False
    host = (parts.hostname or "").lower().rstrip(".")
    return host in _LOOPBACK_HOSTS


def is_https_url(value: str, allowed_hosts: set[str] | None = None) -> bool:
    """HTTPS-адрес без учётных данных, локальных IP и лишних портов."""
    parts = _split(value)
    if parts is None or parts.scheme != "https" or _has_credentials(parts):
        return False
    try:
        port = parts.port
    except ValueError:
        return False
    if port not in (None, 443):
        return False
    host = (parts.hostname or "").lower().rstrip(".")
    if not host or host == "localhost" or host.endswith(".local") or host.endswith(".localhost"):
        return False
    if allowed_hosts is not None:
        allowed = {item.lower().rstrip(".") for item in allowed_hosts}
        if host not in allowed:
            return False
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return True
    return _public_ip(host)


def is_public_https_url(value: str) -> bool:
    return is_https_url(value)
