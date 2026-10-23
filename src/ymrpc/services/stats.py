"""Статистика прослушиваний на SQLite."""

from __future__ import annotations

import csv
import logging
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from ..constants import data_dir
from ..models import Period, PlaybackView

logger = logging.getLogger(__name__)

PLAY_THRESHOLD_MS = 30_000
FLUSH_INTERVAL = 10.0
SCHEMA = """
CREATE TABLE IF NOT EXISTS plays (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    track_key TEXT NOT NULL,
    title TEXT NOT NULL,
    artist TEXT NOT NULL,
    album TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    yandex_id TEXT,
    started_at INTEGER NOT NULL,
    listened_ms INTEGER NOT NULL DEFAULT 0,
    duration_ms INTEGER NOT NULL DEFAULT 0,
    completed INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_plays_started ON plays(started_at);
CREATE INDEX IF NOT EXISTS idx_plays_track ON plays(track_key);
CREATE INDEX IF NOT EXISTS idx_plays_artist ON plays(artist);
"""


def stats_path() -> Path:
    return data_dir() / "stats.db"


@dataclass(frozen=True, slots=True)
class PlayRecord:
    title: str
    artist: str
    album: str
    source: str
    started_at: int
    listened_ms: int
    duration_ms: int
    completed: bool


class StatsStore:
    """Пишет историю из потока-движка. Каждые 10 секунд сбрасывает прогресс."""

    def __init__(self, path: Path | None = None, enabled: bool = True):
        self.path = path or stats_path()
        self.enabled = enabled
        self._connection: sqlite3.Connection | None = None
        self._key: str | None = None
        self._row_id: int | None = None
        self._listened = 0.0
        self._last_seen = 0.0
        self._last_flush = 0.0
        self._position = 0.0
        self._duration = 0.0
        self._started_at = 0

    def _db(self) -> sqlite3.Connection:
        if self._connection is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._connection = sqlite3.connect(self.path, timeout=5)
            self._connection.executescript(SCHEMA)
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute("PRAGMA synchronous=NORMAL")
            self._connection.commit()
        return self._connection

    def observe(self, view: PlaybackView) -> None:
        if not self.enabled:
            return
        now = time.monotonic()
        key = view.track.key if view.track else None
        if key != self._key:
            self._close_current()
            self._key = key
            if view.track is not None and view.track.title:
                self._start(view, now)
            else:
                self._row_id = None

        if self._row_id is not None:
            if view.is_playing:
                delta = now - self._last_seen if self._last_seen else 0.0
                self._listened += max(0.0, min(delta, 5.0))
            self._position = view.position
            self._duration = view.duration or (view.track.duration if view.track else 0)
            if now - self._last_flush >= FLUSH_INTERVAL:
                self.flush()
        self._last_seen = now

    def _start(self, view: PlaybackView, now: float) -> None:
        track = view.track
        if track is None:
            return
        self._started_at = int(time.time())
        self._listened = 0.0
        self._last_seen = now
        self._last_flush = now
        self._position = view.position
        self._duration = view.duration or track.duration
        try:
            cursor = self._db().execute(
                "INSERT INTO plays "
                "(track_key, title, artist, album, source, yandex_id, started_at, listened_ms, duration_ms, completed) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, 0)",
                (
                    track.key,
                    track.title[:300],
                    track.artist[:300],
                    track.album[:300],
                    (view.source_name or track.source)[:120],
                    track.yandex_id,
                    self._started_at,
                    int(self._duration * 1000),
                ),
            )
            self._row_id = int(cursor.lastrowid)
            self._db().commit()
        except sqlite3.Error as error:
            logger.warning("Не удалось записать начало прослушивания: %s", error)
            self._row_id = None

    def flush(self) -> None:
        if self._row_id is None or self._connection is None:
            return
        self._last_flush = time.monotonic()
        listened = int(self._listened * 1000)
        duration_ms = int(self._duration * 1000)
        completed = _completed(listened, duration_ms, self._position, self._duration)
        try:
            self._connection.execute(
                "UPDATE plays SET listened_ms = ?, duration_ms = ?, completed = ? WHERE id = ?",
                (listened, duration_ms, 1 if completed else 0, self._row_id),
            )
            self._connection.commit()
        except sqlite3.Error as error:
            logger.warning("Не удалось обновить статистику: %s", error)

    def _close_current(self) -> None:
        if self._row_id is not None:
            self.flush()
        self._row_id = None
        self._key = None
        self._listened = 0.0
        self._last_seen = 0.0

    def close(self) -> None:
        self._close_current()
        if self._connection is not None:
            self._connection.close()
            self._connection = None


def _completed(listened_ms: int, duration_ms: int, position: float, duration: float) -> bool:
    if duration_ms <= 0:
        return listened_ms >= PLAY_THRESHOLD_MS
    if listened_ms >= duration_ms * 0.9:
        return True
    return duration > 0 and position >= duration - 3 and listened_ms >= PLAY_THRESHOLD_MS


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, timeout=5)
    connection.row_factory = sqlite3.Row
    return connection


