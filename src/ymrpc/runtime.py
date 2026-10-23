"""Выделенный поток с asyncio-циклом для движка приложения."""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import logging
import threading

from .bridge import Bridge
from .config import ConfigStore
from .engine import Engine

logger = logging.getLogger(__name__)


class EngineRuntime:
    """Владеет asyncio-циклом движка и безопасно принимает задачи из UI."""

    def __init__(self, config: ConfigStore, bridge: Bridge):
        self.config = config
        self.bridge = bridge
        self.engine = Engine(config, bridge)
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, name="ymrpc-engine", daemon=True)
        self._ready = threading.Event()
        self._stopped = threading.Event()
        self._started = False

    # ------------------------------------------------------------------ lifecycle

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._thread.start()
        if not self._ready.wait(timeout=10):
            logger.warning("Движок не сообщил о готовности за 10 секунд")

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.call_soon(self._ready.set)
        try:
            self._loop.run_until_complete(self.engine.run())
        except Exception:  # noqa: BLE001
            logger.exception("Движок завершился с ошибкой")
        finally:
            try:
                self._loop.run_until_complete(self._loop.shutdown_asyncgens())
            except Exception:  # noqa: BLE001
                logger.debug("Ошибка при закрытии async-генераторов", exc_info=True)
            self._loop.close()
            self._stopped.set()
            logger.info("Поток движка остановлен")

    def submit(self, coroutine, callback=None) -> concurrent.futures.Future | None:
        """Ставит корутину в цикл движка. Возвращает future или None при остановке."""
        if self._loop.is_closed() or self._stopped.is_set():
            _close_coroutine(coroutine)
            return None
        try:
            future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
        except RuntimeError:
            _close_coroutine(coroutine)
            return None
        if callback is not None:
            future.add_done_callback(callback)
        return future

    def call(self, function, *args, **kwargs):
        """Выполняет обычную функцию в потоке движка (например, чтение настроек)."""
        if self._loop.is_closed() or self._stopped.is_set():
            return None
        try:
            return asyncio.run_coroutine_threadsafe(
                _call_async(function, *args, **kwargs), self._loop
            )
        except RuntimeError:
            return None

    def stop(self, timeout: float = 10.0) -> None:
        if not self._started or not self._thread.is_alive():
            return
        try:
            asyncio.run_coroutine_threadsafe(self.engine.request_stop(), self._loop).result(timeout=4)
        except (RuntimeError, concurrent.futures.TimeoutError):
            logger.debug("Не удалось попросить движок остановиться", exc_info=True)
        self._thread.join(timeout)
        if self._thread.is_alive():
            logger.warning("Поток движка не завершился за %.0f секунд", timeout)

    @property
    def running(self) -> bool:
        return self._thread.is_alive() and not self._stopped.is_set()

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        return self._loop

    def connect_to_loop(self, signal, slot) -> None:
        """Подключает Qt-сигнал к слоту, который выполнится в потоке цикла."""
        signal.connect(lambda *args: self._loop.call_soon_threadsafe(slot, *args))


async def _call_async(function, *args, **kwargs):
    return function(*args, **kwargs)


def _close_coroutine(coroutine) -> None:
    close = getattr(coroutine, "close", None)
    if close is not None:
        with contextlib.suppress(Exception):
            close()
