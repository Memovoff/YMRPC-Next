"""Единая точка обогащения трека обложкой, ссылками и метаданными."""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict

from ..i18n import source_label
from ..models import MediaSnapshot, Track
from .catalogs import FallbackCatalogs
from .yandex import YandexService

logger = logging.getLogger(__name__)


class Resolver:
    def __init__(self, yandex: YandexService, catalogs: FallbackCatalogs | None = None):
        self._yandex = yandex
        self._catalogs = catalogs or FallbackCatalogs()
        self._cache: OrderedDict[tuple[str, str, str], Track] = OrderedDict()
        self._limit = 300

    def clear_cache(self) -> None:
        self._cache.clear()

    async def resolve(self, media: MediaSnapshot, timeout: float = 12.0) -> Track:
        key = media.identity
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            return cached
        try:
            track = await asyncio.wait_for(self._resolve(media), timeout)
        except TimeoutError:
            logger.info("Обогащение трека заняло слишком много времени: %s", media.title)
            track = self._generic(media)
        except Exception as error:  # noqa: BLE001
            logger.warning("Ошибка обогащения трека: %s", error)
            track = self._generic(media)
        self._remember(key, track)
        return track

    async def _resolve(self, media: MediaSnapshot) -> Track:
        if media.external_id:
            track = await self._yandex.track_by_id(media.external_id)
            if track is not None:
                return _merge(media, track)

        if self._yandex.configured and media.title:
            track = await self._yandex.search(media)
            if track is not None:
                return _merge(media, track)

        if media.title:
            track = await self._catalogs.search(media)
            if track is not None:
                return _merge(media, track)

        return self._generic(media)

    def _generic(self, media: MediaSnapshot) -> Track:
        return Track(
            title=media.title or "Неизвестный трек",
            artist=media.artist,
            album=media.album,
            duration=media.duration,
            source=source_label(media.source_id, media.source_name),
        )

    def _remember(self, key: tuple[str, str, str], track: Track) -> None:
        self._cache[key] = track
        self._cache.move_to_end(key)
        while len(self._cache) > self._limit:
            self._cache.popitem(last=False)

    async def close(self) -> None:
        await self._catalogs.close()


def _merge(media: MediaSnapshot, track: Track) -> Track:
    """Дополняем найденный трек тем, что уже знает плеер."""
    from dataclasses import replace

    values = {}
    if not track.artist and media.artist:
        values["artist"] = media.artist
    if not track.album and media.album:
        values["album"] = media.album
    if not track.duration and media.duration:
        values["duration"] = media.duration
    return replace(track, **values) if values else track
