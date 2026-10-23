"""SMTC: экстраполяция позиции по last_updated_time."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from ymrpc.models import PlaybackStatus
from ymrpc.sources.smtc import _timeline_position

NOW = datetime(2026, 10, 23, 17, 15, tzinfo=UTC)


@pytest.mark.parametrize(
    ("position", "elapsed", "expected"),
    [
        (0.33, 0.0, 0.33),
        (0.33, 12.5, 12.83),
        (259.09, 3.0, 262.09),
    ],
)
def test_playing_position_is_extrapolated(position: float, elapsed: float, expected: float) -> None:
    updated = NOW - timedelta(seconds=elapsed)
    result = _timeline_position(
        position,
        300.0,
        updated,
        PlaybackStatus.PLAYING,
        now=NOW,
    )
    assert result == pytest.approx(expected)


def test_paused_position_is_not_extrapolated() -> None:
    updated = NOW - timedelta(seconds=60)
    result = _timeline_position(
        120.0,
        300.0,
        updated,
        PlaybackStatus.PAUSED,
        now=NOW,
    )
    assert result == pytest.approx(120.0)


def test_position_is_clamped_to_duration() -> None:
    updated = NOW - timedelta(seconds=400)
    result = _timeline_position(
        100.0,
        300.0,
        updated,
        PlaybackStatus.PLAYING,
        now=NOW,
    )
    assert result == pytest.approx(300.0)


def test_naive_timestamp_is_treated_as_utc() -> None:
    updated = (NOW - timedelta(seconds=5)).replace(tzinfo=None)
    result = _timeline_position(
        10.0,
        300.0,
        updated,
        PlaybackStatus.PLAYING,
        now=NOW,
    )
    assert result == pytest.approx(15.0)


@pytest.mark.parametrize(
    "updated",
    [
        None,
        NOW + timedelta(seconds=30),
        NOW - timedelta(days=2),
        datetime(1601, 1, 1, tzinfo=UTC),
    ],
)
def test_unreliable_timestamp_keeps_raw_position(updated) -> None:
    result = _timeline_position(
        42.0,
        300.0,
        updated,
        PlaybackStatus.PLAYING,
        now=NOW,
    )
    assert result == pytest.approx(42.0)


def test_negative_position_is_zero() -> None:
    assert _timeline_position(-5.0, 300.0, None, PlaybackStatus.PLAYING, now=NOW) == 0.0


def test_unknown_status_is_not_extrapolated() -> None:
    updated = NOW - timedelta(seconds=60)
    assert (
        _timeline_position(7.0, 300.0, updated, PlaybackStatus.UNKNOWN, now=NOW)
        == 7.0
    )
