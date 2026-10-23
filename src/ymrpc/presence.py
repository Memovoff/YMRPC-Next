"""Шаблоны и сборка payload для Discord Rich Presence."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

from .constants import ASSETS_URL, DISCORD_CLIENT_ID_EN, DISCORD_CLIENT_ID_RU
from .i18n import t  # noqa: F401  (публичный реэкспорт для UI)
from .models import ActivityKind, ButtonsMode, Lyrics, PlaybackStatus, PlaybackView, Settings, Track
from .urls import is_public_https_url

PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
DISCORD_TEXT_LIMIT = 128
BUTTON_LABEL_LIMIT = 32

PLACEHOLDERS = (
    "title",
    "artist",
    "album",
    "year",
    "source",
    "device",
    "progress",
    "duration",
    "remaining",
    "progress_pct",
    "url",
    "lyric",
)

DEFAULT_DETAILS = "{title}"
DEFAULT_STATE = "{artist}"
DEFAULT_LARGE_TEXT = "{album}"


@dataclass(frozen=True, slots=True)
class PresencePreview:
    details: str
    state: str
    large_text: str
    small_text: str


def client_id(settings: Settings) -> str:
    return DISCORD_CLIENT_ID_RU if settings.rpc_language == "ru" else DISCORD_CLIENT_ID_EN


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02}:{seconds:02}"
    return f"{minutes}:{seconds:02}"


def build_context(
    view: PlaybackView,
    track: Track,
    *,
    position: float | None = None,
    lyric: str = "",
) -> dict[str, str]:
    duration = view.duration or track.duration or 0
    current = view.position if position is None else position
    current = max(0.0, min(current, duration) if duration else current)
    remaining = max(0.0, duration - current) if duration else 0.0
    percent = int(round(current / duration * 100)) if duration else 0
    return {
        "title": track.title,
        "artist": track.artist,
        "album": track.album,
        "year": str(track.year) if track.year else "",
        "source": view.source_name or track.source,
        "device": view.device,
        "progress": format_duration(current),
        "duration": format_duration(duration) if duration else "",
        "remaining": format_duration(remaining) if duration else "",
        "progress_pct": str(percent),
        "url": track.track_url or "",
        "lyric": lyric,
        "track": track.title,
        "app": view.source_name or track.source,
    }


def render(template: str, context: dict[str, str]) -> str:
    if not template:
        return ""

    def _replace(match: re.Match) -> str:
        return context.get(match.group(1), "")

    return PLACEHOLDER_RE.sub(_replace, template).strip()


def preview(settings: Settings) -> PresencePreview:
    view = PlaybackView(
        track=Track(
            title="Пыяла",
            artist="АИГЕЛ",
            album="Пыяла",
            year=2023,
            duration=214,
            track_url="https://music.yandex.ru/",
        ),
        status=PlaybackStatus.PLAYING,
        position=72,
        duration=214,
        source_name="Яндекс Музыка",
        source_state="ok",
    )
    context = build_context(view, view.track, lyric="Я иду по краю")
    details = render(settings.details_template, context) or view.track.title
    state = render(settings.state_template, context) or view.track.artist
    large = render(settings.large_text_template, context)
    return PresencePreview(
        details=discord_text(details),
        state=discord_text(state),
        large_text=discord_text(large),
        small_text=_small_text(True),
    )


def _small_text(playing: bool) -> str:
    if _is_russian():
        return "Играет" if playing else "Пауза"
    return "Playing" if playing else "Paused"


def discord_text(value: str, fallback: str = "") -> str:
    value = (value or fallback).strip()[:DISCORD_TEXT_LIMIT]
    if not value:
        return ""
    return value + "\u200b" if len(value) == 1 else value


def build_activity(
    view: PlaybackView,
    settings: Settings,
    lyrics: Lyrics | None,
    *,
    now_wall: float | None = None,
    now_mono: float | None = None,
) -> dict | None:
    track = view.track
    if track is None or not settings.presence_enabled:
        return None
    if view.status not in (PlaybackStatus.PLAYING, PlaybackStatus.PAUSED):
        return None
    if view.status == PlaybackStatus.PAUSED and not settings.show_paused:
        return None

    now_wall = time.time() if now_wall is None else now_wall
    position = view.position_at(now_mono)
    lyric = ""
    if settings.lyrics_in_presence and lyrics is not None and lyrics.synced:
        lyric = lyrics.active_line(position + settings.lyrics_offset)
    context = build_context(view, track, position=position, lyric=lyric)

    details = render(settings.details_template, context) or track.title or track.artist
    state = render(settings.state_template, context) or track.artist or track.title
    large_text = render(settings.large_text_template, context)
    if not details and not state:
        return None

    playing = view.status == PlaybackStatus.PLAYING
    payload: dict = {
        "type": 2 if settings.activity_type == ActivityKind.LISTENING else 0,
        "details": discord_text(details),
        "state": discord_text(state),
        "assets": {
            "small_image": f"{ASSETS_URL}/{'Playing' if playing else 'Paused'}.png",
            "small_text": discord_text(_small_text(playing)),
        },
        "instance": False,
    }
    cover = _button_url(track.cover_url)
    if cover:
        payload["assets"]["large_image"] = cover
        if large_text:
            payload["assets"]["large_text"] = discord_text(large_text)

    if playing:
        # Discord сам двигает прогресс по timestamps; обновляем только при смене трека/паузы.
        start = int(now_wall - position)
        payload["timestamps"] = {"start": start}
        if view.duration and view.duration > position:
            payload["timestamps"]["end"] = int(now_wall - position + view.duration)

    buttons = _buttons(track, settings)
    if buttons:
        payload["buttons"] = buttons
    return payload


def _buttons(track: Track, settings: Settings) -> list[dict[str, str]]:
    if settings.buttons == ButtonsMode.NONE:
        return []
    url = _button_url(track.track_url)
    if not url:
        query = " ".join(part for part in (track.artist, track.title) if part)
        if query:
            from urllib.parse import quote

            url = f"https://music.yandex.ru/search?text={quote(query)}"
    app_url = _button_url(track.app_url, yandex_app=True)
    buttons: list[dict[str, str]] = []
    if settings.buttons in (ButtonsMode.TRACK, ButtonsMode.BOTH) and url:
        buttons.append({"label": _label("presence.browser"), "url": url[:512]})
    if settings.buttons in (ButtonsMode.APP, ButtonsMode.BOTH) and app_url:
        buttons.append({"label": _label("presence.app"), "url": app_url[:512]})
    return buttons[:2]


def _button_url(value: str | None, *, yandex_app: bool = False) -> str | None:
    """Discord принимает только публичные HTTPS-ссылки."""
    if not value:
        return None
    value = value.strip()
    if yandex_app and value.startswith("yandexmusic://"):
        value = "https://music.yandex.ru/" + value[len("yandexmusic://") :].lstrip("/")
    return value if is_public_https_url(value) else None


def _label(key: str) -> str:
    return t(key)


def _is_russian() -> bool:
    from . import i18n

    return i18n.current_language() == "ru"


def validate_template(value: str) -> str | None:
    """Возвращает текст ошибки или None."""
    if not value.strip():
        return t("discord.invalid_template")
    unknown = {
        name
        for name in PLACEHOLDER_RE.findall(value)
        if name not in PLACEHOLDERS and name not in {"track", "app"}
    }
    if unknown:
        return ", ".join(sorted(unknown))
    return None
