"""Иконка и меню в системном трее."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QSystemTrayIcon, QWidget

from ..i18n import t
from ..models import PlaybackView
from . import icons


class TrayIcon(QSystemTrayIcon):
    open_requested = Signal()
    mini_toggled = Signal(bool)
    lyrics_requested = Signal()
    presence_toggled = Signal(bool)
    overlay_requested = Signal()
    update_requested = Signal()
    exit_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(icons.app_icon(), parent)
        self.setToolTip(t("app.title"))
        self._menu = QMenu()
        self._build_menu()
        self.setContextMenu(self._menu)
        self.activated.connect(self._activated)

    def _build_menu(self) -> None:
        self.now_action = QAction(t("tray.no_track"), self._menu)
        self.now_action.setEnabled(False)
        self._menu.addAction(self.now_action)
        self._menu.addSeparator()

        self.open_action = QAction(icons.icon("overview", "#d8dbe2", 16), t("tray.open"), self._menu)
        self.open_action.triggered.connect(self.open_requested)
        self._menu.addAction(self.open_action)

        self.mini_action = QAction(icons.icon("headphones", "#d8dbe2", 16), t("tray.mini"), self._menu)
        self.mini_action.setCheckable(True)
        self.mini_action.toggled.connect(self.mini_toggled)
        self._menu.addAction(self.mini_action)

        self.lyrics_action = QAction(icons.icon("lyrics", "#d8dbe2", 16), t("tray.lyrics"), self._menu)
        self.lyrics_action.triggered.connect(self.lyrics_requested)
        self._menu.addAction(self.lyrics_action)

        self.presence_action = QAction(icons.icon("eye", "#d8dbe2", 16), t("tray.hide_presence"), self._menu)
        self.presence_action.setCheckable(True)
        self.presence_action.setChecked(True)
        self.presence_action.toggled.connect(self.presence_toggled)
        self._menu.addAction(self.presence_action)

        self.overlay_action = QAction(icons.icon("overlay", "#d8dbe2", 16), t("tray.overlay"), self._menu)
        self.overlay_action.triggered.connect(self.overlay_requested)
        self._menu.addAction(self.overlay_action)

        self._menu.addSeparator()
        self.update_action = QAction(
            icons.icon("refresh", "#d8dbe2", 16), t("tray.check_updates"), self._menu
        )
        self.update_action.triggered.connect(self.update_requested)
        self._menu.addAction(self.update_action)

        self.exit_action = QAction(icons.icon("logout", "#d8dbe2", 16), t("tray.exit"), self._menu)
        self.exit_action.triggered.connect(self.exit_requested)
        self._menu.addAction(self.exit_action)

    def _activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.DoubleClick,
            QSystemTrayIcon.ActivationReason.Trigger,
        ):
            self.open_requested.emit()

    def set_view(self, view: PlaybackView) -> None:
        track = view.track
        if track:
            text = t("tray.now_playing", title=track.title, artist=track.artist)
            if len(text) > 64:
                text = text[:61] + "…"
            self.now_action.setText(text)
            self.setToolTip(f"{t('app.title')}\n{track.title} — {track.artist}")
            self.lyrics_action.setEnabled(view.lyrics_available)
        else:
            self.now_action.setText(t("tray.no_track"))
            self.setToolTip(t("app.title"))
            self.lyrics_action.setEnabled(False)

    def set_presence(self, enabled: bool) -> None:
        self.presence_action.blockSignals(True)
        self.presence_action.setChecked(enabled)
        self.presence_action.setText(t("tray.hide_presence") if enabled else t("tray.show_presence"))
        self.presence_action.setIcon(
            icons.icon("eye" if enabled else "eye_off", "#d8dbe2", 16)
        )
        self.presence_action.blockSignals(False)

    def set_mini(self, visible: bool) -> None:
        self.mini_action.blockSignals(True)
        self.mini_action.setChecked(visible)
        self.mini_action.blockSignals(False)

    def set_update_available(self, version: str | None) -> None:
        self.update_action.setText(
            t("settings.update_available", version=version)
            if version
            else t("tray.check_updates")
        )
