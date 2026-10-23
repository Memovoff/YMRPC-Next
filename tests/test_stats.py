"""Статистика прослушиваний на SQLite."""

from __future__ import annotations

import csv
import sqlite3
import time
from dataclasses import replace
from datetime import datetime

from ymrpc.models import Period, PlaybackStatus, PlaybackView, Track
from ymrpc.services import stats
from ymrpc.services.stats import (
    SCHEMA,
    StatsStore,
    daily_activity,
    empty_summary,
    export_csv,
    period_start,
    summary,
)


class FakeClock:
    def __init__(self, monotonic: float = 1000.0, wall: float = 1_700_000_000.0):
        self.value = monotonic
        self.wall = wall

    def monotonic(self) -> float:
        return self.value

    def time(self) -> float:
        return self.wall

    def advance(self, seconds: float) -> None:
        self.value += seconds
        self.wall += seconds


def _view(position: float = 0.0, status: PlaybackStatus = PlaybackStatus.PLAYING) -> PlaybackView:
    return PlaybackView(
        track=Track(title="Пыяла", artist="АИГЕЛ", album="Пыяла", duration=200),
        status=status,
        position=position,
        duration=200,
        source_name="Яндекс Музыка",
    )


def _insert(
    path,
    *,
    track_key: str,
    title: str,
    artist: str,
    listened_ms: int,
    started_at: int,
    duration_ms: int = 200_000,
    completed: int = 0,
    album: str = "",
    source: str = "test",
) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(SCHEMA)
        connection.execute(
            "INSERT INTO plays "
            "(track_key, title, artist, album, source, yandex_id, started_at, listened_ms, duration_ms, completed) "
            "VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)",
            (track_key, title, artist, album, source, started_at, listened_ms, duration_ms, completed),
        )
        connection.commit()
    finally:
        connection.close()


def _rows(path) -> list[sqlite3.Row]:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        return connection.execute("SELECT * FROM plays ORDER BY id").fetchall()
    finally:
        connection.close()


def test_observe_records_play(tmp_path, monkeypatch) -> None:
    clock = FakeClock()
    monkeypatch.setattr(stats, "time", clock)
    path = tmp_path / "stats.db"
    store = StatsStore(path)
    view = _view()
    for index in range(8):
        store.observe(replace(view, position=index * 5))
        clock.advance(5)
    store.close()

    rows = _rows(path)
    assert len(rows) == 1
    row = rows[0]
    assert row["title"] == "Пыяла"
    assert row["artist"] == "АИГЕЛ"
    assert row["source"] == "Яндекс Музыка"
    assert row["duration_ms"] == 200_000
    assert row["listened_ms"] == 35_000
    assert row["completed"] == 0

    result = summary(path, Period.ALL)
    assert result["plays"] == 1
    assert result["tracks"] == 1
    assert result["artists"] == 1
    assert result["listened_ms"] == 35_000


def test_observe_switches_tracks(tmp_path, monkeypatch) -> None:
    clock = FakeClock()
    monkeypatch.setattr(stats, "time", clock)
    path = tmp_path / "stats.db"
    store = StatsStore(path)
    view = _view()
    store.observe(view)
    for index in range(1, 8):
        clock.advance(5)
        store.observe(replace(view, position=index * 5))

    other = replace(_view(), track=Track(title="Другая", artist="Кто-то", duration=100))
    store.observe(other)
    for index in range(1, 8):
        clock.advance(5)
        store.observe(replace(other, position=index * 5))
    store.close()

    rows = _rows(path)
    assert [row["title"] for row in rows] == ["Пыяла", "Другая"]
    assert all(row["listened_ms"] >= 30_000 for row in rows)


def test_disabled_stats_writes_nothing(tmp_path, monkeypatch) -> None:
    clock = FakeClock()
    monkeypatch.setattr(stats, "time", clock)
    path = tmp_path / "stats.db"
    store = StatsStore(path, enabled=False)
    store.observe(_view())
    clock.advance(35)
    store.observe(_view(position=35))
    store.close()
    assert not path.exists()


def test_completed_detection() -> None:
    assert stats._completed(35_000, 30_000, 30, 30) is True
    assert stats._completed(30_000, 200_000, 30, 200) is False
    assert stats._completed(29_999, 0, 0, 0) is False
    assert stats._completed(30_000, 0, 0, 0) is True
    assert stats._completed(30_000, 200_000, 198, 200) is True
    assert stats._completed(0, 0, 0, 0) is False


