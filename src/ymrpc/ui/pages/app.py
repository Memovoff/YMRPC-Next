"""Страница «Приложение»: аккаунт, язык, автозапуск, обновления и данные."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ... import __version__
from ...config import REPO_RE
from ...constants import data_dir, log_dir
from ...i18n import LANGUAGES, current_language, t
from ...models import Settings, UpdateInfo, UpdateProgress
from ...services.autostart import open_data_folder
from ...urls import is_https_url
from .. import icons, theme
from ..widgets import Card, IconBadge, Page, ToggleRow


class AppPage(Page):
    login_requested = Signal()
    logout_requested = Signal()
    check_updates_requested = Signal()
    install_update_requested = Signal()
    toast_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(t("settings.title"), t("settings.subtitle"), parent)
        self._settings = Settings()
        self._account: str | None = None
        self._update: UpdateInfo | None = None
        self._build_account()
        self._build_language()
        self._build_behavior()
        self._build_updates()
        self._build_data()

    # ------------------------------------------------------------------ build

    def _build_account(self) -> None:
        card = Card(padding=16)
        row = QHBoxLayout()
        row.setSpacing(12)
        self.account_badge = IconBadge("login", theme.ACCENT, card, size=40)
        row.addWidget(self.account_badge)
        text = QVBoxLayout()
        text.setSpacing(2)
        self.account_name = QLabel(t("settings.not_logged"), card)
        self.account_name.setObjectName("h3")
        self.account_name.setTextFormat(Qt.TextFormat.PlainText)
        self.account_hint = QLabel(t("settings.account_hint"), card)
        self.account_hint.setObjectName("tiny")
        self.account_hint.setWordWrap(True)
        text.addWidget(self.account_name)
        text.addWidget(self.account_hint)
        row.addLayout(text, 1)
        self.account_button = QPushButton(t("settings.login"), card)
        self.account_button.setObjectName("primary")
        self.account_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.account_button.clicked.connect(self._account_action)
        row.addWidget(self.account_button)
        card.add_layout(row)
        self.add(card)

    def _build_language(self) -> None:
        card = Card(padding=18)
        title = QLabel(t("settings.language"), card)
        title.setObjectName("h2")
        card.add(title)
        row = QHBoxLayout()
        row.setSpacing(12)
        self.ui_language = QComboBox(card)
        for code, name in LANGUAGES.items():
            self.ui_language.addItem(name, code)
        ui_holder = QWidget(card)
        ui_layout = QVBoxLayout(ui_holder)
        ui_layout.setContentsMargins(0, 0, 0, 0)
        ui_layout.setSpacing(4)
        ui_label = QLabel(t("settings.ui_language"), ui_holder)
        ui_label.setObjectName("tiny")
        ui_layout.addWidget(ui_label)
        ui_layout.addWidget(self.ui_language)
        row.addWidget(ui_holder, 1)

        self.rpc_language = QComboBox(card)
        for code, name in LANGUAGES.items():
            self.rpc_language.addItem(name, code)
        rpc_holder = QWidget(card)
        rpc_layout = QVBoxLayout(rpc_holder)
        rpc_layout.setContentsMargins(0, 0, 0, 0)
        rpc_layout.setSpacing(4)
        rpc_label = QLabel(t("settings.rpc_language"), rpc_holder)
        rpc_label.setObjectName("tiny")
        rpc_layout.addWidget(rpc_label)
        rpc_layout.addWidget(self.rpc_language)
        row.addWidget(rpc_holder, 1)
        card.add_layout(row)

        self.restart_hint = QLabel(t("app.restart_required"), card)
        self.restart_hint.setStyleSheet(f"color: {theme.ORANGE};")
        self.restart_hint.setVisible(False)
        card.add(self.restart_hint)
        self.ui_language.currentIndexChanged.connect(self._language_changed)
        self.rpc_language.currentIndexChanged.connect(self.notify)
        self.add(card)

    def _build_behavior(self) -> None:
        card = Card(padding=18)
        title = QLabel(t("settings.behavior"), card)
        title.setObjectName("h2")
        card.add(title)
        self.autostart_toggle = ToggleRow(t("settings.autostart"), t("settings.autostart_hint"), card)
        card.add(self.autostart_toggle)

        divider = QFrame(card)
        divider.setObjectName("separator")
        divider.setFrameShape(QFrame.Shape.HLine)
        card.add(divider)

        self.hotkeys_toggle = ToggleRow(t("settings.hotkeys"), t("settings.hotkeys_hint"), card)
        card.add(self.hotkeys_toggle)
        keys = QVBoxLayout()
        keys.setSpacing(1)
        for text in (
            t("settings.hotkey_toggle_player"),
            t("settings.hotkey_lyrics"),
            t("settings.hotkey_play"),
            t("settings.hotkey_next"),
            t("settings.hotkey_prev"),
            t("settings.hotkey_presence"),
        ):
            label = QLabel(text, card)
            label.setObjectName("tiny")
            keys.addWidget(label)
        card.add_layout(keys)

        divider = QFrame(card)
        divider.setObjectName("separator")
        divider.setFrameShape(QFrame.Shape.HLine)
        card.add(divider)

        self.stats_toggle = ToggleRow(t("settings.stats_enabled"), t("settings.stats_hint"), card)
        card.add(self.stats_toggle)

        for toggle in (self.autostart_toggle, self.hotkeys_toggle, self.stats_toggle):
            toggle.switch.toggled.connect(self.notify)
        self.add(card)

    def _build_updates(self) -> None:
        card = Card(padding=18)
        header = QHBoxLayout()
        title = QLabel(t("settings.updates"), card)
        title.setObjectName("h2")
        header.addWidget(title)
        header.addStretch(1)
        self.check_button = QPushButton(t("settings.check_updates"), card)
        self.check_button.setIcon(icons.icon("refresh", theme.MUTED, 15))
        self.check_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.check_button.clicked.connect(self.check_updates_requested)
        header.addWidget(self.check_button)
        card.add_layout(header)

        self.auto_update_toggle = ToggleRow(t("settings.auto_update"), "", card)
        card.add(self.auto_update_toggle)

        repo_row = QHBoxLayout()
        self.repo_edit = QLineEdit(card)
        self.repo_edit.setPlaceholderText("owner/repo")
        repo_row.addWidget(self.repo_edit, 1)
        self.repo_error = QLabel("", card)
        self.repo_error.setObjectName("danger")
        self.repo_error.setTextFormat(Qt.TextFormat.PlainText)
        self.repo_error.setWordWrap(True)
        self.repo_error.setVisible(False)
        repo_row.addWidget(self.repo_error)
        card.add_layout(repo_row)
        hint = QLabel(t("settings.update_repo_hint"), card)
        hint.setObjectName("tiny")
        hint.setWordWrap(True)
        card.add(hint)

        self.update_box = QFrame(card)
        self.update_box.setObjectName("soft")
        box = QVBoxLayout(self.update_box)
        box.setContentsMargins(14, 12, 14, 12)
        box.setSpacing(7)
        row = QHBoxLayout()
        self.update_title = QLabel("", self.update_box)
        self.update_title.setObjectName("h3")
        self.update_title.setTextFormat(Qt.TextFormat.PlainText)
        row.addWidget(self.update_title)
        row.addStretch(1)
        self.update_page_button = QPushButton(t("app.open"), self.update_box)
        self.update_page_button.setObjectName("ghost")
        self.update_page_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update_page_button.clicked.connect(self._open_update_page)
        row.addWidget(self.update_page_button)
        self.install_button = QPushButton(t("settings.download_install"), self.update_box)
        self.install_button.setObjectName("primary")
        self.install_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.install_button.clicked.connect(self.install_update_requested)
        row.addWidget(self.install_button)
        box.addLayout(row)
        self.update_notes = QLabel("", self.update_box)
        self.update_notes.setObjectName("muted")
        self.update_notes.setTextFormat(Qt.TextFormat.PlainText)
        self.update_notes.setWordWrap(True)
        self.update_notes.setMaximumHeight(90)
        box.addWidget(self.update_notes)
        self.update_progress = QProgressBar(self.update_box)
        self.update_progress.setVisible(False)
        self.update_progress.setRange(0, 100)
        box.addWidget(self.update_progress)
        self.update_status = QLabel("", self.update_box)
        self.update_status.setObjectName("tiny")
        self.update_status.setTextFormat(Qt.TextFormat.PlainText)
        self.update_status.setWordWrap(True)
        self.update_status.setVisible(False)
        box.addWidget(self.update_status)
        self.update_box.setVisible(False)
        card.add(self.update_box)
        self.auto_update_toggle.switch.toggled.connect(self.notify)
        self.repo_edit.textChanged.connect(self._repo_changed)
        self.repo_edit.textChanged.connect(self.notify)
        self.add(card)

    def _build_data(self) -> None:
        card = Card(padding=18)
        title = QLabel(t("settings.data"), card)
        title.setObjectName("h2")
        card.add(title)
        path = QLabel(str(data_dir()), card)
        path.setObjectName("tiny")
        path.setWordWrap(True)
        path.setToolTip(str(data_dir()))
        path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        card.add(path)
        row = QHBoxLayout()
        row.setSpacing(8)
        open_data = QPushButton(t("settings.open_data"), card)
        open_data.setIcon(icons.icon("folder", theme.MUTED, 15))
        open_data.setCursor(Qt.CursorShape.PointingHandCursor)
        open_data.clicked.connect(lambda: open_data_folder(data_dir()))
        row.addWidget(open_data)
        open_logs = QPushButton(t("settings.open_logs"), card)
        open_logs.setIcon(icons.icon("folder", theme.MUTED, 15))
        open_logs.setCursor(Qt.CursorShape.PointingHandCursor)
        open_logs.clicked.connect(lambda: open_data_folder(log_dir()))
        row.addWidget(open_logs)
        row.addStretch(1)
        card.add_layout(row)

        divider = QFrame(card)
        divider.setObjectName("separator")
        divider.setFrameShape(QFrame.Shape.HLine)
        card.add(divider)
        about = QLabel(t("settings.about"), card)
        about.setObjectName("h2")
        card.add(about)
        text = QLabel(t("settings.about_text", version=__version__), card)
        text.setObjectName("muted")
        text.setWordWrap(True)
        card.add(text)
        disclaimer = QLabel(t("settings.disclaimer"), card)
        disclaimer.setObjectName("tiny")
        disclaimer.setWordWrap(True)
        card.add(disclaimer)
        self.add(card)

    # ------------------------------------------------------------------ state

    def _load(self, settings: Settings) -> None:
        self._settings = settings
        self.ui_language.setCurrentIndex(max(0, self.ui_language.findData(settings.ui_language)))
        self.rpc_language.setCurrentIndex(max(0, self.rpc_language.findData(settings.rpc_language)))
        self.autostart_toggle.switch.setChecked(settings.autostart)
        self.hotkeys_toggle.switch.setChecked(settings.hotkeys_enabled)
        self.stats_toggle.switch.setChecked(settings.stats_enabled)
        self.auto_update_toggle.switch.setChecked(settings.auto_update)
        self.repo_edit.setText(settings.update_repo)
        self._language_changed()
        self._repo_changed()

    def _language_changed(self) -> None:
        changed = self.ui_language.currentData() != current_language()
        self.restart_hint.setVisible(changed)
        if not self._loading:
            self.notify()

    def _repo_changed(self) -> None:
        value = self.repo_edit.text().strip()
        valid = bool(REPO_RE.match(value))
        self.repo_error.setText("" if valid else t("settings.update_repo_error"))
        self.repo_error.setVisible(not valid)
        self.repo_edit.setStyleSheet("" if valid else f"border-color: {theme.RED};")

    def _account_action(self) -> None:
        if self._account:
            self.logout_requested.emit()
        else:
            self.login_requested.emit()

    def set_account(self, name: str | None) -> None:
        self._account = name
        if name:
            self.account_name.setText(t("settings.logged_in", name=name))
            self.account_button.setText(t("settings.logout"))
            self.account_button.setObjectName("ghost")
            self.account_badge.setPixmap(icons.pixmap("headphones", theme.ACCENT, 20, dpr=2))
        else:
            self.account_name.setText(t("settings.not_logged"))
            self.account_button.setText(t("settings.login"))
            self.account_button.setObjectName("primary")
            self.account_badge.setPixmap(icons.pixmap("login", theme.ACCENT, 20, dpr=2))
        self.account_button.style().unpolish(self.account_button)
        self.account_button.style().polish(self.account_button)

    # ------------------------------------------------------------------ updates

    def set_checking(self, checking: bool) -> None:
        self.check_button.setEnabled(not checking)
        self.check_button.setText(
            t("app.loading") if checking else t("settings.check_updates")
        )

    def check_finished(self, info: UpdateInfo | None) -> None:
        self.set_checking(False)
        if info is None:
            self.update_box.setVisible(False)
            self.toast_requested.emit(t("settings.update_none"))
            return
        self.set_update(info)

    def set_update(self, info: UpdateInfo | None) -> None:
        self._update = info
        if info is None:
            self.update_box.setVisible(False)
            return
        self.update_title.setText(t("settings.update_available", version=info.version))
        self.update_notes.setText(info.notes.strip()[:600])
        self.update_notes.setVisible(bool(info.notes.strip()))
        self.install_button.setVisible(bool(info.asset_url))
        self.update_page_button.setVisible(bool(info.page_url))
        self.update_status.setVisible(False)
        self.update_progress.setVisible(False)
        self.update_box.setVisible(True)

    def set_progress(self, progress: UpdateProgress) -> None:
        self.install_button.setEnabled(False)
        self.update_progress.setVisible(True)
        self.update_progress.setValue(progress.percent)
        self.update_status.setText(t("settings.downloading", percent=progress.percent))
        self.update_status.setVisible(True)

    def pending_update(self) -> UpdateInfo | None:
        return self._update

    def set_update_ready(self, ok: bool, detail: str) -> None:
        self.install_button.setEnabled(True)
        self.update_status.setText(detail)
        self.update_status.setVisible(True)
        if ok:
            self.toast_requested.emit(t("toast.update_ready"))

    def _open_update_page(self) -> None:
        if self._update and is_https_url(self._update.page_url, {"github.com"}):
            QDesktopServices.openUrl(QUrl(self._update.page_url))

    # ------------------------------------------------------------------ form

    def apply_to(self, settings: Settings) -> Settings:
        return replace(
            settings,
            ui_language=self.ui_language.currentData() or "ru",
            rpc_language=self.rpc_language.currentData() or "ru",
            autostart=self.autostart_toggle.switch.isChecked(),
            hotkeys_enabled=self.hotkeys_toggle.switch.isChecked(),
            stats_enabled=self.stats_toggle.switch.isChecked(),
            auto_update=self.auto_update_toggle.switch.isChecked(),
            update_repo=self.repo_edit.text().strip(),
        )

    def validate(self) -> str | None:
        if not REPO_RE.match(self.repo_edit.text().strip()):
            return t("settings.update_repo_error")
        return None
