"""Проверка и загрузка обновлений из GitHub Releases."""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import httpx

from ..constants import HTTP_USER_AGENT, UPDATE_MAX_BYTES
from ..models import UpdateInfo
from ..urls import is_https_url

logger = logging.getLogger(__name__)

_VERSION = re.compile(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:\.(\d+))?")
_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_DIGEST = re.compile(r"^sha256:([0-9a-fA-F]{64})$")
_ALLOWED_API_HOSTS = {"api.github.com"}
_ALLOWED_DOWNLOAD_HOSTS = {
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
    "github-releases.githubusercontent.com",
}
_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


def parse_version(value: str) -> tuple[int, ...]:
    match = _VERSION.search(value.lstrip("vV"))
    if not match:
        return (0,)
    return tuple(int(part) if part else 0 for part in match.groups())


def is_newer(current: str, candidate: str) -> bool:
    left = parse_version(current)
    right = parse_version(candidate)
    length = max(len(left), len(right))
    return right + (0,) * (length - len(right)) > left + (0,) * (length - len(left))


def _validate_url(url: str, allowed_hosts: set[str]) -> None:
    try:
        parts = urlparse(url)
        port = parts.port
    except ValueError as error:
        raise RuntimeError("invalid update url") from error
    if parts.scheme != "https" or parts.username or parts.password:
        raise RuntimeError("update url must use https without credentials")
    host = (parts.hostname or "").lower().rstrip(".")
    if host not in allowed_hosts:
        raise RuntimeError(f"untrusted update host: {host or '<empty>'}")
    if port not in (None, 443):
        raise RuntimeError("untrusted update port")


def _request_hook(allowed_hosts: set[str]):
    async def hook(request: httpx.Request) -> None:
        _validate_url(str(request.url), allowed_hosts)

    return hook


def _asset_digest(asset: dict) -> str:
    value = str(asset.get("digest") or "").strip().lower()
    match = _DIGEST.fullmatch(value)
    return match.group(1) if match else ""


def _asset_url(asset: dict) -> str | None:
    value = str(asset.get("browser_download_url") or "").strip()
    if not value:
        return None
    try:
        _validate_url(value, _ALLOWED_DOWNLOAD_HOSTS)
    except RuntimeError:
        return None
    return value


def _asset_name(asset: dict) -> str:
    value = str(asset.get("name") or "").strip()
    if not value or Path(value).name != value:
        return ""
    return value


class Updater:
    def __init__(self, current_version: str):
        self.current_version = current_version

    async def check(self, repo: str) -> UpdateInfo | None:
        if not repo or not _REPO.fullmatch(repo):
            return None
        url = f"https://api.github.com/repos/{repo}/releases/latest"
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(10, connect=5),
                headers={"User-Agent": HTTP_USER_AGENT, "Accept": "application/vnd.github+json"},
                follow_redirects=True,
                event_hooks={"request": [_request_hook(_ALLOWED_API_HOSTS)]},
            ) as client:
                response = await client.get(url)
                if response.status_code == 404:
                    logger.info("Релизы %s не найдены", repo)
                    return None
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, RuntimeError, ValueError) as error:
            logger.info("Не удалось проверить обновления: %s", error)
            return None

        if not isinstance(data, dict):
            return None
        tag = str(data.get("tag_name") or "")
        if not tag or not is_newer(self.current_version, tag):
            return None

        assets = [asset for asset in (data.get("assets") or []) if isinstance(asset, dict)]

        def candidates_with(suffix: str) -> list[dict]:
            return [
                asset
                for asset in assets
                if _asset_name(asset).lower().endswith(suffix)
                and _asset_digest(asset)
                and _asset_url(asset) is not None
            ]

        candidates = candidates_with(".exe") or candidates_with(".zip")
        if not candidates:
            logger.warning("В релизе %s нет файлов с SHA-256 digest", tag)

        asset_url = None
        asset_name = ""
        digest = ""
        if candidates:
            candidates.sort(
                key=lambda asset: (
                    0
                    if any(
                        word in _asset_name(asset).lower()
                        for word in ("setup", "install", "ymrpc")
                    )
                    else 1,
                    -int(asset.get("size") or 0),
                )
            )
            chosen = candidates[0]
            asset_url = _asset_url(chosen)
            asset_name = _asset_name(chosen)
            digest = _asset_digest(chosen)

        page_url = str(data.get("html_url") or "").strip()
        if not is_https_url(page_url, {"github.com"}):
            page_url = ""

        return UpdateInfo(
            version=tag.lstrip("vV"),
            tag=tag,
            page_url=page_url,
            asset_url=asset_url,
            asset_name=asset_name,
            notes=str(data.get("body") or "")[:4000],
            sha256=digest,
        )

    async def download(
        self,
        update: UpdateInfo,
        progress=None,
        target_dir: Path | None = None,
    ) -> Path:
        if not update.asset_url:
            raise RuntimeError("release has no downloadable asset")
        digest_match = _DIGEST.fullmatch(f"sha256:{update.sha256}")
        if not digest_match:
            raise RuntimeError("release asset has no valid SHA-256 digest")
        expected = digest_match.group(1).lower()
        _validate_url(update.asset_url, _ALLOWED_DOWNLOAD_HOSTS)

        if target_dir is None:
            target_dir = Path(tempfile.mkdtemp(prefix="ymrpc-next-update-"))
        else:
            target_dir = Path(target_dir)
            target_dir.mkdir(parents=True, exist_ok=True)
        name = _safe_name(update.asset_name or Path(urlparse(update.asset_url).path).name or "update.exe")
        target = target_dir / name
        partial = target.with_suffix(target.suffix + ".part")

        total = 0
        downloaded = 0
        hasher = hashlib.sha256()
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(30, connect=10),
                headers={"User-Agent": HTTP_USER_AGENT},
                follow_redirects=True,
                event_hooks={"request": [_request_hook(_ALLOWED_DOWNLOAD_HOSTS)]},
            ) as client, client.stream("GET", update.asset_url) as response:
                response.raise_for_status()
                total = int(response.headers.get("content-length") or 0)
                if total > UPDATE_MAX_BYTES:
                    raise RuntimeError("update is too large")
                with partial.open("wb") as stream:
                    async for chunk in response.aiter_bytes(64 * 1024):
                        downloaded += len(chunk)
                        if downloaded > UPDATE_MAX_BYTES:
                            raise RuntimeError("update is too large")
                        hasher.update(chunk)
                        stream.write(chunk)
                        if progress:
                            percent = int(downloaded / total * 100) if total else 0
                            progress(percent, downloaded, total)
            actual = hasher.hexdigest()
            if not hmac.compare_digest(actual, expected):
                raise RuntimeError("update checksum mismatch")
            partial.replace(target)
        except Exception:
            partial.unlink(missing_ok=True)
            raise
        if progress:
            progress(100, downloaded, total or downloaded)
        logger.info("Обновление скачано и проверено: %s", target)
        return target


