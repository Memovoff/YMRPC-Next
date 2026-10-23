"""Точка входа приложения: QApplication, single instance и перезапуск."""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QIODevice
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from . import __version__
from .bridge import Bridge
from .config import ConfigStore
from .constants import APP_ID, APP_NAME
from .i18n import set_language
from .log import configure_logging
from .runtime import EngineRuntime
from .ui import icons, theme
from .ui.main_window import MainWindow

logger = logging.getLogger(__name__)

SINGLE_INSTANCE_NAME = "ymrpc-next-single-instance-4f6c1c7a"


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="ymrpc", description=APP_NAME)
    parser.add_argument("--minimized", action="store_true", help="запустить свёрнутым в трей")
    parser.add_argument("--version", action="store_true", help="показать версию и выйти")
    return parser.parse_args(argv)


def _set_app_user_model_id() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:  # noqa: BLE001
        logger.debug("Не удалось задать AppUserModelID", exc_info=True)


class SingleInstance:
    """Локальный сервер, который не даёт запустить две копии приложения."""

    def __init__(self, on_activate):
        self._on_activate = on_activate
        self._server: QLocalServer | None = None
        self._connections: set[QLocalSocket] = set()

    def acquire(self) -> bool:
        probe = QLocalSocket()
        probe.connectToServer(SINGLE_INSTANCE_NAME, QIODevice.OpenModeFlag.WriteOnly)
        if probe.waitForConnected(250):
            probe.write(b"show")
            probe.flush()
            probe.waitForBytesWritten(250)
            probe.disconnectFromServer()
            logger.info("Приложение уже запущено, показываю существующее окно")
            return False

        QLocalServer.removeServer(SINGLE_INSTANCE_NAME)
        server = QLocalServer()
        server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        server.newConnection.connect(self._accept)
        if not server.listen(SINGLE_INSTANCE_NAME):
            logger.warning(
                "Не удалось создать single-instance сервер: %s", server.errorString()
            )
            return True
        self._server = server
        return True

    def _accept(self) -> None:
        if self._server is None:
            return
        while self._server.hasPendingConnections():
            connection = self._server.nextPendingConnection()
            if connection is None:
                break
            self._connections.add(connection)
            connection.disconnected.connect(lambda item=connection: self._drop(item))
            connection.readyRead.connect(lambda item=connection: self._read(item))
            self._on_activate()

    def _read(self, connection: QLocalSocket) -> None:
        # Клиент присылает "show", но показывать окно нужно в любом случае.
        connection.readAll()

    def _drop(self, connection: QLocalSocket) -> None:
        self._connections.discard(connection)
        connection.deleteLater()

    def close(self) -> None:
        for connection in list(self._connections):
            connection.abort()
        self._connections.clear()
        if self._server is not None:
            self._server.close()
            self._server = None
        QLocalServer.removeServer(SINGLE_INSTANCE_NAME)


def _launch_command() -> list[str]:
    """Команда для повторного запуска приложения (в том числе после смены языка)."""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    root = Path(__file__).resolve().parents[2]
    runner = root / "run.py"
    if runner.exists():
        executable = Path(sys.executable)
        if sys.platform == "win32":
            windowless = executable.with_name("pythonw.exe")
            if windowless.exists():
                executable = windowless
        return [str(executable), str(runner)]
    return [sys.executable, "-m", "ymrpc"]


def _relaunch() -> None:
    command = _launch_command()
    try:
        creationflags = 0
        if sys.platform == "win32":
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        subprocess.Popen(  # noqa: S603
            command,
            cwd=os.getcwd(),
            close_fds=True,
            creationflags=creationflags,
        )
        logger.info("Приложение перезапущено: %s", " ".join(command))
    except OSError:
        logger.exception("Не удалось перезапустить приложение")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(list(sys.argv[1:] if argv is None else argv))
    if args.version:
        print(f"{APP_NAME} {__version__}")
        return 0

    log_path = configure_logging()
    logger.info("%s %s запускается, лог: %s", APP_NAME, __version__, log_path)
    _set_app_user_model_id()

    application = QApplication([sys.argv[0]])
    application.setApplicationName(APP_NAME)
    application.setApplicationDisplayName(APP_NAME)
    application.setOrganizationName("YMRPC")
    application.setApplicationVersion(__version__)
    application.setWindowIcon(icons.app_icon())
    theme.apply(application)

    config = ConfigStore()
    set_language(config.settings.ui_language)

    bridge = Bridge()
    runtime = EngineRuntime(config, bridge)
    holder: dict[str, MainWindow | None] = {"window": None}

    def activate() -> None:
        window = holder["window"]
        if window is not None:
            window.show_main()

    instance = SingleInstance(activate)
    if not instance.acquire():
        # Второй экземпляр: существующее окно уже показано, выходим без запуска движка.
        return 0

    window = MainWindow(runtime, config, bridge)
    holder["window"] = window
    reloaded = {"requested": False}

    def request_reload() -> None:
        reloaded["requested"] = True
        application.quit()

    window.restart_requested.connect(request_reload)
    application.aboutToQuit.connect(window.shutdown)

    application.setQuitOnLastWindowClosed(window.tray is None)

    runtime.start()
    if args.minimized and window.tray is not None:
        window.hide()
        window.tray.showMessage(
            APP_NAME,
            "Приложение запущено в фоне и доступно в трее.",
            QSystemTrayIcon.MessageIcon.Information,
            2500,
        )
    else:
        window.show()

    try:
        code = application.exec()
    finally:
        instance.close()
        if reloaded["requested"]:
            _relaunch()
    logger.info("%s завершил работу", APP_NAME)
    return int(code)
