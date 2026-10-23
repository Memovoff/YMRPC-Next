"""Окно входа в Яндекс Музыку."""

from __future__ import annotations

from urllib.parse import unquote

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..constants import OAUTH_URL
from ..i18n import t
from ..secure_store import validate_token_format
from . import icons, theme
from .widgets import Card, IconBadge


class AuthDialog(QDialog):
    login_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(t("auth.title"))
        self.setModal(True)
        self.setMinimumWidth(500)
        self.setWindowIcon(icons.app_icon())
        self._build()
        theme.apply_dark_title_bar(self)

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(14)

        header = QHBoxLayout()
        header.setSpacing(13)
        badge = IconBadge("music", theme.ACCENT, self, size=46)
        header.addWidget(badge)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        title = QLabel(t("auth.title"), self)
        title.setObjectName("h2")
        titles.addWidget(title)
        subtitle = QLabel(t("settings.account_hint"), self)
        subtitle.setObjectName("muted")
        subtitle.setWordWrap(True)
        titles.addWidget(subtitle)
        header.addLayout(titles, 1)
        layout.addLayout(header)

        steps = Card(padding=14)
        step1 = QLabel(
            f"<b>1.</b> {t('auth.browser')}", steps
        )
        step1.setWordWrap(True)
        steps.add(step1)
        step2 = QLabel(f"<b>2.</b> {t('auth.wait')}", steps)
        step2.setWordWrap(True)
        steps.add(step2)
        step3 = QLabel(f"<b>3.</b> {t('auth.token_hint')}", steps)
        step3.setWordWrap(True)
        step3.setObjectName("muted")
        steps.add(step3)
        layout.addWidget(steps)

        self.open_button = QPushButton(t("auth.browser"), self)
        self.open_button.setObjectName("primary")
        self.open_button.setIcon(icons.icon("external", "#141414", 16))
        self.open_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_button.clicked.connect(self._open_browser)
        layout.addWidget(self.open_button)

        token_label = QLabel(t("auth.manual"), self)
        token_label.setObjectName("tiny")
        layout.addWidget(token_label)

        token_row = QHBoxLayout()
        token_row.setSpacing(6)
        self.token_edit = QLineEdit(self)
        self.token_edit.setPlaceholderText("y0_… / AQAA…")
        self.token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.token_edit.returnPressed.connect(self._submit)
        token_row.addWidget(self.token_edit, 1)
        self.show_button = QPushButton(self)
        self.show_button.setObjectName("iconButton")
        self.show_button.setFixedSize(38, 38)
        self.show_button.setIcon(icons.icon("eye", theme.MUTED, 17))
        self.show_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.show_button.clicked.connect(self._toggle_visibility)
        token_row.addWidget(self.show_button)
        paste = QPushButton(t("app.paste"), self)
        paste.setCursor(Qt.CursorShape.PointingHandCursor)
        paste.clicked.connect(self._paste)
        token_row.addWidget(paste)
        layout.addLayout(token_row)

        self.status = QLabel("", self)
        self.status.setObjectName("tiny")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.error = QLabel("", self)
        self.error.setObjectName("danger")
        self.error.setTextFormat(Qt.TextFormat.PlainText)
        self.error.setWordWrap(True)
        self.error.setVisible(False)
        layout.addWidget(self.error)

        footer = QHBoxLayout()
        footer.addStretch(1)
        cancel = QPushButton(t("app.cancel"), self)
        cancel.setObjectName("ghost")
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)
        self.login_button = QPushButton(t("auth.login"), self)
        self.login_button.setObjectName("primary")
        self.login_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.login_button.clicked.connect(self._submit)
        footer.addWidget(self.login_button)
        layout.addLayout(footer)

        self._visible = False

    def start(self) -> None:
        """Сбрасывает состояние и показывает окно."""
        self.error.setVisible(False)
        self.status.setText("")
        self.set_busy(False)
        self.token_edit.clear()
        self.show()
        self.raise_()
        self.activateWindow()
        self.open_button.setFocus()

    def _open_browser(self) -> None:
        QDesktopServices.openUrl(QUrl(OAUTH_URL))
        self.status.setText(t("auth.wait"))

    def _toggle_visibility(self) -> None:
        self._visible = not self._visible
        self.token_edit.setEchoMode(
            QLineEdit.EchoMode.Normal if self._visible else QLineEdit.EchoMode.Password
        )
        self.show_button.setIcon(icons.icon("eye_off" if self._visible else "eye", theme.MUTED, 17))

    def _paste(self) -> None:
        from PySide6.QtWidgets import QApplication

        text = QApplication.clipboard().text()
        token = extract_token(text)
        if token:
            self.token_edit.setText(token)
            self.token_edit.setFocus()

    def _submit(self) -> None:
        token = extract_token(self.token_edit.text())
        if not validate_token_format(token):
            self.show_error(t("auth.token_hint"))
            return
        self.token_edit.setText(token)
        self.set_busy(True)
        self.error.setVisible(False)
        self.status.setText(t("auth.checking"))
        self.login_requested.emit(token)

    def set_busy(self, busy: bool) -> None:
        self.token_edit.setEnabled(not busy)
        self.open_button.setEnabled(not busy)
        self.login_button.setEnabled(not busy)
        self.login_button.setText(t("auth.checking") if busy else t("auth.login"))

    def show_error(self, message: str) -> None:
        self.set_busy(False)
        self.status.setText("")
        self.error.setText(t("auth.error", error=message))
        self.error.setVisible(True)

    def finish(self, ok: bool, name: str) -> None:
        if ok:
            self.set_busy(False)
            self.accept()
        else:
            self.show_error(name)


def extract_token(text: str) -> str:
    """Достаёт токен из строки или URL с фрагментом access_token."""
    value = (text or "").strip()
    if not value:
        return ""
    marker = "access_token="
    if marker in value:
        value = value.split(marker, 1)[1]
        for separator in ("&", "#", " "):
            value = value.split(separator, 1)[0]
    return unquote(value).strip()
