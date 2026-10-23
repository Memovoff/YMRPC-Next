"""Правила выбора активного источника по приложениям."""

from __future__ import annotations

from ymrpc.models import AppRule, MediaSnapshot, PlaybackStatus, RuleAction, SessionInfo
from ymrpc.sources.rules import app_ignored, app_priority, choose, choose_auto


def _session(
    source_id: str,
    status: PlaybackStatus = PlaybackStatus.PLAYING,
    name: str = "",
) -> SessionInfo:
    return SessionInfo(source_id=source_id, source_name=name or source_id, status=status)


def test_app_ignored_is_case_insensitive_and_matches_name() -> None:
    rules = (AppRule("chrome", RuleAction.IGNORE),)
    assert app_ignored("Google.Chrome", "Google Chrome", rules) is True
    assert app_ignored("spotify", "Spotify", rules) is False
    assert app_ignored("chrome", "", ()) is False
    assert app_ignored("chrome", "", (AppRule("Chrome", RuleAction.PREFER),)) is False


def test_app_priority_uses_maximum_prefer_value() -> None:
    rules = (
        AppRule("music", RuleAction.PREFER, 10),
        AppRule("yandex", RuleAction.PREFER, 50),
        AppRule("other", RuleAction.PREFER, 99),
    )
    assert app_priority("Yandex.Music", "", rules) == 50
    assert app_priority("unknown", "", rules) == 0


def test_choose_prefers_playing_over_paused() -> None:
    sessions = [
        _session("paused", PlaybackStatus.PAUSED),
        _session("playing", PlaybackStatus.PLAYING),
    ]
    picked = choose(sessions, ())
    assert picked is not None
    assert picked.source_id == "playing"


def test_choose_respects_ignore_rules() -> None:
    sessions = [
        _session("chrome", name="Google Chrome"),
        _session("yandex", name="Яндекс Музыка"),
    ]
    picked = choose(sessions, (AppRule("chrome", RuleAction.IGNORE),))
    assert picked is not None
    assert picked.source_id == "yandex"


def test_choose_uses_priority_among_playing_apps() -> None:
    sessions = [_session("a"), _session("b")]
    picked = choose(sessions, (AppRule("b", RuleAction.PREFER, 10),))
    assert picked is not None
    assert picked.source_id == "b"


def test_selected_session_has_absolute_priority() -> None:
    sessions = [
        _session("playing", PlaybackStatus.PLAYING),
        _session("selected", PlaybackStatus.PAUSED),
    ]
    picked = choose(sessions, (AppRule("selected", RuleAction.IGNORE),), selected="selected")
    assert picked is not None
    assert picked.source_id == "selected"


def test_choose_returns_none_without_active_or_all_ignored() -> None:
    assert choose([_session("x", PlaybackStatus.STOPPED)], ()) is None
    assert choose([], ()) is None
    assert choose([_session("x")], (AppRule("x", RuleAction.IGNORE),)) is None


def _media(source_id: str, status: PlaybackStatus) -> MediaSnapshot:
    return MediaSnapshot(
        source_id=source_id,
        source_name=source_id,
        title=source_id,
        artist="",
        album="",
        position=0.0,
        duration=0.0,
        status=status,
    )


def test_choose_auto_prefers_local_playing() -> None:
    windows = _media("windows", PlaybackStatus.PLAYING)
    ynison = _media("ynison", PlaybackStatus.PLAYING)
    assert choose_auto(windows, ynison) is windows


def test_choose_auto_uses_remote_playing_when_local_is_paused() -> None:
    windows = _media("windows", PlaybackStatus.PAUSED)
    ynison = _media("ynison", PlaybackStatus.PLAYING)
    assert choose_auto(windows, ynison) is ynison


def test_choose_auto_falls_back_to_whatever_exists() -> None:
    paused = _media("windows", PlaybackStatus.PAUSED)
    assert choose_auto(paused, None) is paused
    assert choose_auto(None, paused) is paused
    assert choose_auto(None, None) is None
