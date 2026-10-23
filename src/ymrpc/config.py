"""Хранение настроек в JSON с атомарной записью."""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from pathlib import Path
from threading import RLock

from .constants import data_dir
from .models import (
    ActivityKind,
    AppRule,
    ButtonsMode,
    CaptureMode,
    RuleAction,
    Settings,
)

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 2
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
ACCENT_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
LEGACY_UPDATE_REPOS = {"FozerG/YMRPC-Next"}


def config_path() -> Path:
    return data_dir() / "config.json"


class ConfigStore:
    def __init__(self, path: Path | None = None):
        self.path = path or config_path()
        self._lock = RLock()
        self._settings = self._read()

    @property
    def settings(self) -> Settings:
        with self._lock:
            return self._settings

    def save(self, settings: Settings, *, force: bool = False) -> Settings:
        settings = _sanitize(settings)
        with self._lock:
            if (
                not force
                and self.path.exists()
                and settings == getattr(self, "_settings", None)
            ):
                return settings
            payload = {
                "schema": SCHEMA_VERSION,
                "settings": _dump(settings),
            }
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    "w", encoding="utf-8", dir=self.path.parent, delete=False, suffix=".tmp"
                ) as stream:
                    json.dump(payload, stream, ensure_ascii=False, indent=2)
                    stream.flush()
                    os.fsync(stream.fileno())
                    temporary = Path(stream.name)
                temporary.replace(self.path)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
            self._settings = settings
            logger.info("Настройки сохранены: %s", self.path)
            return settings

    def reset(self) -> Settings:
        return self.save(Settings())

    def _read(self) -> Settings:
        if not self.path.exists():
            return Settings()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8-sig"))
            section = raw.get("settings", raw)
            if not isinstance(section, dict):
                raise ValueError("settings must be an object")
            try:
                schema = int(raw.get("schema", 1))
            except (TypeError, ValueError):
                schema = 1
            settings = _sanitize(_load(section, schema))
            legacy_repo = str(section.get("update_repo", "")).strip() in LEGACY_UPDATE_REPOS
            if schema < SCHEMA_VERSION or legacy_repo:
                try:
                    self.save(settings, force=True)
                except OSError as error:
                    logger.warning("Не удалось обновить формат настроек: %s", error)
            return settings
        except (OSError, ValueError, TypeError) as error:
            logger.warning("Не удалось прочитать настройки (%s), использую значения по умолчанию", error)
            return Settings()


def _load(raw: dict, schema: int = SCHEMA_VERSION) -> Settings:
    defaults = Settings()

    def enum(name, kind, default):
        value = str(raw.get(name, default.value)).lower()
        try:
            return kind(value)
        except ValueError:
            return default

    def boolean(name, default):
        value = raw.get(name, default)
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    def integer(name, default, minimum, maximum):
        try:
            value = int(raw.get(name, default))
        except (TypeError, ValueError):
            return default
        return max(minimum, min(maximum, value))

    def text(name, default, limit=200):
        value = raw.get(name, default)
        return str(value)[:limit] if value is not None else default

    def template(name, default):
        value = str(raw.get(name, default) or "").strip()
        return value[:128] if value else default

    rules: list[AppRule] = []
    raw_rules = raw.get("rules", [])
    if isinstance(raw_rules, list):
        for item in raw_rules[:40]:
            if not isinstance(item, dict):
                continue
            pattern = str(item.get("pattern", "")).strip()[:120]
            if not pattern:
                continue
            try:
                action = RuleAction(str(item.get("action", "ignore")).lower())
            except ValueError:
                action = RuleAction.IGNORE
            try:
                priority = max(-100, min(100, int(item.get("priority", 0))))
            except (TypeError, ValueError):
                priority = 0
            rules.append(AppRule(pattern=pattern, action=action, priority=priority))

    position = raw.get("mini_player_pos", defaults.mini_player_pos)
    if isinstance(position, (list, tuple)) and len(position) == 2:
        try:
            mini_pos = (int(position[0]), int(position[1]))
        except (TypeError, ValueError):
            mini_pos = defaults.mini_player_pos
    else:
        mini_pos = defaults.mini_player_pos

    language = str(raw.get("ui_language", defaults.ui_language)).lower()
    if language not in {"ru", "en"}:
        language = defaults.ui_language
    rpc_language = str(raw.get("rpc_language", defaults.rpc_language)).lower()
    if rpc_language not in {"ru", "en"}:
        rpc_language = defaults.rpc_language

    theme = str(raw.get("overlay_theme", defaults.overlay_theme)).lower()
    if theme not in {"dark", "light"}:
        theme = defaults.overlay_theme

    accent = str(raw.get("overlay_accent", defaults.overlay_accent))
    if not ACCENT_RE.match(accent):
        accent = defaults.overlay_accent

    repo = str(raw.get("update_repo", defaults.update_repo)).strip()
    if not REPO_RE.match(repo) or repo in LEGACY_UPDATE_REPOS:
        repo = defaults.update_repo

    hidden = str(raw.get("overlay_hide", defaults.overlay_hide))[:80]

    capture_mode = enum("capture_mode", CaptureMode, defaults.capture_mode)
    if schema < 2 and capture_mode == CaptureMode.YNISON:
        # Старый режим «только Ynison» оставлял пустой интерфейс, когда на
        # телефоне ничего не играло. Переводим его на авторежим с fallback.
        capture_mode = CaptureMode.AUTO

    return Settings(
        capture_mode=capture_mode,
        selected_session=text("selected_session", "", 300),
        activity_type=enum("activity_type", ActivityKind, defaults.activity_type),
        buttons=enum("buttons", ButtonsMode, defaults.buttons),
        details_template=template("details_template", defaults.details_template),
        state_template=template("state_template", defaults.state_template),
        large_text_template=template("large_text_template", defaults.large_text_template),
        pause_timeout=integer("pause_timeout", defaults.pause_timeout, -1, 86400),
        show_paused=boolean("show_paused", defaults.show_paused),
        presence_enabled=boolean("presence_enabled", defaults.presence_enabled),
        lyrics_in_presence=boolean("lyrics_in_presence", defaults.lyrics_in_presence),
        lyrics_offset=max(-30.0, min(30.0, _float(raw.get("lyrics_offset"), defaults.lyrics_offset))),
        ui_language=language,
        rpc_language=rpc_language,
        mini_player_visible=boolean("mini_player_visible", defaults.mini_player_visible),
        mini_player_autoshow=boolean("mini_player_autoshow", defaults.mini_player_autoshow),
        mini_player_pos=mini_pos,
        hotkeys_enabled=boolean("hotkeys_enabled", defaults.hotkeys_enabled),
        overlay_enabled=boolean("overlay_enabled", defaults.overlay_enabled),
        overlay_port=integer("overlay_port", defaults.overlay_port, 1024, 65535),
        overlay_theme=theme,
        overlay_accent=accent,
        overlay_hide=hidden,
        autostart=boolean("autostart", defaults.autostart),
        auto_update=boolean("auto_update", defaults.auto_update),
        update_repo=repo,
        stats_enabled=boolean("stats_enabled", defaults.stats_enabled),
        rules=tuple(rules),
    )


