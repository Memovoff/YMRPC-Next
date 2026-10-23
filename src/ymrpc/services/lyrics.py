"""Синхронизированные тексты: LRCLIB + запасной вариант из Яндекс Музыки."""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass

import httpx

from ..constants import HTTP_USER_AGENT
from ..models import Lyrics, LyricsLine, Track
from .yandex import YandexService

logger = logging.getLogger(__name__)

LRC_LINE = re.compile(r"^((?:\[[^\]]+\])+)(.*)$")
LRC_TIME = re.compile(r"\[(?:(\d+):)?(\d{1,2}):(\d{2})(?:[.:](\d{1,3}))?\]")
LRC_WORDS = re.compile(r"<[^>]+>")
OFFSET = re.compile(r"\[offset:\s*([+-]?\d+)\]", re.IGNORECASE)
METADATA = re.compile(r"^\[(ar|ti|al|by|offset|length|re|ve):.*\]$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class _Entry:
    lyrics: Lyrics
    at: float


class LyricsService:
    def __init__(self):
        self._client: httpx.AsyncClient | None = None
        self._cache: dict[tuple[str, str, int], _Entry] = {}
        self._limit = 120

    def _http(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(8, connect=4),
                headers={"User-Agent": HTTP_USER_AGENT},
                follow_redirects=True,
            )
        return self._client

    def cached(self, track: Track, duration: float = 0) -> Lyrics | None:
        return self._lookup(track, duration)

    async def get(self, track: Track, yandex: YandexService, duration: float = 0) -> Lyrics:
        cached = self._lookup(track, duration)
        if cached is not None:
            return cached

        lyrics = await self._from_lrclib(track, duration)
        if lyrics is None or not lyrics.synced:
            yandex_text = await yandex.lyrics(track)
            if yandex_text:
                plain = _plain(yandex_text, track)
                if lyrics is None or not lyrics.available:
                    lyrics = plain
                elif not lyrics.plain:
                    from dataclasses import replace

                    lyrics = replace(lyrics, plain=plain.plain)

        if lyrics is None:
            lyrics = Lyrics(track_key=track.key, source="none")
        self._store(track, duration, lyrics)
        return lyrics

    def _lookup(self, track: Track, duration: float) -> Lyrics | None:
        entry = self._cache.get(_key(track, duration))
        if entry is None:
            return None
        if time.monotonic() - entry.at > 6 * 3600:
            self._cache.pop(_key(track, duration), None)
            return None
        return entry.lyrics

    def _store(self, track: Track, duration: float, lyrics: Lyrics) -> None:
        self._cache[_key(track, duration)] = _Entry(lyrics, time.monotonic())
        while len(self._cache) > self._limit:
            self._cache.pop(next(iter(self._cache)))

    async def _from_lrclib(self, track: Track, duration: float) -> Lyrics | None:
        params = {"artist_name": track.artist, "track_name": track.title}
        if track.album:
            params["album_name"] = track.album
        if duration or track.duration:
            params["duration"] = str(int(duration or track.duration))

        data = await self._json("https://lrclib.net/api/get", params)
        if data is None:
            data = await self._json("https://lrclib.net/api/search", params)
            if isinstance(data, list):
                data = data[0] if data else None
        if not isinstance(data, dict):
            return None

        synced = data.get("syncedLyrics")
        plain = data.get("plainLyrics")
        if synced:
            parsed = parse_lrc(str(synced))
            if parsed:
                return Lyrics(
                    track_key=track.key,
                    lines=tuple(parsed),
                    plain=str(plain or "").strip(),
                    source="LRCLIB",
                    synced=True,
                )
        if plain:
            return _plain(str(plain), track, source="LRCLIB")
        return None

    async def _json(self, url: str, params: dict):
        try:
            response = await self._http().get(url, params=params)
            if response.status_code == 404:
                return None
            if response.status_code != 200:
                logger.debug("LRCLIB ответил %s", response.status_code)
                return None
            return response.json()
        except (httpx.HTTPError, ValueError) as error:
            logger.debug("LRCLIB недоступен: %s", error)
            return None

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


def _key(track: Track, duration: float) -> tuple[str, str, int]:
    return (
        track.artist.casefold().strip(),
        track.title.casefold().strip(),
        int(duration or track.duration or 0),
    )


def _plain(text: str, track: Track, source: str = "Яндекс Музыка") -> Lyrics:
    lines = [line.strip() for line in text.replace("\r\n", "\n").split("\n")]
    cleaned = "\n".join(line for line in lines if line).strip()
    return Lyrics(track_key=track.key, plain=cleaned, source=source, synced=False)


def parse_lrc(text: str) -> list[LyricsLine]:
    offset = 0.0
    offset_match = OFFSET.search(text)
    if offset_match:
        offset = int(offset_match.group(1)) / 1000

    rows: list[tuple[float, str]] = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if not line or METADATA.match(line):
            continue
        match = LRC_LINE.match(line)
        if not match:
            continue
        stamps = LRC_TIME.findall(match.group(1))
        if not stamps:
            continue
        lyric = LRC_WORDS.sub("", match.group(2)).strip()
        if not lyric:
            continue
        for hours, minutes, seconds, fraction in stamps:
            try:
                if hours:
                    # Формат [mm:ss] уже разобран как минуты; [hh:mm:ss] встречается редко.
                    total = int(hours) * 3600 + int(minutes) * 60 + int(seconds)
                else:
                    total = int(minutes) * 60 + int(seconds)
                if fraction:
                    total += int(fraction.ljust(3, "0")[:3]) / 1000
            except ValueError:
                continue
            rows.append((total + offset, lyric))

    rows.sort(key=lambda item: item[0])
    result: list[LyricsLine] = []
    seen: set[tuple[int, str]] = set()
    for timestamp, lyric in rows:
        key = (int(timestamp * 100), lyric)
        if key in seen:
            continue
        seen.add(key)
        result.append(LyricsLine(time=max(0.0, timestamp), text=lyric))
    return result


def split_plain(text: str) -> list[str]:
    return [line.strip() for line in text.replace("\r\n", "\n").split("\n") if line.strip()]
