"""Источник Ynison — состояние Яндекс Музыки с других устройств."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import random
import string
import time
from uuid import NAMESPACE_URL, uuid5

import aiohttp

from ..constants import YNISON_REDIRECT_URL, data_dir
from ..models import MediaSnapshot, PlaybackStatus

logger = logging.getLogger(__name__)

DEVICE_TYPE = "WEB"
_YNISON_DOMAIN = "music.yandex.ru"


def _validated_host(value: object) -> str | None:
    """Разрешает только хосты Яндекс Музыки, чтобы не утекал OAuth-токен."""
    if not isinstance(value, str):
        return None
    host = value.strip().lower().rstrip(".")
    if not host or len(host) > 253:
        return None
    if any(char not in "abcdefghijklmnopqrstuvwxyz0123456789.-" for char in host):
        return None
    if host == _YNISON_DOMAIN or host.endswith("." + _YNISON_DOMAIN):
        return host
    return None


class YnisonSource:
    """Опрашивает Ynison по WebSocket и возвращает текущий трек аккаунта."""

    def __init__(self, *, poll_interval: float = 4.0, timeout: float = 8.0):
        self.state = "auth_required"
        self._device_id = uuid5(NAMESPACE_URL, str(data_dir()) + "/ynison-device").hex
        self._token = ""
        self._task: asyncio.Task | None = None
        self._snapshot: MediaSnapshot | None = None
        self._updated = 0.0
        self._next_poll = 0.0
        self._poll_interval = poll_interval
        self._timeout = timeout
        self._last_error = ""

    def reset(self) -> None:
        self._token = ""
        self._snapshot = None
        self._updated = 0.0
        self._next_poll = 0.0
        self.state = "auth_required"

    async def read(self, token: str) -> MediaSnapshot | None:
        if not token:
            self.state = "auth_required"
            self._snapshot = None
            return None
        if token != self._token:
            await self.close()
            self._token = token

        now = time.monotonic()
        if self._task is None and now >= self._next_poll:
            self._task = asyncio.create_task(self._poll(token))

        if self._task is not None and self._task.done():
            try:
                snapshot = self._task.result()
                self._snapshot = snapshot
                self._updated = time.monotonic()
                self.state = "ok" if snapshot else "idle"
                self._next_poll = time.monotonic() + self._poll_interval
                self._last_error = ""
            except Exception as error:  # noqa: BLE001
                name = f"{type(error).__name__}: {error}"
                if name != self._last_error:
                    logger.warning("Ynison недоступен: %s", name)
                    self._last_error = name
                self.state = "unavailable"
                self._next_poll = time.monotonic() + max(10.0, self._poll_interval * 2)
            finally:
                self._task = None

        return self._interpolated()

    def _interpolated(self) -> MediaSnapshot | None:
        snapshot = self._snapshot
        if snapshot is None:
            return None
        if snapshot.status != PlaybackStatus.PLAYING:
            return snapshot
        from dataclasses import replace

        elapsed = max(0.0, time.monotonic() - self._updated)
        position = snapshot.position + elapsed
        if snapshot.duration:
            position = min(position, snapshot.duration)
        return replace(snapshot, position=position)

    async def _poll(self, token: str) -> MediaSnapshot | None:
        device_info = {
            "app_name": "YMRPC Next",
            "type": DEVICE_TYPE,
            "title": "YMRPC Next",
        }
        proto = {
            "Ynison-Device-Id": self._device_id,
            "Ynison-Device-Info": json.dumps(device_info),
        }
        timeout = aiohttp.ClientTimeout(total=self._timeout, connect=5)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.ws_connect(
                YNISON_REDIRECT_URL,
                headers=self._headers(proto, token),
                timeout=aiohttp.ClientWSTimeout(ws_close=2),
            ) as ws:
                message = await asyncio.wait_for(ws.receive(), 5)
                if message.type != aiohttp.WSMsgType.TEXT:
                    raise RuntimeError("Ynison redirector did not return a ticket")
                data = json.loads(message.data)

            if not isinstance(data, dict):
                raise RuntimeError("Ynison redirect response is malformed")
            host = _validated_host(data.get("host"))
            ticket = data.get("redirect_ticket")
            if not host or not isinstance(ticket, str) or not ticket or len(ticket) > 4096:
                raise RuntimeError("Ynison redirect response is malformed")

            state_proto = dict(proto)
            state_proto["Ynison-Redirect-Ticket"] = ticket

            async with session.ws_connect(
                f"wss://{host}/ynison_state.YnisonStateService/PutYnisonState",
                headers=self._headers(state_proto, token),
                method="GET",
                timeout=aiohttp.ClientWSTimeout(ws_close=2),
            ) as ws:
                await ws.send_str(json.dumps(self._state_request()))

                deadline = time.monotonic() + self._timeout
                latest: dict | None = None
                while time.monotonic() < deadline:
                    remaining = max(0.1, deadline - time.monotonic())
                    try:
                        message = await asyncio.wait_for(ws.receive(), remaining)
                    except TimeoutError:
                        break
                    if message.type == aiohttp.WSMsgType.TEXT:
                        try:
                            payload = json.loads(message.data)
                        except ValueError:
                            continue
                        snapshot = self._parse(payload)
                        if snapshot is not None:
                            latest = payload
                            break
                        latest = payload
                    elif message.type in (
                        aiohttp.WSMsgType.CLOSE,
                        aiohttp.WSMsgType.CLOSED,
                        aiohttp.WSMsgType.ERROR,
                    ):
                        break
                return self._parse(latest) if latest else None

    @staticmethod
    def _headers(proto: dict, token: str) -> dict[str, str]:
        return {
            "Sec-WebSocket-Protocol": f"Bearer, v2, {json.dumps(proto)}",
            "Origin": "https://music.yandex.ru",
            "Authorization": f"OAuth {token}",
        }

    def _state_request(self) -> dict:
        version = {
            "device_id": self._device_id,
            "version": int.from_bytes(random.randbytes(8), "big") & 0x7FFFFFFFFFFFFFFF,
            "timestamp_ms": int(time.time() * 1000),
        }
        return {
            "update_full_state": {
                "player_state": {
                    "player_queue": {
                        "current_playable_index": -1,
                        "entity_id": "",
                        "entity_type": "VARIOUS",
                        "playable_list": [],
                        "options": {"repeat_mode": "NONE"},
                        "entity_context": "BASED_ON_ENTITY_BY_DEFAULT",
                        "version": version,
                        "from_optional": "",
                    },
                    "status": {
                        "duration_ms": 0,
                        "paused": True,
                        "playback_speed": 1,
                        "progress_ms": 0,
                        "version": version,
                    },
                },
                "device": {
                    "capabilities": {
                        "can_be_player": True,
                        "can_be_remote_controller": False,
                        "volume_granularity": 16,
                    },
                    "info": {
                        "device_id": self._device_id,
                        "type": DEVICE_TYPE,
                        "title": "YMRPC Next",
                        "app_name": "YMRPC Next",
                    },
                    "volume_info": {"volume": 0},
                    "is_shadow": False,
                },
                "is_currently_active": False,
            },
            "rid": "".join(random.choices(string.hexdigits.lower(), k=32)),
            "player_action_timestamp_ms": 0,
            "activity_interception_type": "DO_NOT_INTERCEPT_BY_DEFAULT",
        }

    def _parse(self, payload: dict) -> MediaSnapshot | None:
        player = payload.get("player_state") or {}
        queue = player.get("player_queue") or {}
        items = queue.get("playable_list") or []
        index = queue.get("current_playable_index", -1)
        if not isinstance(index, int) or index < 0 or index >= len(items):
            return None

        item = items[index] or {}
        status = player.get("status") or {}
        paused = bool(status.get("paused", True))
        progress_ms = _number(status.get("progress_ms"))
        duration_ms = _number(status.get("duration_ms"))
        if not duration_ms:
            duration_ms = _number(item.get("duration_ms"))

        track = item.get("track") if isinstance(item.get("track"), dict) else {}
        title = (item.get("title") or track.get("title") or "").strip()
        artist = _artist(item, track)
        album = (item.get("album") or track.get("album") or "").strip()
        playable_id = item.get("playable_id") or item.get("entity_id")
        if playable_id is not None:
            playable_id = str(playable_id)

        device_name = _active_device(payload, player)
        return MediaSnapshot(
            source_id="ynison",
            source_name="Яндекс Музыка",
            title=title,
            artist=artist,
            album=album,
            position=progress_ms / 1000,
            duration=duration_ms / 1000,
            status=PlaybackStatus.PAUSED if paused else PlaybackStatus.PLAYING,
            device=device_name,
            external_id=playable_id,
        )

    async def close(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(BaseException):
                await self._task
        self._task = None
        self._snapshot = None
        self._updated = 0.0
        self._next_poll = 0.0


def _number(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _artist(item: dict, track: dict) -> str:
    for value in (item.get("artist"), track.get("artist")):
        if isinstance(value, str) and value.strip():
            return value.strip()
    artists = item.get("artists") or track.get("artists") or []
    names = []
    for artist in artists:
        name = artist.get("name") if isinstance(artist, dict) else getattr(artist, "name", None)
        if name:
            names.append(str(name))
    return ", ".join(names)


def _active_device(payload: dict, player: dict) -> str:
    devices = payload.get("devices") or []
    active_id = (
        payload.get("active_device_id_optional")
        or player.get("active_device_id_optional")
        or payload.get("active_device_id")
    )
    for device in devices:
        info = device.get("info") or {}
        if active_id and info.get("device_id") == active_id:
            return str(info.get("title") or info.get("app_name") or "")
    for device in devices:
        if device.get("is_currently_active"):
            info = device.get("info") or {}
            return str(info.get("title") or info.get("app_name") or "")
    return ""
