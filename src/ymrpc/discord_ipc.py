"""Минимальный и надёжный клиент Discord IPC (named pipe)."""

from __future__ import annotations

import contextlib
import json
import logging
import os
import queue
import struct
import sys
import threading
import time
import uuid

logger = logging.getLogger(__name__)

OP_HANDSHAKE = 0
OP_FRAME = 1
OP_CLOSE = 2
OP_PING = 3
OP_PONG = 4
MAX_FRAME = 1024 * 1024
POLL_INTERVAL = 0.025

if sys.platform == "win32":
    import ctypes
    import ctypes.wintypes as wintypes
    import msvcrt

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.PeekNamedPipe.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
    ]
    _kernel32.PeekNamedPipe.restype = wintypes.BOOL
else:  # pragma: no cover - приложение предназначено для Windows
    ctypes = None  # type: ignore[assignment]
    wintypes = None  # type: ignore[assignment]
    msvcrt = None  # type: ignore[assignment]
    _kernel32 = None


def _available_bytes(file) -> int:
    """Количество байт в named pipe без блокирующего ReadFile.

    Возвращает -1, если соединение закрыто. Синхронный named pipe Windows
    не допускает одновременно висящий ReadFile и WriteFile, поэтому читать
    нужно только уже доступные данные.
    """
    if sys.platform != "win32" or _kernel32 is None:
        return -1
    try:
        handle = wintypes.HANDLE(msvcrt.get_osfhandle(file.fileno()))
        available = wintypes.DWORD()
        left = wintypes.DWORD()
        read = wintypes.DWORD()
        ok = _kernel32.PeekNamedPipe(
            handle,
            None,
            0,
            ctypes.byref(read),
            ctypes.byref(available),
            ctypes.byref(left),
        )
    except (OSError, ValueError, OverflowError):
        return -1
    return int(available.value) if ok else -1


class DiscordIPCError(RuntimeError):
    pass


def pipe_paths() -> list[str]:
    return [rf"\\.\pipe\discord-ipc-{index}" for index in range(10)]


def encode_frame(opcode: int, payload: dict | None) -> bytes:
    body = b"" if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return struct.pack("<II", opcode, len(body)) + body


def decode_header(header: bytes) -> tuple[int, int]:
    if len(header) != 8:
        raise DiscordIPCError("short Discord IPC header")
    return struct.unpack("<II", header)


