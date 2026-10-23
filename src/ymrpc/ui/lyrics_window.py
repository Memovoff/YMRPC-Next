"""Окно синхронизированного текста песни."""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..i18n import t
from ..models import Lyrics, PlaybackView
from . import icons, theme
from .widgets import ElidedLabel, IconBadge, IconButton, Pill


class LyricsWindow(QWidget):
    reload_requested = Signal()
    offset_changed = Signal(float)
    closed = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(t("lyrics.title"))
        self.setWindowIcon(icons.app_icon())
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.resize(450, 620)
        self._lyrics: Lyrics | None = None
        self._view = PlaybackView()
        self._offset = 0.0
        self._track_key: str | None = None
        self._active = -1
        self._loading = False
        self._build()
        self._scroll_animation = QPropertyAnimation(self.list.verticalScrollBar(), b"value", self)
        self._scroll_animation.setDuration(190)
        self._scroll_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._timer = QTimer(self)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._tick)

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(11)
        badge = IconBadge("lyrics", theme.ACCENT, self, size=40)
        header.addWidget(badge)
        titles = QVBoxLayout()
        titles.setSpacing(1)
        self.title = ElidedLabel(t("lyrics.title"), self)
        self.title.setObjectName("h2")
        titles.addWidget(self.title)
        self.artist = ElidedLabel("", self)
        self.artist.setObjectName("muted")
        titles.addWidget(self.artist)
        header.addLayout(titles, 1)
        self.status = Pill("", theme.MUTED, self)
        header.addWidget(self.status, 0, Qt.AlignmentFlag.AlignTop)
        self.close_button = IconButton("close", t("lyrics.close"), self, size=30, icon_size=15)
        self.close_button.clicked.connect(self.hide)
        header.addWidget(self.close_button, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)

        self.empty = QLabel(t("lyrics.not_found"), self)
        self.empty.setObjectName("muted")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)
        layout.addWidget(self.empty, 1)

        self.list = QListWidget(self)
        self.list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.list.setSpacing(2)
        layout.addWidget(self.list, 1)

        footer = QHBoxLayout()
        footer.setSpacing(6)
        self.minus = QPushButton("−", self)
        self.minus.setFixedSize(30, 28)
        self.minus.setToolTip(t("lyrics.offset"))
        self.minus.clicked.connect(lambda: self._change_offset(-0.5))
        footer.addWidget(self.minus)
        self.offset_label = QLabel("0.0 с", self)
        self.offset_label.setObjectName("tiny")
        self.offset_label.setMinimumWidth(62)
        self.offset_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer.addWidget(self.offset_label)
        self.plus = QPushButton("+", self)
        self.plus.setFixedSize(30, 28)
        self.plus.clicked.connect(lambda: self._change_offset(0.5))
        footer.addWidget(self.plus)
        self.source = QLabel("", self)
        self.source.setObjectName("tiny")
        self.source.setTextFormat(Qt.TextFormat.PlainText)
        footer.addWidget(self.source, 1)
        self.reload = QPushButton(t("lyrics.reload"), self)
        self.reload.setIcon(icons.icon("refresh", theme.MUTED, 14))
        self.reload.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reload.clicked.connect(self._reload)
        footer.addWidget(self.reload)
        layout.addLayout(footer)

        self.list.setVisible(False)

    # ------------------------------------------------------------------ state

    def set_view(self, view: PlaybackView) -> None:
        self._view = view
        track = view.track
        key = track.key if track else None
        if key != self._track_key:
            self._track_key = key
            self._lyrics = None
            self._active = -1
            self.list.clear()
            self.list.setVisible(False)
            self._loading = bool(track)
            self.status.setVisible(False)
            self.source.setText("")
            self.empty.setText(t("lyrics.loading") if track else t("lyrics.not_found"))
            self.empty.setVisible(True)
        if track:
            self.title.set_full_text(track.title)
            self.artist.set_full_text(track.artist or t("app.unknown"))
        else:
            self.title.set_full_text(t("lyrics.title"))
            self.artist.set_full_text(t("tray.no_track"))
        self._tick()

    def set_lyrics(self, lyrics: Lyrics | None) -> None:
        self._lyrics = lyrics
        self._loading = False
        self._active = -1
        self.list.clear()
        self._scroll_animation.stop()
        self.list.verticalScrollBar().setValue(0)
        if lyrics is None or not lyrics.available:
            self.empty.setText(t("lyrics.not_found"))
            self.empty.setVisible(True)
            self.list.setVisible(False)
            self.status.setVisible(False)
            self.source.setText("")
            return

        lines = [line.text for line in lyrics.lines] if lyrics.lines else [
            line.strip() for line in lyrics.plain.splitlines() if line.strip()
        ]
        base_font = QFont(self.list.font())
        base_font.setPointSizeF(11.5)
        for text in lines:
            item = QListWidgetItem(text or "♪", self.list)
            item.setFont(base_font)
            item.setForeground(QColor(theme.MUTED))
            item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self.list.setVisible(True)
        self.empty.setVisible(False)
        if lyrics.synced:
            self.status.setText(t("lyrics.synced"))
            self.status.set_color(theme.GREEN)
            self.status.setVisible(True)
        else:
            self.status.setText(t("lyrics.plain"))
            self.status.set_color(theme.MUTED)
            self.status.setVisible(True)
        self.source.setText(lyrics.source)
        self._tick()

    def set_offset(self, value: float) -> None:
        self._offset = max(-30.0, min(30.0, float(value)))
        self.offset_label.setText(f"{self._offset:+.1f} с")
        self._active = -1
        self._tick()

    def _change_offset(self, delta: float) -> None:
        self.set_offset(self._offset + delta)
        self.offset_changed.emit(self._offset)

    def _tick(self) -> None:
        lyrics = self._lyrics
        if lyrics is None or not lyrics.synced or not lyrics.lines:
            return
        position = self._view.position_at() + self._offset
        index = lyrics.active_index(position)
        if index == self._active:
            return
        previous = self._active
        self._active = index
        if 0 <= previous < self.list.count():
            item = self.list.item(previous)
            item.setForeground(QColor(theme.MUTED))
            font = item.font()
            font.setBold(False)
            item.setFont(font)
            item.setBackground(QColor(0, 0, 0, 0))
        if 0 <= index < self.list.count():
            item = self.list.item(index)
            item.setForeground(QColor(theme.ACCENT))
            font = item.font()
            font.setBold(True)
            item.setFont(font)
            item.setBackground(QColor(255, 204, 0, 18))
            self._scroll_to(index)

    def _scroll_to(self, index: int) -> None:
        item = self.list.item(index)
        if item is None:
            return
        rect = self.list.visualItemRect(item)
        scrollbar = self.list.verticalScrollBar()
        target = scrollbar.value() + rect.center().y() - self.list.viewport().height() // 2
        target = max(scrollbar.minimum(), min(scrollbar.maximum(), target))
        self._scroll_animation.stop()
        self._scroll_animation.setStartValue(scrollbar.value())
        self._scroll_animation.setEndValue(target)
        self._scroll_animation.start()

    def _reload(self) -> None:
        self._loading = True
        self.empty.setText(t("lyrics.loading"))
        self.empty.setVisible(True)
        self.list.setVisible(False)
        self.status.setVisible(False)
        self.reload_requested.emit()

    def present(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
        self._timer.start()
        self._tick()

    def hideEvent(self, event) -> None:  # noqa: N802
        self._timer.stop()
        super().hideEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802
        self._timer.start()
        super().showEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802
        event.ignore()
        self.hide()
        self.closed.emit()
