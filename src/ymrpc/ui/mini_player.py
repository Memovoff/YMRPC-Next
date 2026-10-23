"""Компактный мини-плеер поверх всех окон."""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..i18n import t
from ..models import PlaybackStatus, PlaybackView
from . import icons, theme
from .widgets import CoverWidget, ElidedLabel, IconButton, SeekBar, format_time


class MiniPlayer(QWidget):
    open_requested = Signal()
    lyrics_requested = Signal()
    control_requested = Signal(str)
    seek_requested = Signal(float)
    closed_by_user = Signal()
    moved = Signal(QPoint)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle(t("overview.mini_player"))
        self.setWindowIcon(icons.app_icon())
        self._view = PlaybackView()
        self._drag_offset: QPoint | None = None
        self._build()

        self._ticker = QTimer(self)
        self._ticker.setInterval(500)
        self._ticker.timeout.connect(self._tick)
        self._ticker.start()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        frame = QFrame(self)
        frame.setObjectName("miniCard")
        frame.setStyleSheet(
            "QFrame#miniCard { background: rgba(19, 21, 27, 0.98);"
            f" border: 1px solid {theme.BORDER}; border-radius: 16px; }}"
        )
        shadow = QGraphicsDropShadowEffect(frame)
        shadow.setBlurRadius(30)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(0, 0, 0, 170))
        frame.setGraphicsEffect(shadow)
        outer.addWidget(frame)

        layout = QHBoxLayout(frame)
        layout.setContentsMargins(12, 11, 11, 11)
        layout.setSpacing(11)
        self.cover = CoverWidget(70, 11, frame)
        layout.addWidget(self.cover)

        info = QVBoxLayout()
        info.setSpacing(3)
        self.title = ElidedLabel(t("mini.no_track"), frame)
        self.title.setStyleSheet("font-size: 13px; font-weight: 700;")
        info.addWidget(self.title)
        self.artist = ElidedLabel("", frame)
        self.artist.setStyleSheet(f"color: {theme.MUTED}; font-size: 11px;")
        info.addWidget(self.artist)
        info.addStretch(1)
        self.seek = SeekBar(frame, height=4, interactive=True)
        self.seek.seek_requested.connect(self._seek)
        info.addWidget(self.seek)
        times = QHBoxLayout()
        times.setSpacing(4)
        self.position = QLabel("0:00", frame)
        self.position.setObjectName("tiny")
        self.duration = QLabel("", frame)
        self.duration.setObjectName("tiny")
        times.addWidget(self.position)
        times.addStretch(1)
        times.addWidget(self.duration)
        info.addLayout(times)
        layout.addLayout(info, 1)

        controls = QVBoxLayout()
        controls.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(2)
        top.addStretch(1)
        self.lyrics_button = IconButton("lyrics", t("mini.lyrics"), frame, size=24, icon_size=14)
        self.lyrics_button.clicked.connect(self.lyrics_requested)
        top.addWidget(self.lyrics_button)
        self.close_button = IconButton("close", t("mini.close"), frame, size=24, icon_size=13)
        self.close_button.clicked.connect(self._close)
        top.addWidget(self.close_button)
        controls.addLayout(top)

        player = QHBoxLayout()
        player.setSpacing(3)
        self.prev_button = IconButton("prev", t("mini.prev"), frame, size=27, icon_size=14)
        self.prev_button.clicked.connect(lambda: self.control_requested.emit("previous"))
        player.addWidget(self.prev_button)
        self.play_button = QPushButton(frame)
        self.play_button.setFixedSize(34, 34)
        self.play_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.play_button.setIcon(icons.icon("play", "#141414", 17))
        self.play_button.setStyleSheet(
            f"QPushButton {{ background: {theme.ACCENT}; border: none; border-radius: 17px; }}"
            f"QPushButton:hover {{ background: {theme.ACCENT_HOVER}; }}"
            f"QPushButton:disabled {{ background: #3a351d; }}"
        )
        self.play_button.clicked.connect(lambda: self.control_requested.emit("toggle"))
        player.addWidget(self.play_button)
        self.next_button = IconButton("next", t("mini.next"), frame, size=27, icon_size=14)
        self.next_button.clicked.connect(lambda: self.control_requested.emit("next"))
        player.addWidget(self.next_button)
        controls.addLayout(player)
        layout.addLayout(controls)

        self.setMinimumWidth(366)
        self.resize(376, 124)

    # ------------------------------------------------------------------ state

    def set_view(self, view: PlaybackView) -> None:
        self._view = view
        track = view.track
        self.cover.set_path(view.art_path)
        if track:
            self.title.set_full_text(track.title)
            self.artist.set_full_text(track.artist or t("app.unknown"))
            self.setWindowTitle(f"{track.title} — {track.artist}")
        else:
            self.title.set_full_text(t("mini.no_track"))
            self.artist.set_full_text("")
            self.setWindowTitle(t("overview.mini_player"))
        active = track is not None
        for button in (self.prev_button, self.play_button, self.next_button):
            button.setEnabled(active)
        self.lyrics_button.setEnabled(view.lyrics_available)
        playing = view.status == PlaybackStatus.PLAYING
        self.play_button.setIcon(icons.icon("pause" if playing else "play", "#141414", 17))
        self.play_button.setToolTip(t("mini.pause") if playing else t("mini.play"))
        self._tick()

    def _tick(self) -> None:
        view = self._view
        if view.track is None:
            self.seek.set_state(0, 0)
            self.position.setText("0:00")
            self.duration.setText("")
            return
        position = view.position_at()
        self.seek.set_state(position, view.duration)
        self.position.setText(format_time(position))
        self.duration.setText(format_time(view.duration) if view.duration else "")

    def _seek(self, position: float) -> None:
        self.seek_requested.emit(position)

    def _close(self) -> None:
        self.hide()
        self.closed_by_user.emit()

    # ------------------------------------------------------------------ window

    def show_player(self, position: QPoint | None = None) -> None:
        if position is not None:
            self.move(self._clamp(position))
        else:
            self.move(self._clamp(self.pos()))
        self.show()
        self.raise_()
        self._ticker.start()

    def hideEvent(self, event) -> None:  # noqa: N802
        self._ticker.stop()
        super().hideEvent(event)

    def _clamp(self, position: QPoint) -> QPoint:
        target = self.screen()
        if target is None and self.parentWidget() is not None:
            target = self.parentWidget().screen()
        if target is None:
            return position
        area = target.availableGeometry()
        x = min(max(area.left(), position.x()), area.right() - self.width())
        y = min(max(area.top(), position.y()), area.bottom() - self.height())
        return QPoint(x, y)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            child = self.childAt(event.position().toPoint())
            if not isinstance(child, QAbstractButton):
                self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._drag_offset is not None:
            self._drag_offset = None
            self.moved.emit(self.pos())
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self.open_requested.emit()
        super().mouseDoubleClickEvent(event)
