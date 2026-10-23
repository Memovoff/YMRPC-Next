"""Резервные каталоги обложек и ссылок: iTunes и Deezer (без ключей)."""

from __future__ import annotations

import logging
from datetime import datetime

import httpx

from ..constants import HTTP_USER_AGENT
from ..matching import choose
from ..models import MediaSnapshot, Track

logger = logging.getLogger(__name__)


class CatalogClient:
    def __init__(self):
        self._client: httpx.AsyncClient | None = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(7, connect=4),
                headers={"User-Agent": HTTP_USER_AGENT},
                follow_redirects=True,
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _json(self, url: str, params: dict) -> dict | None:
        try:
            response = await self._http().get(url, params=params)
            if response.status_code != 200:
                return None
            data = response.json()
            return data if isinstance(data, dict) else None
        except (httpx.HTTPError, ValueError) as error:
            logger.debug("Каталог %s недоступен: %s", url, error)
            return None


class ITunesCatalog(CatalogClient):
    async def search(self, media: MediaSnapshot) -> Track | None:
        term = " ".join(part for part in (media.artist, media.title) if part).strip()
        if not term:
            return None
        data = await self._json(
            "https://itunes.apple.com/search",
            {"term": term, "entity": "song", "limit": 8, "country": "ru"},
        )
        if not data:
            return None
        tracks = []
        for row in data.get("results", [])[:8]:
            if not isinstance(row, dict):
                continue
            cover = str(row.get("artworkUrl100") or "")
            cover = cover.replace("100x100bb", "600x600bb").replace("100x100", "600x600")
            year = None
            release = str(row.get("releaseDate") or "")
            if len(release) >= 4 and release[:4].isdigit():
                year = int(release[:4])
            tracks.append(
                Track(
                    title=str(row.get("trackName") or "").strip(),
                    artist=str(row.get("artistName") or "").strip(),
                    album=str(row.get("collectionName") or "").strip(),
                    year=year,
                    duration=float(row.get("trackTimeMillis") or 0) / 1000,
                    cover_url=cover or None,
                    track_url=str(row.get("trackViewUrl") or "") or None,
                    source="iTunes",
                )
            )
        return choose(media, tracks)


class DeezerCatalog(CatalogClient):
    async def search(self, media: MediaSnapshot) -> Track | None:
        term = " ".join(part for part in (media.artist, media.title) if part).strip()
        if not term:
            return None
        data = await self._json("https://api.deezer.com/search", {"q": term, "limit": 8})
        if not data:
            return None
        tracks = []
        for row in data.get("data", [])[:8]:
            if not isinstance(row, dict):
                continue
            album = row.get("album") or {}
            cover = str(album.get("cover_xl") or album.get("cover_big") or "") or None
            tracks.append(
                Track(
                    title=str(row.get("title") or "").strip(),
                    artist=str((row.get("artist") or {}).get("name") or "").strip(),
                    album=str(album.get("title") or "").strip(),
                    duration=float(row.get("duration") or 0),
                    cover_url=cover,
                    track_url=str(row.get("link") or "") or None,
                    source="Deezer",
                )
            )
        return choose(media, tracks)


class FallbackCatalogs:
    def __init__(self):
        self.itunes = ITunesCatalog()
        self.deezer = DeezerCatalog()

    async def search(self, media: MediaSnapshot) -> Track | None:
        track = await self.itunes.search(media)
        if track is not None:
            return track
        return await self.deezer.search(media)

    async def close(self) -> None:
        await self.itunes.close()
        await self.deezer.close()


def _year(value: str) -> int | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).year
    except (ValueError, TypeError):
        return None