def test_summary_aggregates_and_threshold(tmp_path) -> None:
    path = tmp_path / "stats.db"
    now = int(time.time())
    _insert(path, track_key="a", title="A", artist="Alpha", listened_ms=40_000, started_at=now - 100)
    _insert(path, track_key="a", title="A", artist="Alpha", listened_ms=30_000, started_at=now - 50)
    _insert(path, track_key="b", title="B", artist="Beta", listened_ms=10_000, started_at=now - 10)

    result = summary(path, Period.ALL)
    assert result["listened_ms"] == 80_000
    assert result["plays"] == 2
    assert result["tracks"] == 1
    assert result["artists"] == 1
    assert len(result["top_tracks"]) == 1
    assert result["top_tracks"][0]["track_key"] == "a"
    assert result["top_tracks"][0]["plays"] == 2
    assert result["top_tracks"][0]["listened_ms"] == 70_000
    assert len(result["top_artists"]) == 1
    assert result["top_artists"][0]["artist"] == "Alpha"
    assert len(result["recent"]) == 2


def test_summary_filters_by_period(tmp_path) -> None:
    path = tmp_path / "stats.db"
    now = int(time.time())
    _insert(path, track_key="new", title="New", artist="A", listened_ms=40_000, started_at=now)
    _insert(
        path,
        track_key="old",
        title="Old",
        artist="B",
        listened_ms=50_000,
        started_at=now - 40 * 86400,
    )

    day = summary(path, Period.DAY)
    assert day["plays"] == 1
    assert day["listened_ms"] == 40_000

    everything = summary(path, Period.ALL)
    assert everything["plays"] == 2
    assert everything["listened_ms"] == 90_000


def test_summary_missing_database(tmp_path) -> None:
    assert summary(tmp_path / "missing.db", Period.ALL) == empty_summary()


def test_period_start() -> None:
    moment = datetime(2026, 10, 23, 15, 30, 45)
    assert period_start(Period.DAY, moment) == int(datetime(2026, 10, 23).timestamp())
    assert period_start(Period.WEEK, moment) == int(datetime(2026, 10, 19).timestamp())
    assert period_start(Period.MONTH, moment) == int(datetime(2026, 10, 1).timestamp())
    assert period_start(Period.ALL, moment) == 0


def test_daily_activity(tmp_path) -> None:
    path = tmp_path / "stats.db"
    now = int(time.time())
    _insert(path, track_key="a", title="A", artist="Alpha", listened_ms=40_000, started_at=now)
    _insert(path, track_key="b", title="B", artist="Beta", listened_ms=10_000, started_at=now)

    days = daily_activity(path, days=3)
    assert len(days) == 3
    assert days[-1]["date"] == datetime.now().strftime("%Y-%m-%d")
    assert days[-1]["listened_ms"] == 50_000
    assert days[-1]["plays"] == 1
    assert days[0]["listened_ms"] == 0


def test_daily_activity_missing_database(tmp_path) -> None:
    days = daily_activity(tmp_path / "missing.db", days=2)
    assert len(days) == 2
    assert all(day["listened_ms"] == 0 for day in days)


def test_export_csv(tmp_path) -> None:
    path = tmp_path / "stats.db"
    _insert(
        path,
        track_key="a",
        title="Пыяла",
        artist="АИГЕЛ",
        listened_ms=40_000,
        started_at=int(time.time()),
    )
    target = export_csv(path, tmp_path / "history.csv")
    assert target == tmp_path / "history.csv"
    assert target.read_bytes().startswith(b"\xef\xbb\xbf")
    text = target.read_text(encoding="utf-8-sig")
    lines = text.splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("started_at;title;artist")
    assert "Пыяла" in lines[1]
    assert "40000" in lines[1]


def test_export_csv_escapes_formula_injection(tmp_path) -> None:
    path = tmp_path / "stats.db"
    _insert(
        path,
        track_key="formula",
        title="=HYPERLINK(\"https://evil.example\")",
        artist="+cmd",
        album="-1+1",
        source="@SUM(A1:A2)",
        listened_ms=40_000,
        started_at=int(time.time()),
    )
    target = export_csv(path, tmp_path / "history.csv")
    with target.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.reader(stream, delimiter=";"))
    assert len(rows) == 2
    assert rows[1][1].startswith("'=")
    assert rows[1][2].startswith("'+")
    assert rows[1][3].startswith("'-")
    assert rows[1][4].startswith("'@")


def test_empty_summary_shape() -> None:
    result = empty_summary()
    assert set(result) == {"listened_ms", "plays", "tracks", "artists", "top_tracks", "top_artists", "recent"}
    assert result["listened_ms"] == 0
    assert result["top_tracks"] == []


def test_stats_store_close_is_idempotent(tmp_path) -> None:
    store = StatsStore(tmp_path / "stats.db")
    store.close()
    store.close()
    assert store._connection is None
