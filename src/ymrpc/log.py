"""Логирование в файл с ротацией."""

from __future__ import annotations

import logging
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .constants import log_dir


def configure_logging(level: int = logging.INFO, logfile: Path | None = None) -> Path:
    path = logfile or (log_dir() / "app.log")
    path.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler = RotatingFileHandler(
        path, maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    if sys.stderr is not None:
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(formatter)
        root.addHandler(console)

    def _hook(exc_type, value, traceback):
        logging.getLogger("ymrpc").critical(
            "Необработанное исключение", exc_info=(exc_type, value, traceback)
        )

    def _thread_hook(args):
        logging.getLogger("ymrpc").critical(
            "Исключение в потоке %s",
            getattr(args.thread, "name", "?"),
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = _hook
    threading.excepthook = _thread_hook
    return path