def _dump(settings: Settings) -> dict:
    return {
        "capture_mode": settings.capture_mode.value,
        "selected_session": settings.selected_session,
        "activity_type": settings.activity_type.value,
        "buttons": settings.buttons.value,
        "details_template": settings.details_template,
        "state_template": settings.state_template,
        "large_text_template": settings.large_text_template,
        "pause_timeout": settings.pause_timeout,
        "show_paused": settings.show_paused,
        "presence_enabled": settings.presence_enabled,
        "lyrics_in_presence": settings.lyrics_in_presence,
        "lyrics_offset": settings.lyrics_offset,
        "ui_language": settings.ui_language,
        "rpc_language": settings.rpc_language,
        "mini_player_visible": settings.mini_player_visible,
        "mini_player_autoshow": settings.mini_player_autoshow,
        "mini_player_pos": list(settings.mini_player_pos),
        "hotkeys_enabled": settings.hotkeys_enabled,
        "overlay_enabled": settings.overlay_enabled,
        "overlay_port": settings.overlay_port,
        "overlay_theme": settings.overlay_theme,
        "overlay_accent": settings.overlay_accent,
        "overlay_hide": settings.overlay_hide,
        "autostart": settings.autostart,
        "auto_update": settings.auto_update,
        "update_repo": settings.update_repo,
        "stats_enabled": settings.stats_enabled,
        "rules": [
            {"pattern": rule.pattern, "action": rule.action.value, "priority": rule.priority}
            for rule in settings.rules
        ],
    }


def _sanitize(settings: Settings) -> Settings:
    """Не даём UI сохранить заведомо невалидные значения."""
    defaults = Settings()
    details = settings.details_template.strip()[:128] or defaults.details_template
    state = settings.state_template.strip()[:128] or defaults.state_template
    large = settings.large_text_template.strip()[:128]
    repo = settings.update_repo.strip()
    if not REPO_RE.match(repo):
        repo = defaults.update_repo
    rules = tuple(
        AppRule(
            pattern=rule.pattern.strip()[:120],
            action=rule.action,
            priority=max(-100, min(100, int(rule.priority))),
        )
        for rule in settings.rules
        if rule.pattern.strip()
    )[:40]
    from dataclasses import replace

    return replace(
        settings,
        details_template=details,
        state_template=state,
        large_text_template=large,
        pause_timeout=max(-1, min(86400, int(settings.pause_timeout))),
        overlay_port=max(1024, min(65535, int(settings.overlay_port))),
        overlay_accent=settings.overlay_accent if ACCENT_RE.match(settings.overlay_accent) else "#ffcc00",
        lyrics_offset=max(-30.0, min(30.0, float(settings.lyrics_offset))),
        update_repo=repo,
        rules=rules,
    )


def _float(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
