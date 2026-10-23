"""Сопоставление треков из плеера с каталогами."""

from __future__ import annotations

from ymrpc.matching import artist_tokens, choose, normalize, score
from ymrpc.models import MediaSnapshot, Track


def _media(**overrides) -> MediaSnapshot:
    values = {
        "source_id": "Yandex",
        "source_name": "Яндекс Музыка",
        "title": "Пыяла",
        "artist": "АИГЕЛ",
        "album": "Пыяла",
        "duration": 214,
    }
    values.update(overrides)
    return MediaSnapshot(**values)


def test_normalize_strips_brackets_noise_and_punctuation() -> None:
    assert normalize("Song (Remastered 2011) [feat. Guest]") == "song"
    assert normalize("Ёлка — Всё, как всегда!") == "елка все как всегда"
    assert normalize("") == ""
    assert normalize("  A   B  ") == "a b"


def test_artist_tokens_splits_duets() -> None:
    assert artist_tokens("A, B & C feat. D") == {"a", "b", "c", "d"}
    assert artist_tokens("АИГЕЛ") == {"аигел"}
    assert artist_tokens("") == set()


def test_exact_track_scores_maximum() -> None:
    track = Track(title="Пыяла", artist="АИГЕЛ", album="Пыяла", duration=214)
    assert score(_media(), track) == 1.0


def test_completely_different_track_scores_zero() -> None:
    track = Track(title="Bohemian Rhapsody", artist="Queen", duration=355)
    assert score(_media(), track) == 0.0


def test_similar_title_with_other_artist_scores_lower() -> None:
    track = Track(title="Пыяла", artist="Другой исполнитель", duration=214)
    value = score(_media(), track)
    assert 0.5 < value < 1.0


def test_long_duration_mismatch_penalises() -> None:
    same = Track(title="Пыяла", artist="АИГЕЛ", album="Пыяла", duration=214)
    longer = Track(title="Пыяла", artist="АИГЕЛ", album="Пыяла", duration=400)
    assert score(_media(), longer) < score(_media(), same)


def test_choose_prefers_best_match() -> None:
    wrong = Track(title="Совсем другое", artist="Кто-то", duration=100)
    right = Track(title="Пыяла", artist="АИГЕЛ", album="Пыяла", duration=214)
    assert choose(_media(), [wrong, right]) is right


def test_choose_returns_none_when_nothing_passes_threshold() -> None:
    weak = Track(title="Пыяла (кавер)", artist="Неизвестный", duration=214)
    assert choose(_media(), [weak], minimum=0.9) is None
    assert choose(_media(), [], minimum=0.1) is None


def test_choose_breaks_ties_by_input_order() -> None:
    first = Track(title="Пыяла", artist="АИГЕЛ", duration=214)
    second = Track(title="Пыяла", artist="АИГЕЛ", duration=214)
    assert choose(_media(), [first, second]) is first
