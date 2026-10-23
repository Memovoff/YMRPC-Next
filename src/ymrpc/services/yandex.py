"""Работа с API Яндекс Музыки: аккаунт, поиск, метаданные, тексты."""

from __future__ import annotations

import asyncio
import logging
import threading

from yandex_music import Client

from ..matching import choose
from ..models import MediaSnapshot, Track

logger = logging.getLogger(__name__)


class YandexService:
    def __init__(self):
        self._client: Client | None = None
        self._token = ""
        self._lock = threading.Lock()

    @property
    def configured(self) -> bool:
        return self._client is not None

    @property
    def token(self) -> str:
        return self._token

    async def login(self, token: str) -> str:
        token = token.strip()

        def _login() -> tuple[Client, str]:
            client = Client(token=token).init()
            account = client.me.account
            name = (account.display_name or account.login or "Yandex Music").strip()
            return client, name

        client, name = await asyncio.to_thread(_login)
        with self._lock:
            self._client = client
            self._token = token
        logger.info("Вход выполнен: %s", name)
        return name

    async def restore(self, token: str) -> str:
        return await self.login(token)

    async def logout(self) -> None:
        self._client = None
        self._token = ""

    async def search(self, media: MediaSnapshot) -> Track | None:
        client = self._client
        if client is None:
            return None
        query = " ".join(part for part in (media.artist, media.title) if part).strip()
        if not query:
            return None

        def _search() -> list[Track]:
            with self._lock:
                result = client.search(query, type_="track")
                rows = getattr(getattr(result, "tracks", None), "results", None) or []
                return [_map_track(track, media.source_name) for track in rows]

        try:
            tracks = await asyncio.wait_for(asyncio.to_thread(_search), 12)
        except Exception as error:  # noqa: BLE001
            logger.warning("Поиск Яндекс Музыки не удался: %s", error)
            return None
        return choose(media, tracks)

    async def track_by_id(self, track_id: str) -> Track | None:
        client = self._client
        if client is None or not track_id:
            return None

        def _fetch() -> Track | None:
            with self._lock:
                rows = client.tracks([track_id])
                return _map_track(rows[0], "Яндекс Музыка") if rows else None

        try:
            return await asyncio.wait_for(asyncio.to_thread(_fetch), 12)
        except Exception as error:  # noqa: BLE001
            logger.debug("Не удалось получить трек %s: %s", track_id, error)
            return None

    async def lyrics(self, track: Track) -> str | None:
        client = self._client
        track_id = (track.yandex_id or "").split(":")[0]
        if client is None or not track_id:
            return None

        def _fetch() -> str | None:
            with self._lock:
                lyrics = client.tracks_lyrics(track_id)
                if lyrics is None:
                    return None
                text = lyrics.fetch_lyrics()
                return text.strip() or None

        try:
            return await asyncio.wait_for(asyncio.to_thread(_fetch), 12)
        except Exception as error:  # noqa: BLE001
            logger.debug("Текст из Яндекс Музыки недоступен: %s", error)
            return None

    async def close(self) -> None:
        await self.logout()


def _map_track(track, source: str) -> Track:
    album = track.albums[0] if getattr(track, "albums", None) else None
    artists = ", ".join(
        artist.name for artist in (getattr(track, "artists", None) or []) if getattr(artist, "name", None)
    )
    track_id = str(getattr(track, "id", "") or "").split(":")[0]
    album_id = getattr(album, "id", None) if album is not None else None
    cover = None
    try:
        cover = track.get_cover_url("400x400")
    except Exception:
        cover = None
    if not cover:
        og_image = getattr(track, "og_image", None)
        if og_image:
            cover = "https:" + og_image[:-2] + "400x400" if og_image.endswith("%%") else og_image
    url = None
    app_url = None
    if album_id and track_id:
        url = f"https://music.yandex.ru/album/{album_id}/track/{track_id}"
        app_url = f"yandexmusic://album/{album_id}/track/{track_id}"
    duration = (getattr(track, "duration_ms", 0) or 0) / 1000
    year = getattr(album, "year", None) if album is not None else None
    return Track(
        title=(getattr(track, "title", "") or "").strip(),
        artist=artists.strip(),
        album=(getattr(album, "title", "") or "").strip() if album is not None else "",
        year=int(year) if year else None,
        duration=duration,
        cover_url=cover,
        track_url=url,
        app_url=app_url,
        yandex_id=track_id or None,
        source=source,
    )
