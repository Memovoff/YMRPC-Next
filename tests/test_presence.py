"""Шаблоны статуса, форматирование и сборка Discord Activity."""

from __future__ import annotations

from dataclasses import replace

import pytest

from ymrpc import i18n
from ymrpc.models import (
    ActivityKind,
    ButtonsMode,
    Lyrics,
    LyricsLine,
    PlaybackStatus,
    PlaybackView,
    Settings,
    Track,
)
from ymrpc.presence import (
    PLACEHOLDERS,
    build_activity,
    build_context,
    client_id,
    discord_text,
    format_duration,
    preview,
    render,
    validate_template,
)


@pytest.fixture(autouse=True)
def _russian() -> None:
    i18n.set_language("ru")


def _track(**overrides) -> Track:
    values = {
        "title": "Пыяла",
        "artist": "АИГЕЛ",
        "album": "Пыяла",
        "year": 2023,
        "duration": 214,
        "cover_url": "https://example.com/cover.jpg",
        "track_url": "https://music.yandex.ru/track/1",
        "app_url": "yandexmusic://track/1",
    }
    values.update(overrides)
    return Track(**values)


def _view(**overrides) -> PlaybackView:
    values = {
        "track": _track(),
        "status": PlaybackStatus.PLAYING,
        "position": 72,
        "duration": 214,
        "source_id": "Yandex",
        "source_name": "Яндекс Музыка",
        "device": "Настольный ПК",
    }
    values.update(overrides)
    return PlaybackView(**values)


def test_format_duration() -> None:
    assert format_duration(0) == "0:00"
    assert format_duration(59) == "0:59"
    assert format_duration(60) == "1:00"
    assert format_duration(3599) == "59:59"
    assert format_duration(3600) == "1:00:00"
    assert format_duration(3661) == "1:01:01"
    assert format_duration(-10) == "0:00"


def test_render_replaces_known_and_drops_unknown_placeholders() -> None:
    context = {"title": "Пыяла", "artist": "АИГЕЛ", "progress": "1:12"}
    assert render("{artist} — {title} ({progress})", context) == "АИГЕЛ — Пыяла (1:12)"
    assert render("{title} {unknown}", context) == "Пыяла"
    assert render("", context) == ""
    assert render("  {title}  ", context) == "Пыяла"


def test_build_context_uses_track_duration_as_fallback() -> None:
    view = _view(duration=0)
    context = build_context(view, _track())
    assert context["title"] == "Пыяла"
    assert context["artist"] == "АИГЕЛ"
    assert context["album"] == "Пыяла"
    assert context["year"] == "2023"
    assert context["progress"] == "1:12"
    assert context["duration"] == "3:34"
    assert context["remaining"] == "2:22"
    assert context["progress_pct"] == "34"
    assert context["url"] == "https://music.yandex.ru/track/1"
    assert context["app"] == "Яндекс Музыка"


def test_build_context_without_duration() -> None:
    view = _view(duration=0)
    track = _track(duration=0)
    context = build_context(view, track)
    assert context["duration"] == ""
    assert context["remaining"] == ""
    assert context["progress_pct"] == "0"


def test_build_context_clamps_position() -> None:
    view = _view(position=999)
    context = build_context(view, _track(), position=500)
    assert context["progress"] == "3:34"
    assert context["remaining"] == "0:00"
    assert context["progress_pct"] == "100"


def test_validate_template() -> None:
    assert validate_template("   ") is not None
    assert validate_template("{title} — {artist}") is None
    assert validate_template("{track} / {app} / {lyric}") is None
    error = validate_template("{title} {bogus}")
    assert error is not None and "bogus" in error
    error = validate_template("{zzz} {aaa}")
    assert error == "aaa, zzz"


def test_all_documented_placeholders_are_valid() -> None:
    for name in PLACEHOLDERS:
        assert validate_template("{" + name + "}") is None


def test_discord_text_limits_and_single_character() -> None:
    assert discord_text("  hello  ") == "hello"
    assert discord_text("") == ""
    assert discord_text("x") == "x\u200b"
    assert len(discord_text("y" * 500)) == 128


def test_client_id_depends_on_rpc_language() -> None:
    assert client_id(Settings(rpc_language="ru")) != client_id(Settings(rpc_language="en"))


def test_preview_uses_default_templates() -> None:
    result = preview(Settings())
    assert result.details == "Пыяла"
    assert result.state == "АИГЕЛ"
    assert result.large_text == "Пыяла"
    assert result.small_text == "Играет"


def test_build_activity_playing_payload() -> None:
    payload = build_activity(_view(), Settings(), None, now_wall=1_000_000, now_mono=0.0)
    assert payload is not None
    assert payload["type"] == 2
    assert payload["details"] == "Пыяла"
    assert payload["state"] == "АИГЕЛ"
    assert payload["assets"]["large_image"] == "https://example.com/cover.jpg"
    assert payload["assets"]["large_text"] == "Пыяла"
    assert payload["assets"]["small_image"].endswith("/Playing.png")
    assert payload["assets"]["small_text"] == "Играет"
    assert payload["timestamps"] == {"start": 999_928, "end": 1_000_142}
    assert payload["buttons"][0]["label"] == "Открыть в браузере"
    assert payload["buttons"][1]["label"] == "Открыть в приложении"
    assert payload["instance"] is False


def test_build_activity_playing_type() -> None:
    settings = replace(Settings(), activity_type=ActivityKind.PLAYING)
    payload = build_activity(_view(), settings, None, now_wall=1_000_000, now_mono=0.0)
    assert payload is not None
    assert payload["type"] == 0


