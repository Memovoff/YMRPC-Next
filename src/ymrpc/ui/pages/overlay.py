"""Страница «Оверлей»: сервер для OBS, ссылки и живой предпросмотр."""

from __future__ import annotations

import contextlib
import os
from dataclasses import replace
from urllib.parse import urlencode

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QColorDialog,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ...i18n import t
from ...models import Settings
from ...urls import is_loopback_http_url
from .. import theme
from ..widgets import Card, Field, IconBadge, IconButton, Page, Pill, ToggleRow


class OverlayPage(Page):
    toast_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(t("overlay.title"), t("overlay.subtitle"), parent)
        self._settings = Settings()
        self._running = False
        self._server_url = ""
        self._accent = theme.ACCENT
        self._webview = None
        self._preview_loaded = False
        self._build_settings()
        self._build_links()
        self._build_preview()

        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(500)
        self._preview_timer.timeout.connect(self._reload_preview)

    # ------------------------------------------------------------------ build

    def _build_settings(self) -> None:
        card = Card(padding=18)
        self.enabled_toggle = ToggleRow(
            t("overlay.enabled"), t("overlay.not_local"), card
        )
        card.add(self.enabled_toggle)

        grid = QHBoxLayout()
        grid.setSpacing(12)
        self.port_spin = QSpinBox(card)
        self.port_spin.setRange(1024, 65535)
        self.port_spin.setValue(8765)
        self.port_spin.valueChanged.connect(self._changed)
        grid.addWidget(Field(t("overlay.port"), self.port_spin, card), 1)

        self.theme_combo = QComboBox(card)
        self.theme_combo.addItem(t("overlay.theme_dark"), "dark")
        self.theme_combo.addItem(t("overlay.theme_light"), "light")
        self.theme_combo.currentIndexChanged.connect(self._changed)
        grid.addWidget(Field(t("overlay.theme"), self.theme_combo, card), 1)

        self.accent_button = QPushButton(card)
        self.accent_button.setFixedHeight(38)
        self.accent_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.accent_button.clicked.connect(self._pick_accent)
        grid.addWidget(Field(t("overlay.accent"), self.accent_button, card), 1)
        card.add_layout(grid)

        self.hide_edit = QLineEdit(card)
        self.hide_edit.setPlaceholderText("album, source, progress, time, cover")
        self.hide_edit.textChanged.connect(self._changed)
        card.add(Field(t("overlay.hide"), self.hide_edit, card))
        hint = QLabel(t("overlay.hide_hint"), card)
        hint.setObjectName("tiny")
        card.add(hint)

        status = QHBoxLayout()
        status.setSpacing(8)
        self.status_pill = Pill(t("overlay.stopped"), theme.MUTED, card)
        self.status_label = QLabel("", card)
        self.status_label.setObjectName("muted")
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        self.status_label.setWordWrap(True)
        status.addWidget(self.status_pill)
        status.addWidget(self.status_label, 1)
        card.add_layout(status)

        self.enabled_toggle.switch.toggled.connect(self._changed)
        self.add(card)

    def _build_links(self) -> None:
        card = Card(padding=18)
        header = QHBoxLayout()
        title = QLabel(t("overlay.links"), card)
        title.setObjectName("h2")
        header.addWidget(title)
        header.addStretch(1)
        hint = QLabel(t("overlay.obs_hint"), card)
        hint.setObjectName("tiny")
        hint.setWordWrap(True)
        hint.setMaximumWidth(460)
        header.addWidget(hint)
        card.add_layout(header)

        for label, key, options in (
            (t("overlay.url"), "url", {}),
            (t("overlay.widget_url"), "widget", {"widget": True}),
            (t("overlay.api_url"), "api", {"api": True}),
        ):
            edit, field = self._url_row(card, label, **options)
            setattr(self, f"{key}_edit", edit)
            card.add(field)
        self.add(card)

    def _url_row(self, parent: QWidget, label: str, *, widget: bool = False, api: bool = False):
        row = QHBoxLayout()
        row.setSpacing(6)
        edit = QLineEdit(parent)
        edit.setReadOnly(True)
        edit.setCursorPosition(0)
        row.addWidget(edit, 1)
        copy = IconButton("copy", t("overlay.copy"), parent, size=34, icon_size=16)
        copy.clicked.connect(lambda: self._copy(edit.text()))
        row.addWidget(copy)
        open_button = IconButton("external", t("overlay.open"), parent, size=34, icon_size=16)
        open_button.clicked.connect(lambda: self._open(edit.text()))
        row.addWidget(open_button)
        holder = QWidget(parent)
        holder.setLayout(row)
        row.setContentsMargins(0, 0, 0, 0)
        return edit, Field(label, holder, parent)

    def _build_preview(self) -> None:
        card = Card(padding=18)
        header = QHBoxLayout()
        title = QLabel(t("overlay.preview"), card)
        title.setObjectName("h2")
        header.addWidget(title)
        header.addStretch(1)
        self.preview_button = IconButton("refresh", t("app.refresh"), card, size=32, icon_size=16)
        self.preview_button.clicked.connect(self._reload_preview)
        header.addWidget(self.preview_button)
        card.add_layout(header)

        self.preview_stack = QStackedWidget(card)
        self.preview_stack.setMinimumHeight(196)
        placeholder = QWidget(card)
        placeholder_layout = QVBoxLayout(placeholder)
        placeholder_layout.setContentsMargins(0, 20, 0, 20)
        badge = IconBadge("overlay", theme.MUTED, placeholder, size=44)
        placeholder_layout.addWidget(badge, 0, Qt.AlignmentFlag.AlignHCenter)
        label = QLabel(t("overlay.preview_waiting"), placeholder)
        label.setObjectName("muted")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        placeholder_layout.addWidget(label)
        self.preview_stack.addWidget(placeholder)

        if os.environ.get("YMRPC_NO_WEBENGINE") != "1":
            try:
                from PySide6.QtWebEngineWidgets import QWebEngineView

                view = QWebEngineView(card)
                view.setMinimumHeight(196)
                with contextlib.suppress(Exception):
                    view.page().setBackgroundColor(QColor(0, 0, 0, 0))
                self._webview = view
                self.preview_stack.addWidget(view)
            except Exception:  # noqa: BLE001
                self._webview = None

        card.add(self.preview_stack)
        self.add(card)

    # ------------------------------------------------------------------ state

    def _load(self, settings: Settings) -> None:
        self._settings = settings
        self.enabled_toggle.switch.setChecked(settings.overlay_enabled)
        self.port_spin.setValue(settings.overlay_port)
        index = self.theme_combo.findData(settings.overlay_theme)
        self.theme_combo.setCurrentIndex(max(0, index))
        self._accent = settings.overlay_accent
        self._paint_accent()
        self.hide_edit.setText(settings.overlay_hide)
        self._refresh_urls()

    def set_server(self, running: bool, detail: str) -> None:
        self._running = running
        self._server_url = detail if running else ""
        if running:
            self.status_pill.setText(t("overlay.running", port=self.port_spin.value()))
            self.status_pill.set_color(theme.GREEN)
            self.status_label.setText(detail)
        else:
            self.status_pill.setText(t("overlay.stopped"))
            self.status_pill.set_color(theme.MUTED)
            self.status_label.setText(
                t("overlay.error", error=detail) if detail else t("overlay.stopped")
            )
        self._refresh_urls()
        if self.isVisible() and running:
            self._reload_preview()
        else:
            self._update_preview_stack()

    def _base(self) -> str:
        if self._running and self._server_url:
            return self._server_url.rstrip("/")
        return f"http://127.0.0.1:{self.port_spin.value()}"

    def _query(self, *, compact: bool = False, for_preview: bool = False) -> str:
        params = {
            "theme": self.theme_combo.currentData() or "dark",
            "accent": self._accent,
        }
        hide = self.hide_edit.text().strip()
        if hide:
            params["hide"] = hide
        if compact:
            params["compact"] = "1"
        if for_preview:
            params["idle"] = "show"
        return urlencode(params)

    def _refresh_urls(self) -> None:
        base = self._base()
        self.url_edit.setText(f"{base}/?{self._query()}")
        self.widget_edit.setText(f"{base}/widget?{self._query(compact=True)}")
        self.api_edit.setText(f"{base}/api/now-playing")
        for edit in (self.url_edit, self.widget_edit, self.api_edit):
            edit.setCursorPosition(0)

    def _changed(self) -> None:
        self._refresh_urls()
        self._preview_loaded = False
        self._preview_timer.start()
        if not self._loading:
            self.notify()

    def _reload_preview(self) -> None:
        if self._webview is None:
            self._update_preview_stack()
            return
        if not self._running:
            self._update_preview_stack()
            return
        url = f"{self._base()}/?{self._query(for_preview=True)}&v=1"
        self._webview.load(QUrl(url))
        self._preview_loaded = True
        self._update_preview_stack()

    def _update_preview_stack(self) -> None:
        if self._webview is not None and self._running:
            self.preview_stack.setCurrentWidget(self._webview)
        else:
            self.preview_stack.setCurrentIndex(0)

    def _pick_accent(self) -> None:
        color = QColorDialog.getColor(QColor(self._accent), self, t("overlay.accent"))
        if color.isValid():
            self._accent = color.name()
            self._paint_accent()
            self._changed()

    def _paint_accent(self) -> None:
        color = QColor(self._accent)
        foreground = "#111111" if color.lightness() > 150 else "#ffffff"
        self.accent_button.setText(self._accent.upper())
        self.accent_button.setStyleSheet(
            f"QPushButton {{ background: {self._accent}; color: {foreground};"
            f" border: 1px solid {self._accent}; border-radius: 9px; font-weight: 700; }}"
        )

    def _copy(self, text: str) -> None:
        if not text:
            return
        QApplication.clipboard().setText(text)
        self.toast_requested.emit(t("app.copied"))

    def _open(self, text: str) -> None:
        if text and is_loopback_http_url(text):
            QDesktopServices.openUrl(QUrl(text))

    def apply_to(self, settings: Settings) -> Settings:
        return replace(
            settings,
            overlay_enabled=self.enabled_toggle.switch.isChecked(),
            overlay_port=self.port_spin.value(),
            overlay_theme=self.theme_combo.currentData() or "dark",
            overlay_accent=self._accent,
            overlay_hide=self.hide_edit.text().strip()[:80],
        )

    def on_shown(self) -> None:
        self._refresh_urls()
        if self._running and not self._preview_loaded:
            QTimer.singleShot(150, self._reload_preview)
        else:
            self._update_preview_stack()
