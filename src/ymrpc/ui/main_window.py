"""Главное окно приложения."""

from __future__ import annotations

import logging
from dataclasses import replace

from PySide6.QtCore import QPoint, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QSystemTrayIcon,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..bridge import Bridge
from ..config import ConfigStore
from ..i18n import t
from ..models import PlaybackView, Settings
from ..runtime import EngineRuntime
from ..services import autostart
from ..services.hotkeys import GlobalHotkeys
from ..urls import is_loopback_http_url
from . import icons, theme
from .auth import AuthDialog
from .lyrics_window import LyricsWindow
from .mini_player import MiniPlayer
from .pages.app import AppPage
from .pages.discord import DiscordPage
from .pages.overlay import OverlayPage
from .pages.overview import OverviewPage
from .pages.sources import SourcesPage
from .pages.stats import StatsPage
from .tray import TrayIcon
from .widgets import Banner

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    restart_requested = Signal()

    def __init__(self, runtime: EngineRuntime, config: ConfigStore, bridge: Bridge):
        super().__init__()
        self.runtime = runtime
        self.engine = runtime.engine
        self.config = config
        self.bridge = bridge
        self.settings: Settings = config.settings
        self._view = PlaybackView()
        self._account: str | None = None
        self._dirty = False
        self._quitting = False
        self._centered = False
        self._mini_user_closed = False
        self._last_autoshow_key: str | None = None
        self._hotkey_errors: list[str] = []
        self._status_text = t("status.ready")

        self.setWindowTitle(t("app.title"))
        self.setWindowIcon(icons.app_icon())
        self.setMinimumSize(1020, 680)
        self.resize(1180, 790)

        self._build()
        self._create_children()
        self._connect()
        self._load_pages()
        self._apply_initial_state()

        QShortcut(QKeySequence.StandardKey.Save, self).activated.connect(self.save)

    # ------------------------------------------------------------------ build

    def _build(self) -> None:
        root = QWidget(self)
        root.setObjectName("root")
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_sidebar())

        content = QWidget(root)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        banner_wrap = QWidget(content)
        banner_layout = QVBoxLayout(banner_wrap)
        banner_layout.setContentsMargins(34, 18, 30, 0)
        self.banner = Banner(banner_wrap)
        self.banner.action_clicked.connect(self._show_update_page)
        banner_layout.addWidget(self.banner)
        content_layout.addWidget(banner_wrap)

        self.stack = QStackedWidget(content)
        content_layout.addWidget(self.stack, 1)
        content_layout.addWidget(self._build_footer())
        layout.addWidget(content, 1)

        self.pages = [
            OverviewPage(self.stack),
            SourcesPage(self.stack),
            DiscordPage(self.stack),
            OverlayPage(self.stack),
            StatsPage(self.stack),
            AppPage(self.stack),
        ]
        self.overview, self.sources_page, self.discord_page, self.overlay_page, self.stats_page, self.app_page = self.pages
        for page in self.pages:
            self.stack.addWidget(page)

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget(self)
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(228)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(16, 20, 16, 16)
        layout.setSpacing(4)

        logo_row = QHBoxLayout()
        logo_row.setSpacing(10)
        logo = QLabel(sidebar)
        logo.setPixmap(icons.logo_pixmap(38))
        logo_row.addWidget(logo)
        names = QVBoxLayout()
        names.setSpacing(0)
        name = QLabel("YMRPC", sidebar)
        name.setStyleSheet("font-size: 17px; font-weight: 800; letter-spacing: 0.5px;")
        names.addWidget(name)
        next_label = QLabel("NEXT", sidebar)
        next_label.setStyleSheet(
            f"color: {theme.ACCENT}; font-size: 9px; font-weight: 700; letter-spacing: 3px;"
        )
        names.addWidget(next_label)
        logo_row.addLayout(names)
        logo_row.addStretch(1)
        layout.addLayout(logo_row)
        layout.addSpacing(22)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons: list[QToolButton] = []
        entries = (
            (t("nav.overview"), "overview"),
            (t("nav.sources"), "sources"),
            (t("nav.discord"), "discord"),
            (t("nav.overlay"), "overlay"),
            (t("nav.stats"), "stats"),
            (t("nav.app"), "app"),
        )
        for index, (label, icon_name) in enumerate(entries):
            button = QToolButton(sidebar)
            button.setObjectName("navButton")
            button.setText("  " + label)
            button.setIcon(icons.nav_icon(icon_name, 19))
            button.setIconSize(QSize(19, 19))
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            button.setCheckable(True)
            button.setFixedHeight(42)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, i=index: self._go(i))
            self.nav_group.addButton(button, index)
            self.nav_buttons.append(button)
            layout.addWidget(button)
            if index == 2:
                layout.addSpacing(2)
        layout.addStretch(1)

        status_card = QFrame(sidebar)
        status_card.setObjectName("soft")
        status_layout = QVBoxLayout(status_card)
        status_layout.setContentsMargins(12, 10, 12, 10)
        status_layout.setSpacing(3)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.sidebar_dot = QLabel("●", status_card)
        self.sidebar_dot.setStyleSheet(f"color: {theme.MUTED}; font-size: 9px;")
        row.addWidget(self.sidebar_dot)
        discord_label = QLabel("Discord", status_card)
        discord_label.setStyleSheet("font-size: 11px; font-weight: 700;")
        row.addWidget(discord_label)
        row.addStretch(1)
        status_layout.addLayout(row)
        self.sidebar_presence = QLabel(t("status.ready"), status_card)
        self.sidebar_presence.setObjectName("tiny")
        self.sidebar_presence.setTextFormat(Qt.TextFormat.PlainText)
        self.sidebar_presence.setWordWrap(True)
        status_layout.addWidget(self.sidebar_presence)
        self.sidebar_account = QLabel(t("settings.not_logged"), status_card)
        self.sidebar_account.setObjectName("tiny")
        self.sidebar_account.setTextFormat(Qt.TextFormat.PlainText)
        self.sidebar_account.setWordWrap(True)
        status_layout.addWidget(self.sidebar_account)
        layout.addWidget(status_card)
        layout.addSpacing(8)

        version = QLabel(t("app.version", version=__version__), sidebar)
        version.setObjectName("tiny")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(version)
        return sidebar

    def _build_footer(self) -> QWidget:
        footer = QFrame(self)
        footer.setObjectName("footer")
        footer.setFixedHeight(60)
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(34, 0, 30, 0)
        layout.setSpacing(8)
        self.footer_dot = QLabel("●", footer)
        self.footer_dot.setStyleSheet(f"color: {theme.MUTED}; font-size: 9px;")
        layout.addWidget(self.footer_dot)
        self.footer_status = QLabel(self._status_text, footer)
        self.footer_status.setObjectName("muted")
        self.footer_status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.footer_status)
        layout.addStretch(1)
        self.dirty_label = QLabel(t("settings.unsaved"), footer)
        self.dirty_label.setStyleSheet(f"color: {theme.ORANGE}; font-size: 11px;")
        self.dirty_label.setVisible(False)
        layout.addWidget(self.dirty_label)
        self.revert_button = QPushButton(t("app.cancel"), footer)
        self.revert_button.setObjectName("ghost")
        self.revert_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.revert_button.setVisible(False)
        self.revert_button.clicked.connect(self._revert)
        layout.addWidget(self.revert_button)
        self.save_button = QPushButton(t("app.save"), footer)
        self.save_button.setObjectName("primary")
        self.save_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self.save)
        layout.addWidget(self.save_button)
        return footer

    def _create_children(self) -> None:
        self.mini = MiniPlayer()
        self.lyrics = LyricsWindow()
        self.auth = AuthDialog(self)
        self.tray: TrayIcon | None = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = TrayIcon(self)
            self.tray.show()
        self.hotkeys = GlobalHotkeys()
        app = QApplication.instance()
        if app is not None:
            app.installNativeEventFilter(self.hotkeys)

    # ------------------------------------------------------------------ wiring

    def _connect(self) -> None:
        for page in self.pages:
            page.changed.connect(self._mark_dirty)
        self.overview.control_requested.connect(self._control)
        self.overview.seek_requested.connect(self._seek)
        self.overview.mini_requested.connect(self._mini_from_button)
        self.overview.lyrics_requested.connect(self._show_lyrics)
        self.overview.presence_requested.connect(self._presence_from_button)
        self.overview.login_requested.connect(self._show_login)
        self.overview.logout_requested.connect(self._logout)
        self.overview.overlay_requested.connect(self._open_overlay)
        self.overlay_page.toast_requested.connect(self.toast)
        self.stats_page.toast_requested.connect(self.toast)
        self.app_page.toast_requested.connect(self.toast)
        self.app_page.login_requested.connect(self._show_login)
        self.app_page.logout_requested.connect(self._logout)
        self.app_page.check_updates_requested.connect(lambda: self._check_updates(True))
        self.app_page.install_update_requested.connect(self._install_update)

        self.mini.control_requested.connect(self._control)
        self.mini.seek_requested.connect(self._seek)
        self.mini.lyrics_requested.connect(self._show_lyrics)
        self.mini.open_requested.connect(self.show_main)
        self.mini.closed_by_user.connect(self._mini_closed)
        self.mini.moved.connect(self._mini_moved)

        self.lyrics.reload_requested.connect(self._reload_lyrics)
        self.lyrics.offset_changed.connect(self._lyrics_offset_changed)

        self.auth.login_requested.connect(self._login)

        if self.tray is not None:
            self.tray.open_requested.connect(self.show_main)
            self.tray.mini_toggled.connect(self._set_mini)
            self.tray.lyrics_requested.connect(self._show_lyrics)
            self.tray.presence_toggled.connect(self._set_presence)
            self.tray.overlay_requested.connect(self._open_overlay)
            self.tray.update_requested.connect(self._show_update_page)
            self.tray.exit_requested.connect(self.request_quit)
        self.hotkeys.activated.connect(self._hotkey)
        self.hotkeys.failed.connect(self._hotkey_failed)

        self.bridge.state_changed.connect(self._on_state)
        self.bridge.lyrics_changed.connect(self.lyrics.set_lyrics)
        self.bridge.sessions_changed.connect(self.sources_page.set_sessions)
        self.bridge.account_changed.connect(self._on_account)
        self.bridge.login_result.connect(self._on_login_result)
        self.bridge.status_changed.connect(self._on_status)
        self.bridge.overlay_changed.connect(self._on_overlay)
        self.bridge.update_checked.connect(self._on_update_checked)
        self.bridge.update_progress.connect(self.app_page.set_progress)
        self.bridge.update_ready.connect(self._on_update_ready)
        self.bridge.quit_requested.connect(self.request_quit)

        self._mini_pos_timer = QTimer(self)
        self._mini_pos_timer.setSingleShot(True)
        self._mini_pos_timer.setInterval(700)
        self._mini_pos_timer.timeout.connect(self._save_mini_position)

        self._offset_timer = QTimer(self)
        self._offset_timer.setSingleShot(True)
        self._offset_timer.setInterval(600)
        self._offset_timer.timeout.connect(self._save_lyrics_offset)

    # ------------------------------------------------------------------ initial

    def _apply_initial_state(self) -> None:
        self.stats_page.set_stats_path(self.engine.stats.path)
        overlay = self.engine.overlay
        self.overlay_page.set_server(overlay.running, overlay.url if overlay.running else overlay.error)
        self.overview.set_overlay(overlay.running, overlay.url if overlay.running else overlay.error)
        self.overview.set_account(None)
        self.app_page.set_account(None)
        self.lyrics.set_offset(self.settings.lyrics_offset)
        self._refresh_status_dot()
        self.sidebar_account.setText(t("settings.not_logged"))
        self.sources_page.set_sessions(self.engine.smtc.last_infos)
        account = self.engine.account
        if account:
            self._on_account(account)
        self._apply_autostart(initial=True)
        if self.settings.hotkeys_enabled:
            QTimer.singleShot(0, self._register_hotkeys)
        if self.settings.mini_player_visible:
            QTimer.singleShot(120, lambda: self._set_mini(True, persist=False))
        self._go(0)
        if self.tray is not None:
            self.tray.set_presence(self.settings.presence_enabled)
            self.tray.set_mini(self.settings.mini_player_visible)

    def _load_pages(self) -> None:
        for page in self.pages:
            page.load(self.settings)
        self.overview.update_settings(self.settings)
        self.lyrics.set_offset(self.settings.lyrics_offset)
        if self.tray is not None:
            self.tray.set_presence(self.settings.presence_enabled)
        self._refresh_status_dot()

    # ------------------------------------------------------------------ navigation

    def _go(self, index: int) -> None:
        if not 0 <= index < len(self.pages):
            return
        self.stack.setCurrentIndex(index)
        self.nav_buttons[index].setChecked(True)
        page = self.pages[index]
        page.on_shown()

    def _show_update_page(self) -> None:
        self._go(5)
        if self.banner.isVisible():
            self.banner.setVisible(False)

    def show_main(self) -> None:
        self.show()
        if self.isMinimized():
            self.showNormal()
        self.raise_()
        self.activateWindow()

    # ------------------------------------------------------------------ bridge

    def _on_state(self, view: PlaybackView) -> None:
        previous_key = self._view.track.key if self._view.track else None
        new_key = view.track.key if view.track else None
        self._view = view
        self.overview.update_view(view)
        self.sources_page.update_view(view)
        self.mini.set_view(view)
        self.lyrics.set_view(view)
        if self.tray is not None:
            self.tray.set_view(view)
        self.stats_page.update_view(view)
        self._refresh_status_dot()
        if new_key:
            self.setWindowTitle(f"{t('app.title')} — {view.track.title}")
        else:
            self.setWindowTitle(t("app.title"))
        if new_key != previous_key:
            self._mini_user_closed = False
        if (
            self.settings.mini_player_autoshow
            and view.is_playing
            and new_key
            and new_key != self._last_autoshow_key
            and not self._mini_user_closed
        ):
            self._last_autoshow_key = new_key
            self._set_mini(True)

    def _on_account(self, name: str | None) -> None:
        self._account = name
        self.overview.set_account(name)
        self.app_page.set_account(name)
        self.sidebar_account.setText(
            t("settings.logged_in", name=name) if name else t("settings.not_logged")
        )

    def _on_login_result(self, ok: bool, detail: str) -> None:
        if self.auth.isVisible():
            self.auth.finish(ok, detail)
        if ok:
            self.toast(t("auth.success", name=detail))
        elif not self.auth.isVisible():
            self.toast(t("auth.error", error=detail), error=True)

    def _on_status(self, text: str) -> None:
        self._status_text = text
        self.footer_status.setText(text)
        if self._view.has_track:
            self.sidebar_presence.setText(text)

    def _on_overlay(self, running: bool, detail: str) -> None:
        self.overlay_page.set_server(running, detail)
        self.overview.set_overlay(running, detail if running else detail)
        if running:
            self.footer_status.setText(t("status.overlay_ready", url=detail))
        elif detail:
            self.footer_status.setText(t("overlay.error", error=detail))

    def _on_update_checked(self, info) -> None:
        self.app_page.check_finished(info)
        if info is not None:
            self.banner.show_banner(
                t("settings.update_available", version=info.version),
                (info.notes or "").strip().splitlines()[0][:140] if info.notes.strip() else t("settings.updates"),
                t("app.open"),
            )
            if self.tray is not None:
                self.tray.set_update_available(info.version)
            self.toast(t("toast.update_available", version=info.version))
        elif self.tray is not None:
            self.tray.set_update_available(None)

    def _on_update_ready(self, ok: bool, detail: str) -> None:
        self.app_page.set_update_ready(ok, detail)

    # ------------------------------------------------------------------ actions

    def _control(self, action: str, position: float | None = None) -> None:
        self.runtime.submit(self.engine.control(action, position))

    def _seek(self, position: float) -> None:
        self.runtime.submit(self.engine.control("seek", position))

    def _show_lyrics(self) -> None:
        self.lyrics.set_offset(self.settings.lyrics_offset)
        self.lyrics.present()

    def _reload_lyrics(self) -> None:
        self.runtime.submit(self.engine.reload_lyrics())

    def _lyrics_offset_changed(self, value: float) -> None:
        self._pending_offset = value
        self._offset_timer.start()

    def _save_lyrics_offset(self) -> None:
        value = getattr(self, "_pending_offset", self.settings.lyrics_offset)
        if abs(value - self.settings.lyrics_offset) < 0.01:
            return
        self.settings = replace(self.settings, lyrics_offset=value)
        self.runtime.submit(self.engine.update_settings(self.settings))
        self.discord_page.offset_spin.blockSignals(True)
        self.discord_page.offset_spin.setValue(value)
        self.discord_page.offset_spin.blockSignals(False)

    def _toggle_visibility(self) -> None:
        self._set_presence(not self.settings.presence_enabled)

    def _set_presence(self, enabled: bool) -> None:
        if enabled == self.settings.presence_enabled:
            self.overview.update_settings(self.settings)
            if self.tray is not None:
                self.tray.set_presence(self.settings.presence_enabled)
            return
        self._commit(replace(self.settings, presence_enabled=enabled))

    def _presence_from_button(self) -> None:
        self._set_presence(self.overview.presence_button.isChecked())

    def _mini_from_button(self) -> None:
        self._set_mini(self.overview.mini_button.isChecked())

    def _set_mini(self, visible: bool, *, persist: bool = True) -> None:
        if visible:
            position = QPoint(*self.settings.mini_player_pos)
            self.mini.show_player(position)
        else:
            self.mini.hide()
        self.overview.set_mini_visible(visible)
        if self.tray is not None:
            self.tray.set_mini(visible)
        if persist and visible != self.settings.mini_player_visible:
            self.settings = replace(self.settings, mini_player_visible=visible)
            self.runtime.submit(self.engine.update_settings(self.settings))

    def _mini_closed(self) -> None:
        self._mini_user_closed = True
        self._set_mini(False)

    def _mini_moved(self, position: QPoint) -> None:
        if position == QPoint(*self.settings.mini_player_pos):
            return
        self.settings = replace(self.settings, mini_player_pos=(position.x(), position.y()))
        self._mini_pos_timer.start()

    def _save_mini_position(self) -> None:
        self.runtime.submit(self.engine.update_settings(self.settings))

    def _open_overlay(self) -> None:
        url = self.overlay_page.url_edit.text()
        if url and is_loopback_http_url(url):
            QDesktopServices.openUrl(QUrl(url))

    def _show_login(self) -> None:
        self.auth.adjustSize()
        center = self.frameGeometry().center()
        self.auth.move(center - self.auth.rect().center())
        self.auth.start()

    def _login(self, token: str) -> None:
        self.runtime.submit(self.engine.login(token))

    def _logout(self) -> None:
        self.runtime.submit(self.engine.logout())
        self.toast(t("settings.not_logged"))

    def _check_updates(self, manual: bool = True) -> None:
        if manual:
            self.app_page.set_checking(True)
        self.runtime.submit(self.engine.check_updates(manual))

    def _install_update(self) -> None:
        info = self.app_page.pending_update()
        if info is not None:
            self.runtime.submit(self.engine.install_update(info))

    # ------------------------------------------------------------------ hotkeys

    def _register_hotkeys(self) -> None:
        self._hotkey_errors = []
        errors = self.hotkeys.register()
        if errors:
            self._hotkey_errors = errors
            QTimer.singleShot(
                1200,
                lambda: self.toast(
                    t("settings.hotkeys_busy", keys=", ".join(self._hotkey_errors)),
                    error=True,
                ),
            )

    def _hotkey_failed(self, action: str) -> None:
        logger.info("Горячая клавиша занята: %s", action)

    def _hotkey(self, action: str) -> None:
        if action == "toggle_player":
            self._set_mini(not self.mini.isVisible())
        elif action == "lyrics":
            self._show_lyrics()
        elif action == "play_pause":
            self._control("toggle")
        elif action == "next":
            self._control("next")
        elif action == "previous":
            self._control("previous")
        elif action == "presence":
            self._toggle_visibility()

    # ------------------------------------------------------------------ settings

    def _mark_dirty(self) -> None:
        self._dirty = True
        self.save_button.setEnabled(True)
        self.revert_button.setVisible(True)
        self.dirty_label.setVisible(True)

    def _set_dirty(self, dirty: bool) -> None:
        self._dirty = dirty
        self.save_button.setEnabled(dirty)
        self.revert_button.setVisible(dirty)
        self.dirty_label.setVisible(dirty)

    def _revert(self) -> None:
        self._load_pages()
        self._set_dirty(False)

    def _collect(self) -> Settings:
        settings = self.settings
        for page in self.pages:
            settings = page.apply_to(settings)
        return settings

    def save(self) -> bool:
        errors = [error for page in self.pages if (error := page.validate())]
        if errors:
            self.toast(errors[0], error=True)
            self.footer_status.setText(errors[0])
            return False
        previous = self.settings
        settings = self._collect()
        self.settings = settings
        self.runtime.submit(self.engine.update_settings(settings))
        self._apply_side_effects(previous, settings)
        self._load_pages()
        self._set_dirty(False)
        self.toast(t("app.saved"))
        if previous.ui_language != settings.ui_language:
            QTimer.singleShot(250, self._prompt_restart)
        return True

    def _commit(self, settings: Settings) -> None:
        previous = self.settings
        self.settings = settings
        self.runtime.submit(self.engine.update_settings(settings))
        self._apply_side_effects(previous, settings)
        self._load_pages()
        self._set_dirty(False)

    def _apply_side_effects(self, previous: Settings, settings: Settings) -> None:
        if settings.autostart != previous.autostart and not autostart.set_enabled(
            settings.autostart
        ):
            self.toast(t("settings.autostart_failed"), error=True)
        if settings.hotkeys_enabled != previous.hotkeys_enabled:
            if settings.hotkeys_enabled:
                self._register_hotkeys()
            else:
                self.hotkeys.unregister()
        if settings.capture_mode != previous.capture_mode:
            self._last_autoshow_key = None
        self.overview.update_settings(settings)
        if self.tray is not None:
            self.tray.set_presence(settings.presence_enabled)
        self._refresh_status_dot()

    def _apply_autostart(self, initial: bool = False) -> None:
        current = autostart.enabled()
        if current != self.settings.autostart and not autostart.set_enabled(
            self.settings.autostart
        ):
            QTimer.singleShot(
                1200, lambda: self.toast(t("settings.autostart_failed"), error=True)
            )

    def _prompt_restart(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle(t("app.restart_required"))
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(t("app.restart_message"))
        restart = box.addButton(t("app.restart"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(t("app.later"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is restart:
            self.restart_requested.emit()

    def _refresh_status_dot(self) -> None:
        if not self.settings.presence_enabled:
            color = theme.MUTED
            text = t("overview.presence_off")
        elif self._view.presence_visible:
            color = theme.GREEN
            text = t("overview.presence_on")
        elif self._view.has_track:
            color = theme.ORANGE
            text = t("status.discord_waiting")
        else:
            color = theme.MUTED
            text = t("status.ready")
        self.footer_dot.setStyleSheet(f"color: {color}; font-size: 9px;")
        self.sidebar_dot.setStyleSheet(f"color: {color}; font-size: 9px;")
        if not self._view.has_track:
            self.sidebar_presence.setText(text)

    # ------------------------------------------------------------------ toast

    def toast(self, message: str, error: bool = False) -> None:
        if not hasattr(self, "_toast"):
            self._toast = QLabel(self)
            self._toast.setWordWrap(True)
            self._toast.setTextFormat(Qt.TextFormat.PlainText)
            self._toast.setMaximumWidth(560)
            self._toast.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._toast.hide()
            self._toast_timer = QTimer(self)
            self._toast_timer.setSingleShot(True)
            self._toast_timer.setInterval(3200)
            self._toast_timer.timeout.connect(self._toast.hide)
        background = "#3a2024" if error else theme.SURFACE_3
        border = "rgba(255,107,107,.45)" if error else theme.BORDER
        color = theme.RED if error else theme.TEXT
        self._toast.setStyleSheet(
            f"background: {background}; color: {color}; border: 1px solid {border};"
            "border-radius: 10px; padding: 9px 16px; font-weight: 600;"
        )
        self._toast.setText(message)
        self._toast.adjustSize()
        self._position_toast()
        self._toast.show()
        self._toast.raise_()
        self._toast_timer.start()

    def _position_toast(self) -> None:
        if not hasattr(self, "_toast") or not self._toast.isVisible():
            return
        x = max(16, (self.width() - self._toast.width()) // 2)
        y = max(16, self.height() - 60 - self._toast.height() - 18)
        self._toast.move(x, y)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._position_toast()

    # ------------------------------------------------------------------ quit

    def request_quit(self) -> None:
        if self._dirty and not self.save():
            return
        self._quitting = True
        if self.tray is not None:
            self.tray.hide()
        self.mini.close()
        self.lyrics.close()
        QApplication.quit()

    def shutdown(self) -> None:
        self._quitting = True
        self.hotkeys.unregister()
        if self.tray is not None:
            self.tray.hide()
        self.runtime.stop(8)

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._quitting or self.tray is None:
            self._quitting = True
            self.runtime.stop(8)
            event.accept()
            return
        event.ignore()
        self.hide()
        self.tray.showMessage(
            t("app.title"),
            t("tray.minimized_hint"),
            QSystemTrayIcon.MessageIcon.Information,
            2500,
        )

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._centered:
            self._centered = True
            screen = self.screen()
            if screen is not None:
                area = screen.availableGeometry()
                self.move(
                    area.center().x() - self.width() // 2,
                    area.center().y() - self.height() // 2,
                )
        theme.apply_dark_title_bar(self)
