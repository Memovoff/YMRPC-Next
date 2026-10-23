"""Discord IPC: кадры, переподключение и дедупликация."""

from __future__ import annotations

import json

import pytest

from ymrpc.discord_ipc import (
    OP_FRAME,
    OP_HANDSHAKE,
    DiscordIPC,
    DiscordIPCError,
    DiscordService,
    decode_header,
    encode_frame,
    pipe_paths,
)


def test_encode_frame_layout() -> None:
    frame = encode_frame(OP_HANDSHAKE, {"v": 1, "client_id": "123"})
    opcode, length = decode_header(frame[:8])
    assert opcode == OP_HANDSHAKE
    assert length == len(frame) - 8
    assert json.loads(frame[8:]) == {"v": 1, "client_id": "123"}
    assert frame[8:9] == b"{"  # без пробелов в JSON


def test_encode_empty_payload() -> None:
    frame = encode_frame(OP_FRAME, None)
    assert frame == b"\x01\x00\x00\x00\x00\x00\x00\x00"


def test_decode_header_validates_size() -> None:
    with pytest.raises(DiscordIPCError):
        decode_header(b"\x00")
    assert decode_header(b"\x02\x00\x00\x00\x05\x00\x00\x00") == (2, 5)


def test_pipe_paths() -> None:
    paths = pipe_paths()
    assert len(paths) == 10
    assert paths[0] == r"\\.\pipe\discord-ipc-0"
    assert paths[-1] == r"\\.\pipe\discord-ipc-9"


def test_ipc_without_connection_is_safe() -> None:
    ipc = DiscordIPC("1")
    assert ipc.connected is False
    assert ipc.set_activity({"details": "x"}) is False
    assert ipc.clear() is False
    ipc.close()
    ipc.close()
    assert ipc._file is None
    assert ipc._reader is None


class FakePipe:
    """Мини-эмуляция named pipe с уже готовым ответом Discord."""

    def __init__(self, response: dict) -> None:
        self.data = bytearray(encode_frame(OP_FRAME, response))
        self.writes: list[bytes] = []
        self.closed = False

    def read(self, size: int) -> bytes:
        chunk = bytes(self.data[:size])
        del self.data[:size]
        return chunk

    def write(self, data: bytes) -> int:
        self.writes.append(data)
        return len(data)

    def close(self) -> None:
        self.closed = True


def test_connect_sends_handshake_before_reading(monkeypatch) -> None:
    pipe = FakePipe({"evt": "READY", "data": {"user": {"username": "tester"}}})
    monkeypatch.setattr("builtins.open", lambda *args, **kwargs: pipe)
    monkeypatch.setattr("ymrpc.discord_ipc._available_bytes", lambda file: len(pipe.data))

    ipc = DiscordIPC("123")
    try:
        assert ipc.connect(timeout=1.0) is True
        assert ipc.connected is True
        assert pipe.writes, "handshake не отправлен"
        assert decode_header(pipe.writes[0][:8])[0] == OP_HANDSHAKE
        assert ipc.set_activity({"details": "x"}, timeout=0.05) is True
        assert decode_header(pipe.writes[-1][:8])[0] == OP_FRAME
    finally:
        ipc.close()
    assert pipe.closed is True


class FakeIPC:
    def __init__(self) -> None:
        self.connected = False
        self.calls: list[str] = []
        self.last_error = ""
        self.fail_connect = False
        self.fail_set = False
        self.set_count = 0
        self.clear_count = 0

    def connect(self, timeout: float = 5.0, client_id: str | None = None) -> bool:
        self.calls.append(f"connect:{client_id}")
        if self.fail_connect:
            self.last_error = "pipe not found"
            self.connected = False
            return False
        self.connected = True
        return True

    def set_activity(self, activity, pid=None, timeout: float = 2.0) -> bool:
        self.calls.append("set")
        self.set_count += 1
        if self.fail_set:
            self.last_error = "rejected"
            self.connected = False
            return False
        return True

    def clear(self) -> bool:
        self.calls.append("clear")
        self.clear_count += 1
        return True

    def close(self) -> None:
        self.calls.append("close")
        self.connected = False


def _service(client_id: str = "id") -> tuple[DiscordService, FakeIPC]:
    service = DiscordService(client_id)
    fake = FakeIPC()
    service._ipc = fake
    return service, fake


def test_publish_requires_client_id() -> None:
    service, fake = _service()
    assert service.publish("", {"details": "x"}) is False
    assert fake.calls == []


def test_publish_connects_and_deduplicates() -> None:
    service, fake = _service()
    activity = {"details": "x"}
    assert service.publish("id", activity) is True
    assert service.connected is True
    assert fake.calls == ["connect:id", "set"]

    assert service.publish("id", activity) is True
    assert fake.set_count == 1

    assert service.publish("id", {"details": "y"}) is True
    assert fake.set_count == 2

    assert service.publish("id", activity) is True
    assert fake.set_count == 3


def test_publish_clears_activity() -> None:
    service, fake = _service()
    assert service.publish("id", {"details": "x"}) is True
    assert service.publish("id", None) is True
    assert fake.clear_count == 1

    assert service.publish("id", None) is True
    assert fake.clear_count == 1


def test_publish_none_without_previous_activity_does_not_connect() -> None:
    service, fake = _service()
    assert service.publish("id", None) is True
    assert fake.calls == []


def test_publish_reconnects_after_failed_connection() -> None:
    service, fake = _service()
    fake.fail_connect = True
    assert service.publish("id", {"details": "x"}) is False
    assert service.last_error == "pipe not found"
    attempts = fake.calls.count("connect:id")
    assert attempts == 1

    # Повторная попытка сразу же блокируется backoff-таймером.
    assert service.publish("id", {"details": "x"}) is False
    assert fake.calls.count("connect:id") == attempts

    service._next_attempt = 0.0
    fake.fail_connect = False
    assert service.publish("id", {"details": "x"}) is True
    assert fake.calls.count("connect:id") == attempts + 1


def test_publish_handles_rejected_activity() -> None:
    service, fake = _service()
    fake.fail_set = True
    assert service.publish("id", {"details": "x"}) is False
    assert service.last_error == "rejected"
    assert service.connected is False


def test_client_id_change_resets_connection() -> None:
    service, fake = _service()
    service.publish("one", {"details": "x"})
    assert fake.set_count == 1
    service.publish("two", {"details": "x"})
    assert "close" in fake.calls
    assert fake.calls[-2:] == ["connect:two", "set"]
    assert fake.set_count == 2


def test_reset_forces_next_publish() -> None:
    service, fake = _service()
    assert service.publish("id", {"details": "x"}) is True
    assert service.publish("id", {"details": "x"}) is True
    assert fake.set_count == 1
    service.reset()
    assert service.publish("id", {"details": "x"}) is True
    assert fake.set_count == 2


def test_close_delegates_to_ipc() -> None:
    service, fake = _service()
    service.close()
    assert "close" in fake.calls