def test_build_activity_paused() -> None:
    payload = build_activity(
        _view(status=PlaybackStatus.PAUSED),
        Settings(),
        None,
        now_wall=1_000_000,
        now_mono=0.0,
    )
    assert payload is not None
    assert "timestamps" not in payload
    assert payload["assets"]["small_image"].endswith("/Paused.png")
    assert payload["assets"]["small_text"] == "Пауза"


def test_build_activity_hides_paused_when_disabled() -> None:
    settings = replace(Settings(), show_paused=False)
    assert build_activity(_view(status=PlaybackStatus.PAUSED), settings, None) is None


def test_build_activity_requires_enabled_presence_and_track() -> None:
    assert build_activity(_view(), replace(Settings(), presence_enabled=False), None) is None
    assert build_activity(_view(track=None), Settings(), None) is None
    assert build_activity(_view(status=PlaybackStatus.STOPPED), Settings(), None) is None
    assert build_activity(_view(status=PlaybackStatus.UNKNOWN), Settings(), None) is None


def test_build_activity_without_duration_has_no_end_timestamp() -> None:
    view = _view(duration=0, track=_track(duration=0))
    payload = build_activity(view, Settings(), None, now_wall=1_000_000, now_mono=0.0)
    assert payload is not None
    assert payload["timestamps"] == {"start": 999_928}


def test_build_activity_without_cover_has_no_large_image() -> None:
    view = _view(track=_track(cover_url=None))
    payload = build_activity(view, Settings(), None, now_wall=1_000_000, now_mono=0.0)
    assert payload is not None
    assert "large_image" not in payload["assets"]
    assert "large_text" not in payload["assets"]


def test_build_activity_uses_lyrics_when_enabled() -> None:
    lyrics = Lyrics(
        track_key="x",
        lines=(LyricsLine(0, "первая"), LyricsLine(70, "вторая")),
        source="LRCLIB",
        synced=True,
    )
    settings = replace(Settings(), lyrics_in_presence=True, lyrics_offset=5, state_template="{lyric}")
    payload = build_activity(_view(), settings, lyrics, now_wall=1_000_000, now_mono=0.0)
    assert payload is not None
    assert payload["state"] == "вторая"


def test_build_activity_ignores_plain_lyrics() -> None:
    lyrics = Lyrics(track_key="x", plain="просто текст", synced=False)
    settings = replace(Settings(), lyrics_in_presence=True, state_template="{lyric}")
    payload = build_activity(_view(), settings, lyrics, now_wall=1_000_000, now_mono=0.0)
    assert payload is not None
    assert payload["state"] == "АИГЕЛ"


def test_build_activity_falls_back_to_track_fields() -> None:
    settings = replace(Settings(), details_template="", state_template="")
    payload = build_activity(_view(), settings, None, now_wall=1_000_000, now_mono=0.0)
    assert payload is not None
    assert payload["details"] == "Пыяла"
    assert payload["state"] == "АИГЕЛ"


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        (ButtonsMode.NONE, 0),
        (ButtonsMode.TRACK, 1),
        (ButtonsMode.APP, 1),
        (ButtonsMode.BOTH, 2),
    ],
)
def test_buttons_modes(mode: ButtonsMode, expected: int) -> None:
    payload = build_activity(_view(), replace(Settings(), buttons=mode), None, now_wall=1, now_mono=0.0)
    assert payload is not None
    assert len(payload.get("buttons", [])) == expected


def test_track_button_is_generated_from_search_when_url_missing() -> None:
    track = _track(track_url=None, app_url=None, artist="Artist", title="Song")
    settings = replace(Settings(), buttons=ButtonsMode.TRACK)
    payload = build_activity(_view(track=track), settings, None, now_wall=1, now_mono=0.0)
    assert payload is not None
    assert payload["buttons"] == [
        {
            "label": "Открыть в браузере",
            "url": "https://music.yandex.ru/search?text=Artist%20Song",
        }
    ]


def test_app_button_requires_app_url() -> None:
    track = _track(app_url=None)
    settings = replace(Settings(), buttons=ButtonsMode.APP)
    payload = build_activity(_view(track=track), settings, None, now_wall=1, now_mono=0.0)
    assert payload is not None
    assert "buttons" not in payload


def test_private_cover_is_not_sent_to_discord() -> None:
    track = _track(cover_url="http://127.0.0.1/cover.jpg")
    payload = build_activity(_view(track=track), Settings(), None, now_wall=1, now_mono=0.0)
    assert payload is not None
    assert "large_image" not in payload["assets"]
    assert "large_text" not in payload["assets"]


def test_unsafe_buttons_are_replaced_with_safe_search() -> None:
    track = _track(track_url="javascript:alert(1)", app_url="file:///C:/Windows/System32/calc.exe")
    settings = replace(Settings(), buttons=ButtonsMode.BOTH)
    payload = build_activity(_view(track=track), settings, None, now_wall=1, now_mono=0.0)
    assert payload is not None
    assert len(payload["buttons"]) == 1
    assert payload["buttons"][0]["url"].startswith("https://music.yandex.ru/search?text=")


def test_yandex_app_url_is_converted_to_https() -> None:
    track = _track(app_url="yandexmusic://track/1")
    settings = replace(Settings(), buttons=ButtonsMode.APP)
    payload = build_activity(_view(track=track), settings, None, now_wall=1, now_mono=0.0)
    assert payload is not None
    assert payload["buttons"] == [
        {"label": "Открыть в приложении", "url": "https://music.yandex.ru/track/1"}
    ]
