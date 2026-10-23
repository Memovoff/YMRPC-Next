"""Главный асинхронный движок приложения."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
from dataclasses import replace

from . import __version__
from .bridge import Bridge
from .config import ConfigStore
from .constants import data_dir
from .discord_ipc import DiscordService
from .i18n import source_label, t
from .models import (
    CaptureMode,
    Lyrics,
    MediaSnapshot,
    PlaybackStatus,
    PlaybackView,
    Settings,
    Track,
    UpdateProgress,
)
from .presence import build_activity, client_id, format_duration
from .secure_store import TokenStore
from .services.art import ArtCache
from .services.lyrics import LyricsService
from .services.overlay import OverlayServer, OverlayState
from .services.resolver import Resolver
from .services.stats import StatsStore
from .services.updater import Updater, launch_installer
from .services.yandex import YandexService
from .sources.rules import choose_auto
from .sources.smtc import WindowsMediaSource
from .sources.ynison import YnisonSource

logger = logging.getLogger(__name__)


class Engine:
    def __init__(self, config: ConfigStore, bridge: Bridge):
        self.config = config
        self.bridge = bridge
        self.settings = config.settings

        self.smtc = WindowsMediaSource()
        self.ynison = YnisonSource()
        self.yandex = YandexService()
        self.resolver = Resolver(self.yandex)
        self.lyrics_service = LyricsService()
        self.art = ArtCache()
        self.stats = StatsStore(enabled=self.settings.stats_enabled)
        self.tokens = TokenStore()
        self.discord = DiscordService(pid=os.getpid())
        self.updater = Updater(__version__)
        self.overlay_state = OverlayState()
        self.overlay = OverlayServer(
            port=self.settings.overlay_port,
            state=self.overlay_state,
            stats_path=self.stats.path,
        )

        self._stop = asyncio.Event()
        self._wake = asyncio.Event()
        self._tasks: set[asyncio.Task] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

        self._current_media: MediaSnapshot | None = None
        self._current_track: Track | None = None
        self._current_key: str | None = None
        self._art_path: str | None = None
        self._lyrics: Lyrics | None = None
        self._account: str | None = None
        self._source_state = "ok"
        self._presence_visible = False
        self._paused_since: float | None = None
        self._last_presence_hash: str | None = None
        self._last_presence_at = 0.0
        self._last_discord_ok = False
        self._discord_waiting_notified = False
        self._last_view: PlaybackView | None = None
        self._last_media_seen = 0.0
        self._started = 0.0
        self._login_task: asyncio.Task | None = None
        self._update_task: asyncio.Task | None = None
        self._last_sessions: tuple | None = None

    # ------------------------------------------------------------------ lifecycle

    async def run(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._started = time.monotonic()
        await self._startup()
        logger.info("Движок запущен")
        while not self._stop.is_set():
            try:
                await self.tick()
            except Exception:  # noqa: BLE001
                logger.exception("Ошибка в цикле движка")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout=1.0)
            self._wake.clear()
        await self._shutdown()

    async def request_stop(self) -> None:
        self._stop.set()
        self._wake.set()

    async def _startup(self) -> None:
        self.art.cleanup()
        self._apply_overlay()
        token = self.tokens.load()
        if token:
            self._login_task = asyncio.create_task(self._restore_account(token))
        else:
            self.bridge.status_changed.emit(t("status.auth_required"))
        if self.settings.auto_update:
            self._spawn(self._delayed_update_check(), "update-check")

    async def _shutdown(self) -> None:
        logger.info("Остановка движка")
        for task in list(self._tasks):
            task.cancel()
        if self._login_task:
            self._login_task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self.stats.close()
        self.overlay.stop()
        self.discord.close()
        await self.resolver.close()
        await self.lyrics_service.close()
        await self.art.close()
        await self.smtc.close()
        await self.ynison.close()
        await self.yandex.close()

    def _spawn(self, coroutine, name: str = "") -> asyncio.Task:
        task = asyncio.create_task(coroutine, name=name or None)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def wake(self) -> None:
        self._wake.set()

    # ------------------------------------------------------------------ settings

    async def update_settings(self, settings: Settings) -> Settings:
        previous = self.settings
        saved = self.config.save(settings)
        if saved == previous:
            return saved
        self.settings = saved
        if previous.overlay_enabled != self.settings.overlay_enabled or (
            previous.overlay_port != self.settings.overlay_port
        ):
            self._restart_overlay()
        if previous.rpc_language != self.settings.rpc_language:
            self.discord.reset()
            self._last_presence_hash = None
        if previous.capture_mode != self.settings.capture_mode:
            self._reset_track()
        if previous.stats_enabled != self.settings.stats_enabled:
            self.stats.enabled = self.settings.stats_enabled
        if previous.presence_enabled != self.settings.presence_enabled:
            self.discord.reset()
            self._last_presence_hash = None
        if previous.ui_language != self.settings.ui_language:
            self.bridge.status_changed.emit(t("status.ready"))
        self._wake.set()
        logger.info("Настройки применены движком")
        return self.settings

    def _apply_overlay(self) -> None:
        if not self.settings.overlay_enabled:
            self.overlay.stop()
            self.bridge.overlay_changed.emit(False, "")
            return
        if self.overlay.running:
            self.bridge.overlay_changed.emit(True, self.overlay.url)
            return
        self.overlay = OverlayServer(
            port=self.settings.overlay_port,
            state=self.overlay_state,
            stats_path=self.stats.path,
        )
        if self.overlay.start():
            self.bridge.overlay_changed.emit(True, self.overlay.url)
        else:
            self.bridge.overlay_changed.emit(False, self.overlay.error)

    def _restart_overlay(self) -> None:
        self.overlay.stop()
        self.overlay = OverlayServer(
            port=self.settings.overlay_port,
            state=self.overlay_state,
            stats_path=self.stats.path,
        )
        self._apply_overlay()

    # ------------------------------------------------------------------ commands

    async def login(self, token: str) -> None:
        try:
            name = await self.yandex.login(token)
        except Exception as error:  # noqa: BLE001
            logger.warning("Вход не выполнен: %s", error)
            self.bridge.login_result.emit(False, str(error))
            return
        try:
            self.tokens.save(token)
        except Exception as error:  # noqa: BLE001
            logger.warning("Не удалось сохранить токен: %s", error)
            await self.yandex.logout()
            self._account = None
            self.bridge.account_changed.emit(None)
            self.bridge.login_result.emit(False, t("auth.save_failed", error=str(error)))
            return
        self._account = name
        self.resolver.clear_cache()
        self._reset_track()
        self.bridge.account_changed.emit(name)
        self.bridge.login_result.emit(True, name)
        self.bridge.status_changed.emit(t("auth.success", name=name))
        self._wake.set()

    async def logout(self) -> None:
        self.tokens.delete()
        await self.yandex.logout()
        self.resolver.clear_cache()
        self._account = None
        self._lyrics = None
        self._reset_track()
        self.bridge.account_changed.emit(None)
        self.bridge.status_changed.emit(t("status.auth_required"))
        self._wake.set()

    async def _restore_account(self, token: str) -> None:
        try:
            name = await self.yandex.login(token)
        except Exception as error:  # noqa: BLE001
            logger.info("Сохранённый токен не подошёл: %s", error)
            self._account = None
            self.bridge.account_changed.emit(None)
            self.bridge.status_changed.emit(t("status.auth_required"))
            return
        self._account = name
        self.resolver.clear_cache()
        self._reset_track()
        self.bridge.account_changed.emit(name)
        logger.info("Аккаунт восстановлен: %s", name)
        self._wake.set()

    async def control(self, action: str, position: float | None = None) -> None:
        media = self._current_media
        if media is None or media.source_id == "ynison":
            return
        await self.smtc.control(action, position)
        self._wake.set()

    async def reload_lyrics(self) -> None:
        if self._current_track is None:
            return
        self._lyrics = None
        self._schedule_lyrics(self._current_track, self._current_media)
        self._wake.set()

    async def check_updates(self, manual: bool = False) -> None:
        info = await self.updater.check(self.settings.update_repo)
        if info is not None:
            self.bridge.update_checked.emit(info)
            self.bridge.status_changed.emit(t("status.update_available", version=info.version))
        elif manual:
            self.bridge.update_checked.emit(None)
        else:
            logger.info("Обновлений нет")

    async def install_update(self, info) -> None:
        try:
            path = await self.updater.download(
                info,
                progress=lambda percent, downloaded, total: self.bridge.update_progress.emit(
                    UpdateProgress(percent, downloaded, total)
                ),
            )
        except Exception as error:  # noqa: BLE001
            logger.warning("Не удалось скачать обновление: %s", error)
            self.bridge.update_ready.emit(False, str(error))
            return
        if launch_installer(path):
            self.bridge.update_ready.emit(True, str(path))
            self.bridge.quit_requested.emit()
        else:
            self.bridge.update_ready.emit(False, str(path))

    async def _delayed_update_check(self) -> None:
        await asyncio.sleep(6)
        await self.check_updates(manual=False)

    # ------------------------------------------------------------------ main tick

    async def tick(self) -> None:
        media = await self._read_media()
        now = time.monotonic()
        if media is not None:
            self._last_media_seen = now
        elif self._last_view is not None and now - self._last_media_seen < 3.0:
            # Короткий провал при переключении трека: не мигаем в Discord.
            self._publish_view(self._last_view, stale=True)
            return

        if media is None:
            await self._on_idle()
            return

        if media.identity != self._current_media_identity():
            await self._on_new_media(media)
        else:
            self._current_media = media
            self._update_position(media)
            if media.status == PlaybackStatus.PAUSED and not self._current_paused:
                self._paused_since = now
            elif media.status == PlaybackStatus.PLAYING:
                self._paused_since = None

        await self._publish(media)

    def _current_media_identity(self) -> tuple[str, str, str] | None:
        return self._current_media.identity if self._current_media else None

    @property
    def _current_paused(self) -> bool:
        return bool(self._current_media and self._current_media.status == PlaybackStatus.PAUSED)

    async def _read_media(self) -> MediaSnapshot | None:
        mode = self.settings.capture_mode
        if mode == CaptureMode.YNISON:
            media, state = await self._read_ynison()
        elif mode == CaptureMode.WINDOWS:
            media, state = await self._read_windows()
        else:
            windows_media, windows_state = await self._read_windows()
            ynison_media: MediaSnapshot | None = None
            ynison_state = "idle"
            if windows_media is None or windows_media.status != PlaybackStatus.PLAYING:
                # Не ждём Ynison, когда локально уже играет музыка.
                ynison_media, ynison_state = await self._read_ynison()
            media = choose_auto(windows_media, ynison_media)
            if media is windows_media:
                state = windows_state
            elif media is ynison_media:
                state = ynison_state
            else:
                state = self._combined_idle_state(windows_state, ynison_state)
        self._source_state = state
        return media

    async def _read_ynison(self) -> tuple[MediaSnapshot | None, str]:
        if not self.yandex.token:
            return None, "auth_required"
        try:
            media = await asyncio.wait_for(self.ynison.read(self.yandex.token), 12)
        except Exception as error:  # noqa: BLE001
            logger.debug("Ynison read failed: %s", error)
            return None, "unavailable"
        return media, self.ynison.state

    async def _read_windows(self) -> tuple[MediaSnapshot | None, str]:
        try:
            media = await asyncio.wait_for(self.smtc.read(self.settings), 12)
        except TimeoutError:
            return None, "unavailable"
        except Exception as error:  # noqa: BLE001
            logger.debug("SMTC read failed: %s", error)
            return None, "unavailable"
        self._emit_sessions(self.smtc.last_infos)
        return media, ("ok" if media else self.smtc.state)

    @staticmethod
    def _combined_idle_state(*states: str) -> str:
        if any(state in {"ok", "idle"} for state in states):
            return "idle"
        return next((state for state in states if state), "idle")

    async def _on_idle(self) -> None:
        if self._current_media is None and self._current_track is None:
            view = PlaybackView(
                source_state=self._source_state,
                account=self._account,
                presence_visible=False,
                stamp=time.monotonic(),
            )
            self.stats.observe(view)
            self._publish_view(view)
            return

        self.stats.observe(
            PlaybackView(
                source_state=self._source_state,
                account=self._account,
                stamp=time.monotonic(),
            )
        )
        self._reset_track()
        self._lyrics = None
        self._paused_since = None
        self.bridge.lyrics_changed.emit(None)
        if self._last_presence_hash is not None:
            await asyncio.to_thread(self.discord.publish, client_id(self.settings), None)
            self._last_presence_hash = None
        view = PlaybackView(
            source_state=self._source_state,
            account=self._account,
            presence_visible=False,
            stamp=time.monotonic(),
        )
        self._publish_view(view)

    async def _on_new_media(self, media: MediaSnapshot) -> None:
        self._current_media = media
        self._last_media_seen = time.monotonic()
        self._art_path = None
        self._lyrics = None
        self._paused_since = time.monotonic() if media.status == PlaybackStatus.PAUSED else None
        self._publish_view(
            PlaybackView(
                status=media.status,
                position=media.position,
                duration=media.duration,
                source_id=media.source_id,
                source_name=source_label(media.source_id, media.source_name),
                device=media.device,
                source_state=self._source_state,
                account=self._account,
                presence_visible=False,
                stamp=time.monotonic(),
            )
        )
        track = await self.resolver.resolve(media)
        if self._current_media is not media and (
            self._current_media is None or self._current_media.identity != media.identity
        ):
            return
        self._current_track = track
        self._current_key = track.key
        self._schedule_art(track, media)
        self._schedule_lyrics(track, media)
        logger.info("Трек: %s — %s", track.artist, track.title)
        self._wake.set()

    def _update_position(self, media: MediaSnapshot) -> None:
        if self._current_track is not None and not media.duration and self._current_track.duration:
            self._current_media = replace(media, duration=self._current_track.duration)

    async def _publish(self, media: MediaSnapshot) -> None:
        track = self._current_track
        if track is None:
            return
        now = time.monotonic()
        position = media.position
        duration = media.duration or track.duration
        view = PlaybackView(
            track=track,
            status=media.status,
            position=position,
            duration=duration,
            source_id=media.source_id,
            source_name=source_label(media.source_id, media.source_name),
            device=media.device,
            art_path=self._art_path,
            source_state=self._source_state,
            account=self._account,
            lyrics_available=bool(self._lyrics and self._lyrics.available),
            stamp=now,
        )

        activity = None
        if self._presence_allowed(media, now):
            activity = build_activity(view, self.settings, self._lyrics, now_wall=time.time(), now_mono=now)
        view = replace(view, presence_visible=activity is not None)

        self.stats.observe(view)
        self._publish_view(view)
        await self._publish_presence(activity, now)

    def _presence_allowed(self, media: MediaSnapshot, now: float) -> bool:
        if not self.settings.presence_enabled:
            return False
        if media.status == PlaybackStatus.PLAYING:
            return True
        if media.status != PlaybackStatus.PAUSED:
            return False
        if not self.settings.show_paused:
            return False
        if self._paused_since is None:
            self._paused_since = now
        timeout = self.settings.pause_timeout
        if timeout < 0:
            return True
        return now - self._paused_since <= timeout

    async def _publish_presence(self, activity: dict | None, now: float) -> None:
        if activity is not None:
            signature = repr(activity)
            if signature == self._last_presence_hash:
                if not self.discord.connected and now - self._last_presence_at > 5:
                    await asyncio.to_thread(self.discord.publish, client_id(self.settings), activity)
                return
            if now - self._last_presence_at < 3.5 and self._last_presence_hash is not None:
                return
            ok = await asyncio.to_thread(
                self.discord.publish, client_id(self.settings), activity
            )
            self._last_presence_at = now
            if ok:
                self._last_presence_hash = signature
                if not self._last_discord_ok:
                    self.bridge.status_changed.emit(t("status.discord_connected"))
                self._last_discord_ok = True
                self._discord_waiting_notified = False
            elif not self.discord.connected:
                if not self._discord_waiting_notified and (
                    self._last_discord_ok or now - self._started > 5
                ):
                    key = (
                        "status.discord_not_running"
                        if "pipe not found" in self.discord.last_error
                        else "status.discord_waiting"
                    )
                    self.bridge.status_changed.emit(t(key))
                    self._discord_waiting_notified = True
                self._last_discord_ok = False
            return

        if self._last_presence_hash is not None:
            await asyncio.to_thread(self.discord.publish, client_id(self.settings), None)
            self._last_presence_hash = None
            self._last_discord_ok = False

    def _publish_view(self, view: PlaybackView, stale: bool = False) -> None:
        if not stale:
            self._last_view = view
        self.bridge.state_changed.emit(view)
        self._push_overlay(view)

    def _emit_sessions(self, sessions) -> None:
        signature = tuple(
            (item.source_id, item.source_name, item.status.value) for item in sessions
        )
        if signature == self._last_sessions:
            return
        self._last_sessions = signature
        self.bridge.sessions_changed.emit(list(sessions))

    def _push_overlay(self, view: PlaybackView) -> None:
        track = view.track
        position = view.position_at()
        art_url = None
        if view.art_path:
            version = int(os.path.getmtime(view.art_path)) if os.path.exists(view.art_path) else 0
            art_url = f"/api/art?v={version}"
        self.overlay_state.set(
            {
                "has_track": track is not None,
                "status": (
                    "playing"
                    if view.is_playing
                    else "paused"
                    if view.is_paused
                    else "stopped"
                ),
                "title": track.title if track else "",
                "artist": track.artist if track else "",
                "album": track.album if track else "",
                "year": track.year if track else None,
                "position": round(position, 2),
                "duration": round(view.duration or 0, 2),
                "progress": round(position / view.duration, 4) if view.duration else 0,
                "source": view.source_name,
                "device": view.device,
                "url": track.track_url if track else None,
                "cover": track.cover_url if track else None,
                "art_url": art_url,
                "account": self._account,
            },
            art_path=view.art_path,
        )

    # ------------------------------------------------------------------ track data

    def _reset_track(self) -> None:
        self._current_media = None
        self._current_track = None
        self._current_key = None
        self._art_path = None
        self._lyrics = None
        self._paused_since = None

    def _schedule_art(self, track: Track, media: MediaSnapshot) -> None:
        self._spawn(self._load_art(track, media), "art")

    async def _load_art(self, track: Track, media: MediaSnapshot) -> None:
        path = None
        if track.cover_url:
            path = await self.art.from_url(track.cover_url, key=f"{track.key}|{track.cover_url}")
        if path is None and media.source_id != "ynison":
            thumbnail = await self.smtc.thumbnail()
            if thumbnail:
                data, content_type = thumbnail
                path = self.art.save(data, content_type, key=f"{track.key}|smtc")
        if self._current_key != track.key:
            return
        self._art_path = str(path) if path else None
        self._wake.set()

    def _schedule_lyrics(self, track: Track, media: MediaSnapshot | None) -> None:
        self._spawn(self._load_lyrics(track, media), "lyrics")

    async def _load_lyrics(self, track: Track, media: MediaSnapshot | None) -> None:
        duration = (media.duration if media else 0) or track.duration
        try:
            lyrics = await self.lyrics_service.get(track, self.yandex, duration)
        except Exception as error:  # noqa: BLE001
            logger.debug("Текст не загружен: %s", error)
            return
        if self._current_key != track.key:
            return
        self._lyrics = lyrics
        self.bridge.lyrics_changed.emit(lyrics)
        self._wake.set()

    # ------------------------------------------------------------------ helper

    @property
    def account(self) -> str | None:
        return self._account

    def describe(self, view: PlaybackView) -> str:
        if view.track is None:
            return t("tray.no_track")
        return f"{view.track.title} — {view.track.artist}"

    def timecode(self, view: PlaybackView) -> str:
        position = view.position_at()
        return f"{format_duration(position)} / {format_duration(view.duration)}" if view.duration else format_duration(position)

    def data_folder(self) -> str:
        return str(data_dir())
