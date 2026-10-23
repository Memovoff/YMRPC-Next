"""Разбор LRC и работа с синхронизированными текстами."""

from __future__ import annotations

from ymrpc.models import Lyrics, LyricsLine
from ymrpc.services.lyrics import parse_lrc, split_plain


def test_parse_lrc_basic_and_offset() -> None:
    text = "\n".join(
        [
            "[ar:АИГЕЛ]",
            "[ti:Пыяла]",
            "[offset:+250]",
            "[00:01.50]Первая строка",
            "[00:10]Вторая строка",
            "[00:20.123][00:30.000]Припев",
        ]
    )
    lines = parse_lrc(text)
    assert [line.text for line in lines] == [
        "Первая строка",
        "Вторая строка",
        "Припев",
        "Припев",
    ]
    assert [line.time for line in lines] == [1.75, 10.25, 20.373, 30.25]


def test_parse_lrc_hours_format() -> None:
    lines = parse_lrc("[01:02:03.500]Долгая песня")
    assert len(lines) == 1
    assert lines[0].time == 3723.5
    assert lines[0].text == "Долгая песня"


def test_parse_lrc_negative_offset_is_clamped() -> None:
    lines = parse_lrc("[offset:-500]\n[00:00.10]Тихо")
    assert len(lines) == 1
    assert lines[0].time == 0.0


def test_parse_lrc_removes_word_timestamps_and_empty_lines() -> None:
    text = "[00:05.00]<00:05.00>Слово <00:05.50>ещё\n\n[00:06.00]   \n[00:07.00]Конец"
    lines = parse_lrc(text)
    assert [(line.time, line.text) for line in lines] == [
        (5.0, "Слово ещё"),
        (7.0, "Конец"),
    ]


def test_parse_lrc_sorts_and_deduplicates() -> None:
    text = "[00:30.00]Позже\n[00:10.00]Раньше\n[00:10.000]Раньше"
    lines = parse_lrc(text)
    assert [(line.time, line.text) for line in lines] == [
        (10.0, "Раньше"),
        (30.0, "Позже"),
    ]


def test_parse_lrc_without_timestamps_returns_empty() -> None:
    assert parse_lrc("просто текст\nбез времени") == []
    assert parse_lrc("") == []


def test_split_plain_keeps_order_and_drops_blank_lines() -> None:
    assert split_plain("первая\r\n\r\n вторая \n\nтретья\n") == ["первая", "вторая", "третья"]
    assert split_plain("") == []


def test_lyrics_active_index_and_line() -> None:
    lyrics = Lyrics(
        track_key="x",
        lines=(LyricsLine(0, "a"), LyricsLine(10, "b"), LyricsLine(20, "c")),
        synced=True,
    )
    assert lyrics.available is True
    assert lyrics.active_index(0) == 0
    assert lyrics.active_index(9.99) == 0
    assert lyrics.active_index(10) == 1
    assert lyrics.active_index(25) == 2
    assert lyrics.active_line(15) == "b"


def test_lyrics_active_index_edges() -> None:
    lyrics = Lyrics(track_key="x", lines=(LyricsLine(5, "a"),), synced=True)
    assert lyrics.active_index(0) == -1
    assert lyrics.active_line(0) == ""
    assert Lyrics(track_key="x", plain="text").available is True
    assert Lyrics(track_key="x").available is False
