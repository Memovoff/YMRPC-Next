"""Модели данных: настройки, треки, снимки медиа, состояние воспроизведения."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field, replace
from enum import StrEnum

from .constants import DEFAULT_UPDATE_REPO


class CaptureMode(StrEnum):
    AUTO = "auto"
    WINDOWS = "windows"
    YNISON = "ynison"


class ActivityKind(StrEnum):
    LISTENING = "listening"
    PLAYING = "playing"


class ButtonsMode(StrEnum):
    TRACK = "track"
    APP = "app"
    BOTH = "both"
    NONE = "none"


class PlaybackStatus(StrEnum):
    PLAYING = "playing"
    PAUSED = "paused"
    STOPPED = "stopped"
    UNKNOWN = "unknown"


class RuleAction(StrEnum):
    IGNORE = "ignore"
    PREFER = "prefer"


class Period(StrEnum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    ALL = "all"


@dataclass(frozen=True, slots=True)
class MediaSnapshot:
    """То, что отдаёт источник: SMTC или Ynison."""

    source_id: str
    source_name: str
    title: str
    artist: str
    album: str = ""
    position: float = 0.0
    duration: float = 0.0
    status: PlaybackStatus = PlaybackStatus.UNKNOWN
    device: str = ""
    external_id: str | None = None

    @property
    def identity(self) -> tuple[str, str, str]:
        return (self.source_id, self.title.casefold(), self.artist.casefold())

    @property
    def is_active(self) -> bool:
        return self.status in (PlaybackStatus.PLAYING, PlaybackStatus.PAUSED)

    @property
    def is_playing(self) -> bool:
        return self.status == PlaybackStatus.PLAYING


@dataclass(frozen=True, slots=True)
class Track:
    title: str
    artist: str
    album: str = ""
    year: int | None = None
    duration: float = 0.0
    cover_url: str | None = None
    track_url: str | None = None
    app_url: str | None = None
    yandex_id: str | None = None
    source: str = ""

    @property
    def key(self) -> str:
        if self.yandex_id:
            return f"yandex:{self.yandex_id}"
        return f"{_normalize(self.artist)}|{_normalize(self.title)}"

    @property
    def display_artist(self) -> str:
        return self.artist or "Неизвестный исполнитель"


@dataclass(frozen=True, slots=True)
class AppRule:
    """Правило для источника Windows: игнорировать или поднять приоритет."""

    pattern: str
    action: RuleAction = RuleAction.IGNORE
    priority: int = 0

    def matches(self, source_id: str, source_name: str = "") -> bool:
        needle = self.pattern.strip().casefold()
        if not needle:
            return False
        return needle in source_id.casefold() or needle in source_name.casefold()


@dataclass(frozen=True, slots=True)
class Settings:
    capture_mode: CaptureMode = CaptureMode.AUTO
    selected_session: str = ""

    activity_type: ActivityKind = ActivityKind.LISTENING
    buttons: ButtonsMode = ButtonsMode.BOTH
    details_template: str = "{title}"
    state_template: str = "{artist}"
    large_text_template: str = "{album}"
    pause_timeout: int = 300
    show_paused: bool = True
    presence_enabled: bool = True
    lyrics_in_presence: bool = False
    lyrics_offset: float = 0.0

    ui_language: str = "ru"
    rpc_language: str = "ru"

    mini_player_visible: bool = False
    mini_player_autoshow: bool = False
    mini_player_pos: tuple[int, int] = (40, 40)
    hotkeys_enabled: bool = True

    overlay_enabled: bool = True
    overlay_port: int = 8765
    overlay_theme: str = "dark"
    overlay_accent: str = "#ffcc00"
    overlay_hide: str = ""

    autostart: bool = False
    auto_update: bool = True
    update_repo: str = DEFAULT_UPDATE_REPO
    stats_enabled: bool = True
    rules: tuple[AppRule, ...] = ()

    def with_rule(self, rule: AppRule) -> Settings:
        rules = tuple(existing for existing in self.rules if existing.pattern != rule.pattern)
        return replace(self, rules=rules + (rule,))

    def without_rule(self, pattern: str) -> Settings:
        return replace(self, rules=tuple(rule for rule in self.rules if rule.pattern != pattern))


@dataclass(frozen=True, slots=True)
class LyricsLine:
    time: float
    text: str


@dataclass(frozen=True, slots=True)
class Lyrics:
    track_key: str
    lines: tuple[LyricsLine, ...] = ()
    plain: str = ""
    source: str = ""
    synced: bool = False

    @property
    def available(self) -> bool:
        return bool(self.lines or self.plain)

    def active_index(self, position: float) -> int:
        if not self.lines:
            return -1
        low, high = 0, len(self.lines) - 1
        result = -1
        while low <= high:
            middle = (low + high) // 2
            if self.lines[middle].time <= position:
                result = middle
                low = middle + 1
            else:
                high = middle - 1
        return result

    def active_line(self, position: float) -> str:
        index = self.active_index(position)
        return self.lines[index].text if index >= 0 else ""


@dataclass(frozen=True, slots=True)
class PlaybackView:
    """Готовое состояние для UI, оверлея и Discord."""

    track: Track | None = None
    status: PlaybackStatus = PlaybackStatus.UNKNOWN
    position: float = 0.0
    duration: float = 0.0
    source_id: str = ""
    source_name: str = ""
    device: str = ""
    art_path: str | None = None
    source_state: str = "ok"
    account: str | None = None
    presence_visible: bool = False
    lyrics_available: bool = False
    stamp: float = field(default_factory=time.monotonic)

    @property
    def has_track(self) -> bool:
        return self.track is not None

    @property
    def is_playing(self) -> bool:
        return self.status == PlaybackStatus.PLAYING

    @property
    def is_paused(self) -> bool:
        return self.status == PlaybackStatus.PAUSED

    def position_at(self, now: float | None = None) -> float:
        position = self.position
        if self.is_playing:
            moment = time.monotonic() if now is None else now
            position += max(0.0, moment - self.stamp)
        if self.duration > 0:
            position = min(position, self.duration)
        return max(0.0, position)

    def identity(self) -> tuple[str, str] | None:
        if self.track is None:
            return None
        return (self.track.key, self.source_id)


@dataclass(frozen=True, slots=True)
class SessionInfo:
    source_id: str
    source_name: str
    status: PlaybackStatus
    title: str = ""
    artist: str = ""
    current: bool = False


@dataclass(frozen=True, slots=True)
class UpdateInfo:
    version: str
    tag: str
    page_url: str
    asset_url: str | None = None
    asset_name: str = ""
    notes: str = ""
    sha256: str = ""


@dataclass(frozen=True, slots=True)
class UpdateProgress:
    percent: int
    downloaded: int
    total: int


def _normalize(value: str) -> str:
    value = value.casefold().replace("ё", "е")
    value = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", value)
    return re.sub(r"[\W_]+", " ", value, flags=re.UNICODE).strip()