def period_start(period: Period, now: datetime | None = None) -> int:
    now = now or datetime.now()
    if period == Period.DAY:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == Period.WEEK:
        start = (now - timedelta(days=now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    elif period == Period.MONTH:
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        return 0
    return int(start.timestamp())


def summary(path: Path | None = None, period: Period = Period.WEEK) -> dict:
    path = path or stats_path()
    if not path.exists():
        return _empty_summary()
    since = period_start(period)
    try:
        with _connect(path) as connection:
            totals = connection.execute(
                "SELECT COALESCE(SUM(listened_ms),0) AS listened_ms, "
                "COALESCE(SUM(CASE WHEN listened_ms >= ? THEN 1 ELSE 0 END),0) AS plays, "
                "COUNT(DISTINCT CASE WHEN listened_ms >= ? THEN track_key END) AS tracks, "
                "COUNT(DISTINCT CASE WHEN listened_ms >= ? THEN artist END) AS artists "
                "FROM plays WHERE started_at >= ?",
                (PLAY_THRESHOLD_MS, PLAY_THRESHOLD_MS, PLAY_THRESHOLD_MS, since),
            ).fetchone()
            top_tracks = connection.execute(
                "SELECT track_key, title, artist, COUNT(*) AS plays, SUM(listened_ms) AS listened_ms "
                "FROM plays WHERE started_at >= ? GROUP BY track_key, title, artist "
                "HAVING SUM(listened_ms) >= ? ORDER BY listened_ms DESC LIMIT 10",
                (since, PLAY_THRESHOLD_MS),
            ).fetchall()
            top_artists = connection.execute(
                "SELECT artist, COUNT(*) AS plays, SUM(listened_ms) AS listened_ms "
                "FROM plays WHERE started_at >= ? AND artist <> '' "
                "GROUP BY artist HAVING SUM(listened_ms) >= ? ORDER BY listened_ms DESC LIMIT 10",
                (since, PLAY_THRESHOLD_MS),
            ).fetchall()
            recent = connection.execute(
                "SELECT title, artist, album, source, started_at, listened_ms, duration_ms, completed "
                "FROM plays WHERE started_at >= ? AND listened_ms >= ? "
                "ORDER BY started_at DESC LIMIT 30",
                (since, PLAY_THRESHOLD_MS),
            ).fetchall()
    except sqlite3.Error as error:
        logger.warning("Не удалось прочитать статистику: %s", error)
        return _empty_summary()

    return {
        "listened_ms": int(totals["listened_ms"] or 0),
        "plays": int(totals["plays"] or 0),
        "tracks": int(totals["tracks"] or 0),
        "artists": int(totals["artists"] or 0),
        "top_tracks": [dict(row) for row in top_tracks],
        "top_artists": [dict(row) for row in top_artists],
        "recent": [dict(row) for row in recent],
    }


def daily_activity(path: Path | None = None, days: int = 14) -> list[dict]:
    """Активность по дням для графика."""
    path = path or stats_path()
    days = max(1, min(60, int(days)))
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    start = today - timedelta(days=days - 1)
    if not path.exists():
        return _empty_days(start, days)
    try:
        with _connect(path) as connection:
            rows = connection.execute(
                "SELECT date(started_at, 'unixepoch', 'localtime') AS day, "
                "COALESCE(SUM(listened_ms), 0) AS listened_ms, "
                "COALESCE(SUM(CASE WHEN listened_ms >= ? THEN 1 ELSE 0 END), 0) AS plays "
                "FROM plays WHERE started_at >= ? GROUP BY day",
                (PLAY_THRESHOLD_MS, int(start.timestamp())),
            ).fetchall()
    except sqlite3.Error as error:
        logger.warning("Не удалось построить график: %s", error)
        return _empty_days(start, days)
    values = {str(row["day"]): (int(row["listened_ms"]), int(row["plays"])) for row in rows}
    result = []
    for index in range(days):
        moment = start + timedelta(days=index)
        key = moment.strftime("%Y-%m-%d")
        listened, plays = values.get(key, (0, 0))
        result.append(
            {
                "date": key,
                "label": moment.strftime("%d.%m"),
                "listened_ms": listened,
                "plays": plays,
            }
        )
    return result


def _empty_days(start: datetime, days: int) -> list[dict]:
    return [
        {
            "date": (start + timedelta(days=index)).strftime("%Y-%m-%d"),
            "label": (start + timedelta(days=index)).strftime("%d.%m"),
            "listened_ms": 0,
            "plays": 0,
        }
        for index in range(days)
    ]


def _csv_safe(value: object) -> str:
    text = str(value)
    if text.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + text
    return text


def export_csv(path: Path | None = None, target: Path | None = None) -> Path:
    path = path or stats_path()
    target = target or (data_dir() / f"history-{datetime.now():%Y-%m-%d}.csv")
    with _connect(path) as connection:
        rows = connection.execute(
            "SELECT started_at, title, artist, album, source, listened_ms, duration_ms, completed "
            "FROM plays ORDER BY started_at"
        ).fetchall()
    with target.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.writer(stream, delimiter=";")
        writer.writerow(
            ["started_at", "title", "artist", "album", "source", "listened_ms", "duration_ms", "completed"]
        )
        for row in rows:
            writer.writerow(
                [
                    datetime.fromtimestamp(row["started_at"]).isoformat(sep=" "),
                    _csv_safe(row["title"]),
                    _csv_safe(row["artist"]),
                    _csv_safe(row["album"]),
                    _csv_safe(row["source"]),
                    row["listened_ms"],
                    row["duration_ms"],
                    row["completed"],
                ]
            )
    return target


def empty_summary() -> dict:
    return _empty_summary()


def _empty_summary() -> dict:
    return {
        "listened_ms": 0,
        "plays": 0,
        "tracks": 0,
        "artists": 0,
        "top_tracks": [],
        "top_artists": [],
        "recent": [],
    }