def _is_within(path: Path, root: Path) -> bool:
    try:
        resolved = path.resolve(strict=True)
        base = root.resolve(strict=True)
    except OSError:
        return False
    resolved_text = os.path.normcase(str(resolved))
    base_text = os.path.normcase(str(base))
    return resolved_text != base_text and resolved_text.startswith(base_text + os.sep)


def launch_installer(path: Path, *, allowed_root: Path | None = None) -> bool:
    try:
        path = Path(path)
        if path.suffix.lower() not in (".exe", ".zip") or not path.is_file():
            logger.warning("Недопустимый файл обновления: %s", path)
            return False
        root = Path(allowed_root) if allowed_root is not None else Path(tempfile.gettempdir())
        if not _is_within(path, root):
            logger.warning("Файл обновления вне временного каталога: %s", path)
            return False
        if path.suffix.lower() == ".zip":
            subprocess.Popen(["explorer", "/select,", str(path)])
        elif _is_portable_update(path):
            return _replace_portable(path)
        else:
            subprocess.Popen([str(path)])
        return True
    except OSError as error:
        logger.warning("Не удалось запустить установщик: %s", error)
        return False


def _is_portable_update(path: Path) -> bool:
    """Однофайловая portable-сборка обновляет себя сама, установщик — нет."""
    if not getattr(sys, "frozen", False) or path.suffix.lower() != ".exe":
        return False
    name = path.name.casefold()
    return not any(word in name for word in ("setup", "install", "unins"))


def _replace_portable(downloaded: Path) -> bool:
    """Ждёт завершения процесса, копирует новый exe поверх старого и запускает его."""
    current = Path(sys.executable)
    if downloaded.resolve() == current.resolve():
        return False
    script = (
        f"Wait-Process -Id {os.getpid()} -ErrorAction SilentlyContinue\r\n"
        f"$new = {_ps_quote(str(downloaded))}\r\n"
        f"$old = {_ps_quote(str(current))}\r\n"
        "for ($i = 0; $i -lt 30; $i++) {\r\n"
        "    try {\r\n"
        "        Copy-Item -LiteralPath $new -Destination $old -Force -ErrorAction Stop\r\n"
        "        Start-Process -FilePath $old\r\n"
        "        break\r\n"
        "    } catch { Start-Sleep -Seconds 1 }\r\n"
        "}\r\n"
    )
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    flags = 0
    if sys.platform == "win32":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(  # noqa: S603
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-WindowStyle",
            "Hidden",
            "-EncodedCommand",
            encoded,
        ],
        creationflags=flags,
        close_fds=True,
    )
    logger.info("Portable-обновление будет установлено после выхода")
    return True


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _safe_name(name: str) -> str:
    base = Path(name.replace("\\", "/")).name
    base = re.sub(r"[^\w.\-]+", "_", base, flags=re.UNICODE).strip(" .")
    suffix = Path(base).suffix.lower()
    if suffix in (".exe", ".zip"):
        stem = base[: -len(suffix)].lstrip(".")
        if not stem:
            stem = "update"
        base = stem[: 120 - len(suffix)] + suffix
    else:
        base = (base or "update")[:116]
        base = base.rstrip(" .")
        base = (base or "update") + ".exe"
    if base.split(".", 1)[0].upper() in _WINDOWS_RESERVED:
        base = "_" + base
    return base
