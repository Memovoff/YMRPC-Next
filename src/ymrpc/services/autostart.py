"""Автозапуск через HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run."""

from __future__ import annotations

import contextlib
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "YMRPCNext"


def _pythonw() -> str:
    executable = Path(sys.executable)
    candidate = executable.with_name("pythonw.exe")
    return str(candidate if candidate.exists() else executable)


def startup_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --minimized'
    script = Path(sys.argv[0]).resolve()
    if script.name.lower() == "run.py" and script.exists():
        return f'"{_pythonw()}" "{script}" --minimized'
    root = Path(__file__).resolve().parents[2]
    runner = root / "run.py"
    return f'"{_pythonw()}" "{runner}" --minimized'


def enabled() -> bool:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
            return bool(value)
    except FileNotFoundError:
        return False
    except OSError:
        return False


def set_enabled(value: bool) -> bool:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if value:
                winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, startup_command())
            else:
                with contextlib.suppress(FileNotFoundError):
                    winreg.DeleteValue(key, VALUE_NAME)
        logger.info("Автозапуск: %s", "включён" if value else "выключен")
        return True
    except OSError as error:
        logger.warning("Не удалось изменить автозапуск: %s", error)
        return False


def open_data_folder(path: Path) -> None:
    try:
        os.startfile(path)  # noqa: S606
    except OSError as error:
        logger.warning("Не удалось открыть папку: %s", error)