class DiscordIPC:
    def __init__(self, client_id: str):
        self.client_id = client_id
        self._file = None
        self._reader: threading.Thread | None = None
        self._responses: queue.Queue[tuple[int | None, dict | None]] = queue.Queue()
        self._write_lock = threading.Lock()
        self._connected = False
        self._closing = False
        self.last_error = ""

    @property
    def connected(self) -> bool:
        return self._connected and self._file is not None

    def connect(self, timeout: float = 5.0, client_id: str | None = None) -> bool:
        self.close()
        self._closing = False
        self._drain()
        self.last_error = ""
        if client_id:
            self.client_id = client_id

        for path in pipe_paths():
            try:
                self._file = open(path, "r+b", buffering=0)  # noqa: SIM115
                break
            except OSError:
                continue
        if self._file is None:
            self.last_error = "Discord IPC pipe not found"
            logger.debug("Discord IPC: pipe not found")
            return False

        # Сначала отправляем handshake, и только потом запускаем чтение.
        # Иначе синхронный named pipe Windows блокирует запись, пока висит
        # ReadFile, и Discord закрывает соединение по таймауту.
        try:
            self._send(OP_HANDSHAKE, {"v": 1, "client_id": self.client_id})
        except OSError as error:
            self.last_error = str(error)
            self.close()
            return False

        self._reader = threading.Thread(target=self._read_loop, name="discord-ipc", daemon=True)
        self._reader.start()

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            remaining = max(0.05, deadline - time.monotonic())
            try:
                opcode, payload = self._responses.get(timeout=remaining)
            except queue.Empty:
                break
            if opcode is None:
                break
            if opcode == OP_FRAME and isinstance(payload, dict):
                if payload.get("evt") == "READY":
                    self._connected = True
                    logger.info("Discord IPC подключён (user %s)", payload.get("data", {}).get("user", {}).get("username"))
                    return True
                if payload.get("evt") == "ERROR":
                    self.last_error = str(payload.get("data", {}).get("message", "Discord error"))
                    break
            if opcode == OP_CLOSE:
                self.last_error = "Discord closed the IPC connection"
                break
        self.close()
        if not self.last_error:
            self.last_error = "Discord did not answer the handshake"
        return False

    def set_activity(self, activity: dict | None, pid: int | None = None, timeout: float = 2.0) -> bool:
        if not self.connected:
            return False
        nonce = uuid.uuid4().hex
        payload = {
            "cmd": "SET_ACTIVITY",
            "args": {"pid": pid or os.getpid(), "activity": activity},
            "nonce": nonce,
        }
        try:
            self._drain()
            self._send(OP_FRAME, payload)
        except OSError as error:
            self.last_error = str(error)
            self.close()
            return False

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                opcode, response = self._responses.get(timeout=max(0.05, deadline - time.monotonic()))
            except queue.Empty:
                # Некоторые сборки Discord не присылают подтверждение — это нормально.
                return True
            if opcode is None:
                break
            if not isinstance(response, dict):
                continue
            if response.get("nonce") not in (None, nonce):
                continue
            if response.get("evt") == "ERROR":
                self.last_error = str(response.get("data", {}).get("message", "Discord rejected the activity"))
                logger.warning("Discord отклонил активность: %s", self.last_error)
                return False
            return True
        return True

    def clear(self) -> bool:
        return self.set_activity(None)

    def _send(self, opcode: int, payload: dict | None) -> None:
        if self._file is None:
            raise OSError("Discord IPC is not connected")
        frame = encode_frame(opcode, payload)
        with self._write_lock:
            self._file.write(frame)

    def _read_loop(self) -> None:
        buffer = bytearray()
        try:
            while not self._closing and self._file is not None:
                if sys.platform == "win32":
                    available = _available_bytes(self._file)
                    if available < 0:
                        break
                    if available == 0:
                        time.sleep(POLL_INTERVAL)
                        continue
                    chunk = self._file.read(available)
                else:  # pragma: no cover - запасной путь для Unix
                    chunk = self._file.read(65536)
                if not chunk:
                    break
                buffer.extend(chunk)
                while len(buffer) >= 8:
                    opcode, length = decode_header(bytes(buffer[:8]))
                    if length > MAX_FRAME:
                        self.last_error = "Discord IPC frame is too large"
                        return
                    if len(buffer) < 8 + length:
                        break
                    body = bytes(buffer[8 : 8 + length])
                    del buffer[: 8 + length]
                    payload = None
                    if body:
                        try:
                            payload = json.loads(body.decode("utf-8"))
                        except (ValueError, UnicodeDecodeError):
                            continue
                    if opcode == OP_PING:
                        self._send(OP_PONG, payload)
                        continue
                    self._responses.put((opcode, payload))
                    if opcode == OP_CLOSE:
                        self._closing = True
                        break
        except (OSError, ValueError) as error:
            if not self._closing:
                self.last_error = str(error)
        finally:
            self._connected = False
            self._responses.put((None, None))

    def _drain(self) -> None:
        while True:
            try:
                self._responses.get_nowait()
            except queue.Empty:
                return

    def close(self) -> None:
        self._closing = True
        self._connected = False
        file, self._file = self._file, None
        if file is not None:
            # Не отправляем OP_CLOSE: запись может ждать читающий поток.
            # Discord сам освобождает соединение после закрытия handle.
            with contextlib.suppress(OSError, ValueError):
                file.close()
        reader, self._reader = self._reader, None
        if reader is not None and reader.is_alive() and reader is not threading.current_thread():
            reader.join(timeout=1)
        self._responses.put((None, None))


class DiscordService:
    """Переподключение, дедупликация и защита от спама обновлениями."""

    def __init__(self, client_id: str = "", pid: int | None = None):
        self._ipc = DiscordIPC(client_id)
        self._client_id = client_id
        self._pid = pid
        self._last_hash = None
        self._next_attempt = 0.0
        self._connected_once = False
        self._logged_error = ""
        self.last_error = ""

    @property
    def connected(self) -> bool:
        return self._ipc.connected

    def publish(self, client_id: str, activity: dict | None) -> bool:
        if not client_id:
            return False
        if client_id != self._client_id:
            self._ipc.close()
            self._client_id = client_id
            self._last_hash = None
            self._next_attempt = 0.0

        signature = repr(activity)
        if activity is None:
            if self._last_hash is None:
                return True
            if not self._ipc.connected:
                self._last_hash = None
                return True
            try:
                self._ipc.clear()
                self._last_hash = None
                return True
            except Exception as error:  # noqa: BLE001
                self.last_error = str(error)
                self._ipc.close()
                return False

        if signature == self._last_hash and self._ipc.connected:
            return True
        now = time.monotonic()
        if now < self._next_attempt:
            return False
        if not self._ipc.connected:
            if not self._ipc.connect(client_id=client_id):
                self.last_error = self._ipc.last_error
                self._next_attempt = now + 5.0
                self._log_error()
                return False
            self._connected_once = True
        try:
            ok = self._ipc.set_activity(activity, self._pid)
        except Exception as error:  # noqa: BLE001
            self.last_error = str(error)
            self._ipc.close()
            ok = False
        if ok:
            self._last_hash = signature
            self.last_error = ""
            self._logged_error = ""
        else:
            self.last_error = self._ipc.last_error or "Discord update failed"
            self._log_error()
            if not self._ipc.connected:
                self._next_attempt = now + 5.0
        return ok

    def _log_error(self) -> None:
        if self.last_error and self.last_error != self._logged_error:
            logger.info("Discord IPC недоступен: %s", self.last_error)
            self._logged_error = self.last_error

    def reset(self) -> None:
        self._last_hash = None
        self._next_attempt = 0.0

    def close(self) -> None:
        self._ipc.close()
