"""Захват медиа через Windows System Media Transport Controls (SMTC)."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime

from ..i18n import source_label
from ..models import MediaSnapshot, PlaybackStatus, SessionInfo, Settings
from .rules import choose

logger = logging.getLogger(__name__)

try:
    from winrt.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as SessionManager,
    )
    from winrt.windows.storage.streams import DataReader

    AVAILABLE = True
except Exception as error:  # pragma: no cover - зависит от Windows
    SessionManager = None
    DataReader = None
    AVAILABLE = False
    logger.warning("Windows SMTC недоступен: %s", error)


_STATUS_MAP = {
    0: PlaybackStatus.STOPPED,   # CLOSED
    1: PlaybackStatus.UNKNOWN,   # OPENED
    2: PlaybackStatus.UNKNOWN,   # CHANGING
    3: PlaybackStatus.STOPPED,
    4: PlaybackStatus.PLAYING,
    5: PlaybackStatus.PAUSED,
}


def _status(value) -> PlaybackStatus:
    try:
        return _STATUS_MAP.get(int(value), PlaybackStatus.UNKNOWN)
    except (TypeError, ValueError):
        name = str(getattr(value, "name", value)).upper()
        return {
            "PLAYING": PlaybackStatus.PLAYING,
            "PAUSED": PlaybackStatus.PAUSED,
            "STOPPED": PlaybackStatus.STOPPED,
        }.get(name, PlaybackStatus.UNKNOWN)


def _timeline_position(
    position: float,
    duration: float,
    last_updated: datetime | None,
    status: PlaybackStatus,
    *,
    now: datetime | None = None,
) -> float:
    """Досчитывает позицию от last_updated_time.

    Многие приложения (в том числе Яндекс Музыка) не обновляют position в SMTC
    на каждом чтении, а лишь один раз при старте трека или перемотке. Без этой
    поправки таймер замирает на одном значении.
    """
    position = max(0.0, position)
    if status == PlaybackStatus.PLAYING and last_updated is not None:
        moment = now or datetime.now(UTC)
        try:
            updated = last_updated
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=UTC)
            elapsed = (moment - updated.astimezone(UTC)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            elapsed = -1.0
        # Отрицательное или абсурдно большое время означает, что метка
        # недостоверна: доверяем только исходной позиции.
        if 0.0 <= elapsed <= 86_400.0:
            position += elapsed
    if duration > 0:
        position = min(position, duration)
    return position


class WindowsMediaSource:
    """Читает GSMTC-сессии. Все тяжёлые операции ограничены таймаутом."""

    def __init__(self, *, request_timeout: float = 6.0):
        self._manager = None
        self._sessions = []
        self._last_session = None
        self._last_source = ""
        self._last_infos: list[SessionInfo] = []
        self._meta_cache: dict[str, tuple[float, tuple[str, str, str]]] = {}
        self._timeout = request_timeout
        self._failures = 0
        self._last_error = ""
        self.state = "starting" if AVAILABLE else "unavailable"

    @property
    def available(self) -> bool:
        return AVAILABLE

    @property
    def last_infos(self) -> list[SessionInfo]:
        return list(self._last_infos)

    async def _ensure_manager(self):
        if not AVAILABLE:
            raise RuntimeError("Windows media service is unavailable")
        if self._manager is None:
            self._manager = await asyncio.wait_for(SessionManager.request_async(), self._timeout)
            self.state = "ok"
        return self._manager

    async def _read_sessions(self) -> None:
        manager = await self._ensure_manager()
        self._sessions = list(manager.get_sessions())
        if not self._sessions:
            self.state = "idle"

    async def session_infos(self) -> list[SessionInfo]:
        try:
            await self._read_sessions()
            infos = []
            for session in self._sessions:
                source_id = session.source_app_user_model_id or ""
                if not source_id:
                    continue
                try:
                    playback = session.get_playback_info()
                    status = _status(playback.playback_status)
                except Exception:
                    status = PlaybackStatus.UNKNOWN
                infos.append(
                    SessionInfo(
                        source_id=source_id,
                        source_name=source_label(source_id),
                        status=status,
                    )
                )
            self._last_infos = list(infos)
            return infos
        except Exception as error:
            self._failed(error)
            return []

    async def read(self, settings: Settings) -> MediaSnapshot | None:
        try:
            await self._read_sessions()
            infos = []
            handles = {}
            for session in self._sessions:
                source_id = session.source_app_user_model_id or ""
                if not source_id:
                    continue
                try:
                    playback = session.get_playback_info()
                    status = _status(playback.playback_status)
                except Exception:
                    status = PlaybackStatus.UNKNOWN
                info = SessionInfo(
                    source_id=source_id,
                    source_name=source_label(source_id),
                    status=status,
                )
                infos.append(info)
                handles[source_id] = session

            self._last_infos = list(infos)
            selected = choose(infos, settings.rules, settings.selected_session)
            if selected is None:
                self.state = "idle" if not infos else "ok"
                self._last_session = None
                return None

            session = handles[selected.source_id]
            self._last_session = session
            self._last_source = selected.source_id

            title, artist, album = await self._metadata(session, selected.source_id)
            if not title and not artist:
                self.state = "idle"
                return None

            position, duration = self._timeline(session, selected.status)
            self.state = "ok"
            self._failures = 0
            return MediaSnapshot(
                source_id=selected.source_id,
                source_name=selected.source_name,
                title=title,
                artist=artist,
                album=album,
                position=position,
                duration=duration,
                status=selected.status,
            )
        except TimeoutError:
            self._failed(RuntimeError("Windows media request timed out"))
            return None
        except Exception as error:
            self._failed(error)
            return None

    async def _metadata(self, session, source_id: str) -> tuple[str, str, str]:
        cached = self._meta_cache.get(source_id)
        now = time.monotonic()
        if cached and now - cached[0] < 1.5:
            return cached[1]
        info = await asyncio.wait_for(session.try_get_media_properties_async(), self._timeout)
        values = (
            (info.title or "").strip(),
            (info.artist or "").strip(),
            (info.album_title or "").strip(),
        )
        self._meta_cache[source_id] = (now, values)
        return values

    @staticmethod
    def _timeline(session, status: PlaybackStatus) -> tuple[float, float]:
        try:
            timeline = session.get_timeline_properties()
            start = timeline.start_time.total_seconds()
            end = timeline.end_time.total_seconds()
            raw_position = timeline.position.total_seconds()
            duration = max(0.0, end - start)
            position = _timeline_position(
                raw_position - start,
                duration,
                getattr(timeline, "last_updated_time", None),
                status,
            )
            return position, duration
        except Exception:
            return 0.0, 0.0

    async def thumbnail(self) -> tuple[bytes, str] | None:
        """Обложка текущего трека из SMTC (если приложение её отдаёт)."""
        session = self._last_session
        if session is None or DataReader is None:
            return None
        try:
            info = await asyncio.wait_for(session.try_get_media_properties_async(), self._timeout)
            reference = info.thumbnail
            if reference is None:
                return None
            stream = await asyncio.wait_for(reference.open_read_async(), self._timeout)
            size = int(stream.size or 0)
            if size <= 0 or size > 8 * 1024 * 1024:
                return None
            reader = DataReader(stream)
            try:
                await asyncio.wait_for(reader.load_async(size), self._timeout)
                data = bytes(reader.read_buffer(size))
            finally:
                reader.close()
            content_type = str(stream.content_type or "image/png").split(";")[0]
            return data, content_type
        except Exception as error:
            logger.debug("Не удалось прочитать обложку SMTC: %s", error)
            return None

    async def control(self, action: str, position: float | None = None) -> bool:
        session = self._last_session
        if session is None:
            try:
                await self._read_sessions()
            except Exception as error:
                self._failed(error)
                return False
            if self._sessions:
                session = self._sessions[0]
                self._last_session = session
        if session is None:
            return False
        try:
            if action == "toggle":
                return bool(await asyncio.wait_for(session.try_toggle_play_pause_async(), 3))
            if action == "next":
                return bool(await asyncio.wait_for(session.try_skip_next_async(), 3))
            if action == "previous":
                return bool(await asyncio.wait_for(session.try_skip_previous_async(), 3))
            if action == "seek" and position is not None:
                ticks = int(max(0.0, position) * 10_000_000)
                return bool(
                    await asyncio.wait_for(
                        session.try_change_playback_position_async(ticks), 3
                    )
                )
        except Exception as error:
            logger.warning("Команда %s не выполнена: %s", action, error)
        return False

    def _failed(self, error: Exception) -> None:
        self._failures += 1
        message = f"{type(error).__name__}: {error}"
        if message != self._last_error:
            logger.warning("Ошибка Windows Media: %s", message)
            self._last_error = message
        self.state = "unavailable"
        if self._failures >= 3:
            self._manager = None
            self._sessions = []
            self._failures = 0

    async def close(self) -> None:
        self._manager = None
        self._sessions = []
        self._last_session = None
