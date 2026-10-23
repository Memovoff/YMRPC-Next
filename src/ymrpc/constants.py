"""Общие константы приложения."""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "YMRPC Next"
APP_SLUG = "YMRPC-Next"
APP_ID = "YMRPCNext.Desktop"
DATA_FOLDER = "YMRPC-Next"

# Discord application IDs. Второй нужен для корректного склонения
# «Слушает Яндекс Музыку» в русской локали Discord.
DISCORD_CLIENT_ID_EN = "1269807014393942046"
DISCORD_CLIENT_ID_RU = "1269826362399522849"

# Публичные картинки Playing/Paused, которые Discord умеет загружать по URL.
ASSETS_URL = "https://raw.githubusercontent.com/Memovoff/YMRPC-Next/main/assets"

OAUTH_URL = (
    "https://oauth.yandex.ru/authorize?response_type=token"
    "&client_id=23cabbbdc6cd418abb4b39c32c41195d"
)

DEFAULT_UPDATE_REPO = "Memovoff/YMRPC-Next"
GITHUB_RELEASES_URL = "https://github.com/{repo}/releases"

YNISON_REDIRECT_URL = (
    "wss://ynison.music.yandex.ru/redirector.YnisonRedirectService/GetRedirectToYnison"
)

SUPPORTED_AUDIO_EXTENSIONS = {".mp3", ".flac", ".wav", ".m4a", ".ogg", ".opus", ".aac"}
COVER_MAX_BYTES = 8 * 1024 * 1024
UPDATE_MAX_BYTES = 350 * 1024 * 1024
HTTP_USER_AGENT = "YMRPC-Next/0.1 (+https://github.com/Memovoff/YMRPC-Next)"


def project_root() -> Path:
    return Path(__file__).resolve().parent


def assets_dir() -> Path:
    return project_root() / "assets"


def resource_path(name: str) -> Path:
    """Ресурс внутри пакета (работает и из PyInstaller --onefile)."""
    import sys

    base = Path(getattr(sys, "_MEIPASS", project_root()))

    for candidate in (base / "ymrpc" / "assets" / name, base / "assets" / name):
        if candidate.exists():
            return candidate
    return assets_dir() / name


def data_dir() -> Path:
    override = os.environ.get("YMRPC_DATA_DIR")
    if override:
        path = Path(override)
    else:
        root = os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
        path = Path(root) / DATA_FOLDER
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_dir() -> Path:
    path = data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def cache_dir() -> Path:
    path = data_dir() / "cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def art_cache_dir() -> Path:
    path = cache_dir() / "art"
    path.mkdir(parents=True, exist_ok=True)
    return path
