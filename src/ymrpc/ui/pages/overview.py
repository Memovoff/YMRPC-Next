"""Страница «Обзор»: текущий трек и быстрые действия."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...i18n import t
from ...models import PlaybackStatus, PlaybackView
from .. import icons, theme
from ..widgets import (
    Card,
    CoverWidget,
    ElidedLabel,
    IconBadge,
    IconButton,
    Page,
    Pill,
    SeekBar,
    SoftCard,
    format_time,
)


class OverviewPage(Page):
    control_requested = Signal(str)
    seek_requested = Signal(float)
    mini_requested = Signal()
    lyrics_requested = Signal()
    presence_requested = Signal()
    login_requested = Signal()
    logout_requested = Signal()
    overlay_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(t("nav.overview"), t("app.tagline"), parent)
        self._view = PlaybackView()
        self._settings = None
        self._account: str | None = None
        self._overlay_running = False
        self._overlay_url = ""

        self._build_now_playing()
        self._build_quick_actions()
        self._build_account()
        self._build_status()

        self._ticker = QTimer(self)
        self._ticker.setInterval(500)
        self._ticker.timeout.connect(self._tick)
        self._ticker.start()

    # ------------------------------------------------------------------ build

    def _build_now_playing(self) -> None:
        card = Card(accent=True, padding=22)
        self.now_card = card
        row = QHBoxLayout()
        row.setSpacing(22)
        self.cover = CoverWidget(150, 16, card)
        row.addWidget(self.cover, 0, Qt.AlignmentFlag.AlignTop)

        info = QVBoxLayout()
        info.setSpacing(7)
        chips = QHBoxLayout()
        chips.setSpacing(7)
        self.source_pill = Pill("—", theme.MUTED, card)
        self.presence_pill = Pill("", theme.GREEN, card)
        chips.addWidget(self.source_pill)
        chips.addWidget(self.presence_pill)
        chips.addStretch(1)
        info.addLayout(chips)

        self.title = ElidedLabel(t("overview.nothing"), card)
        self.title.setObjectName("h1")
        info.addWidget(self.title)
        self.artist = ElidedLabel("", card)
        self.artist.setObjectName("muted")
        info.addWidget(self.artist)
        self.album = ElidedLabel("", card)
        self.album.setObjectName("tiny")
        info.addWidget(self.album)
        info.addSpacing(6)

        self.seek = SeekBar(card, height=7)
        self.seek.seek_requested.connect(self.seek_requested)
        info.addWidget(self.seek)
        times = QHBoxLayout()
        self.position_label = QLabel("0:00", card)
        self.position_label.setObjectName("tiny")
        self.duration_label = QLabel("0:00", card)
        self.duration_label.setObjectName("tiny")
        times.addWidget(self.position_label)
        times.addStretch(1)
        times.addWidget(self.duration_label)
        info.addLayout(times)
        info.addSpacing(2)

        controls = QHBoxLayout()
        controls.setSpacing(6)
        self.prev_button = IconButton("prev", t("mini.prev"), card, size=36, icon_size=19)
        self.next_button = IconButton("next", t("mini.next"), card, size=36, icon_size=19)
        self.play_button = QPushButton(card)
        self.play_button.setObjectName("playButton")
        self.play_button.setFixedSize(46, 46)
        self.play_button.setIcon(icons.icon("play", "#141414", 22))
        self.play_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lyrics_button = QPushButton(t("overview.lyrics"), card)
        self.lyrics_button.setIcon(icons.icon("lyrics", theme.MUTED, 17))
        self.lyrics_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lyrics_button.setEnabled(False)
        controls.addWidget(self.prev_button)
        controls.addWidget(self.play_button)
        controls.addWidget(self.next_button)
        controls.addSpacing(10)
        controls.addWidget(self.lyrics_button)
        controls.addStretch(1)
        info.addLayout(controls)

        self.prev_button.clicked.connect(lambda: self.control_requested.emit("previous"))
        self.next_button.clicked.connect(lambda: self.control_requested.emit("next"))
        self.play_button.clicked.connect(lambda: self.control_requested.emit("toggle"))
        self.lyrics_button.clicked.connect(self.lyrics_requested)

        row.addLayout(info, 1)
        card.add_layout(row)
        self.add(card)

    def _build_quick_actions(self) -> None:
        card = Card(padding=18)
        header = QHBoxLayout()
        title = QLabel(t("overview.quick"), card)
        title.setObjectName("h2")
        header.addWidget(title)
        header.addStretch(1)
        card.add_layout(header)

        row = QHBoxLayout()
        row.setSpacing(10)
        self.mini_button = self._tile(t("overview.mini_player"), "headphones", card, checkable=True)
        self.presence_button = self._tile(t("overview.hide_presence"), "eye", card, checkable=True)
        self.lyrics_tile = self._tile(t("overview.lyrics"), "lyrics", card)
        self.overlay_tile = self._tile(t("overview.overlay"), "overlay", card)

        self.mini_button.clicked.connect(self.mini_requested)
        self.presence_button.clicked.connect(self.presence_requested)
        self.lyrics_tile.clicked.connect(self.lyrics_requested)
        self.overlay_tile.clicked.connect(self._open_overlay)

        for button in (self.mini_button, self.presence_button, self.lyrics_tile, self.overlay_tile):
            row.addWidget(button, 1)
        card.add_layout(row)
        self.add(card)

    def _tile(self, text: str, icon_name: str, parent: QWidget, *, checkable: bool = False) -> QPushButton:
        button = QPushButton(text, parent)
        button.setObjectName("tile")
        button.setCheckable(checkable)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setIcon(icons.icon(icon_name, theme.MUTED, 19))
        button.setMinimumHeight(62)
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        return button

    def _build_account(self) -> None:
        self.account_card = Card(padding=16)
        row = QHBoxLayout()
        row.setSpacing(12)
        self.account_badge = IconBadge("login", theme.ACCENT, self.account_card, size=38)
        row.addWidget(self.account_badge)
        text = QVBoxLayout()
        text.setSpacing(2)
        self.account_name = QLabel(t("overview.not_logged"), self.account_card)
        self.account_name.setObjectName("h3")
        self.account_name.setTextFormat(Qt.TextFormat.PlainText)
        self.account_hint = QLabel(t("settings.account_hint"), self.account_card)
        self.account_hint.setObjectName("tiny")
        self.account_hint.setWordWrap(True)
        text.addWidget(self.account_name)
        text.addWidget(self.account_hint)
        row.addLayout(text, 1)
        self.account_button = QPushButton(t("overview.login"), self.account_card)
        self.account_button.setObjectName("primary")
        self.account_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.account_button.clicked.connect(self._account_action)
        row.addWidget(self.account_button)
        self.account_card.add_layout(row)
        self.add(self.account_card)

    def _build_status(self) -> None:
        row = QHBoxLayout()
        row.setSpacing(10)
        self.status_source = self._status_tile("sources", t("overview.source"))
        self.status_discord = self._status_tile("discord", "Discord")
        self.status_overlay = self._status_tile("overlay", t("overview.overlay"))
        for tile in (self.status_source, self.status_discord, self.status_overlay):
            row.addWidget(tile, 1)
        self.add_layout(row)

    def _status_tile(self, icon_name: str, title: str) -> QFrame:
        frame = SoftCard(self, padding=13)
        row = QHBoxLayout()
        row.setSpacing(10)
        badge = IconBadge(icon_name, theme.MUTED, frame, size=30)
        row.addWidget(badge)
        text = QVBoxLayout()
        text.setSpacing(0)
        label = QLabel(title, frame)
        label.setObjectName("tiny")
        value = QLabel("—", frame)
        value.setObjectName("h3")
        value.setProperty("role", "value")
        text.addWidget(label)
        text.addWidget(value)
        row.addLayout(text, 1)
        frame.body.addLayout(row)
        frame.value = value
        return frame

    # ------------------------------------------------------------------ state

    def load(self, settings) -> None:
        super().load(settings)
        self._settings = settings
        self._apply_presence_state()

    def _apply_presence_state(self) -> None:
        if self._settings is None:
            return
        enabled = self._settings.presence_enabled
        self.presence_button.setChecked(enabled)
        self.presence_button.setText(
            t("overview.hide_presence") if enabled else t("overview.show_presence")
        )
        self.presence_button.setIcon(
            icons.icon("eye" if enabled else "eye_off", theme.ACCENT if enabled else theme.MUTED, 19)
        )
        if enabled:
            self.presence_pill.setText(t("overview.presence_on"))
            self.presence_pill.set_color(theme.GREEN)
        else:
            self.presence_pill.setText(t("overview.presence_off"))
            self.presence_pill.set_color(theme.MUTED)
        self.presence_pill.setVisible(self._view.has_track)

    def set_mini_visible(self, visible: bool) -> None:
        self.mini_button.setChecked(visible)

    def set_account(self, name: str | None) -> None:
        self._account = name
        if name:
            self.account_name.setText(t("settings.logged_in", name=name))
            self.account_hint.setText(t("settings.account_hint"))
            self.account_button.setText(t("overview.logout"))
            self.account_button.setObjectName("ghost")
            self.account_badge.setPixmap(icons.pixmap("headphones", theme.ACCENT, 19, dpr=2))
        else:
            self.account_name.setText(t("overview.not_logged"))
            self.account_hint.setText(t("settings.account_hint"))
            self.account_button.setText(t("overview.login"))
            self.account_button.setObjectName("primary")
            self.account_badge.setPixmap(icons.pixmap("login", theme.ACCENT, 19, dpr=2))
        self.account_button.style().unpolish(self.account_button)
        self.account_button.style().polish(self.account_button)

    def _account_action(self) -> None:
        if self._account:
            self.logout_requested.emit()
        else:
            self.login_requested.emit()

    def set_overlay(self, running: bool, url: str) -> None:
        self._overlay_running = running
        self._overlay_url = url
        self.status_overlay.value.setText(url if running else t("overlay.stopped"))
        self.status_overlay.value.setToolTip(url)

    def _open_overlay(self) -> None:
        self.overlay_requested.emit()

    def update_view(self, view: PlaybackView) -> None:
        self._view = view
        track = view.track
        self.cover.set_path(view.art_path)
        if track:
            self.title.set_full_text(track.title)
            self.artist.set_full_text(track.artist or t("app.unknown"))
            year = f" · {track.year}" if track.year else ""
            album = f"{track.album}{year}" if track.album else year.lstrip(" ·")
            self.album.set_full_text(album)
            self.source_pill.setText(view.source_name or t("source.unknown"))
            self.source_pill.setVisible(True)
            self.status_source.value.setText(view.source_name or "—")
            self.lyrics_button.setEnabled(view.lyrics_available)
            self.lyrics_tile.setEnabled(view.lyrics_available)
        else:
            self.title.set_full_text(t("overview.nothing"))
            self.artist.set_full_text(t("overview.nothing_hint"))
            self.album.set_full_text("")
            self.source_pill.setVisible(False)
            self.status_source.value.setText("—")
            self.lyrics_button.setEnabled(False)
            self.lyrics_tile.setEnabled(False)
        self.presence_pill.setVisible(bool(track) and self._settings is not None)
        self._apply_presence_state()

        active = track is not None
        for button in (self.prev_button, self.next_button, self.play_button):
            button.setEnabled(active)
        playing = view.status == PlaybackStatus.PLAYING
        self.play_button.setIcon(icons.icon("pause" if playing else "play", "#141414", 22))
        self.play_button.setToolTip(t("mini.pause") if playing else t("mini.play"))
        self._tick()

    def update_settings(self, settings) -> None:
        self._settings = settings
        self._apply_presence_state()

    def _tick(self) -> None:
        view = self._view
        if view.track is None:
            self.seek.set_state(0, 0)
            self.position_label.setText("0:00")
            self.duration_label.setText("0:00")
            return
        position = view.position_at()
        self.seek.set_state(position, view.duration)
        self.position_label.setText(format_time(position))
        self.duration_label.setText(format_time(view.duration) if view.duration else "")

    def on_shown(self) -> None:
        self._tick()
