"""Потокобезопасный мост между asyncio-движком и Qt-интерфейсом."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class Bridge(QObject):
    state_changed = Signal(object)        # PlaybackView
    lyrics_changed = Signal(object)       # Lyrics
    sessions_changed = Signal(object)     # list[SessionInfo]
    account_changed = Signal(object)      # str | None
    login_result = Signal(bool, str)
    status_changed = Signal(str)
    overlay_changed = Signal(bool, str)   # running, url/error
    update_checked = Signal(object)       # UpdateInfo | None
    update_progress = Signal(object)      # UpdateProgress
    update_ready = Signal(bool, str)
    quit_requested = Signal()
