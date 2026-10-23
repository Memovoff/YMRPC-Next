"""Страница «Статистика»: агрегаты, график, топы и история."""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...constants import data_dir
from ...i18n import t
from ...models import Period, PlaybackView
from ...services import stats as stats_service
from .. import icons, theme
from ..widgets import Card, ElidedLabel, Page, StatTile, format_listened


class ActivityChart(QWidget):
    """Столбики прослушиваний за две недели."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._data: list[dict] = []
        self._hover = -1
        self.setMinimumHeight(150)
        self.setMouseTracking(True)

    def set_data(self, data: list[dict]) -> None:
        self._data = list(data)
        self.update()

    def _bar_rects(self) -> list[QRectF]:
        if not self._data:
            return []
        margins = (22, 12, 12, 26)
        width = max(1, self.width() - margins[0] - margins[2])
        height = max(1, self.height() - margins[1] - margins[3])
        step = width / len(self._data)
        bar_width = max(4.0, step * 0.54)
        peak = max((item.get("listened_ms", 0) for item in self._data), default=0) or 1
        rects = []
        for index, item in enumerate(self._data):
            value = item.get("listened_ms", 0)
            bar_height = max(3.0, height * value / peak) if value else 3.0
            x = margins[0] + step * index + (step - bar_width) / 2
            y = margins[1] + height - bar_height
            rects.append(QRectF(x, y, bar_width, bar_height))
        return rects

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self._data:
            painter.setPen(QPen(QColor(theme.MUTED_DIM)))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, t("stats.empty"))
            painter.end()
            return
        rects = self._bar_rects()
        baseline = self.height() - 26
        painter.setPen(QPen(QColor(theme.BORDER_SOFT), 1))
        painter.drawLine(22, baseline, self.width() - 12, baseline)
        for index, (rect, item) in enumerate(zip(rects, self._data, strict=False)):
            active = index == self._hover
            gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            if active:
                gradient.setColorAt(0, QColor(theme.ACCENT_HOVER))
                gradient.setColorAt(1, QColor(theme.ACCENT))
            else:
                gradient.setColorAt(0, QColor(255, 204, 0, 210))
                gradient.setColorAt(1, QColor(255, 204, 0, 70))
            path = QPainterPath()
            path.addRoundedRect(rect, 3.5, 3.5)
            painter.fillPath(path, gradient)
            if index % 2 == 0 or index == len(rects) - 1:
                painter.setPen(QPen(QColor(theme.MUTED_DIM)))
                font = painter.font()
                font.setPointSize(7)
                painter.setFont(font)
                painter.drawText(
                    QRectF(rect.left() - 16, baseline + 4, rect.width() + 32, 18),
                    Qt.AlignmentFlag.AlignHCenter,
                    item.get("label", ""),
                )
        painter.end()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        position = event.position()
        index = -1
        for candidate, rect in enumerate(self._bar_rects()):
            if position.x() >= rect.left() - 4 and position.x() <= rect.right() + 4:
                index = candidate
                break
        if index != self._hover:
            self._hover = index
            self.update()
        if index >= 0:
            item = self._data[index]
            self.setToolTip(
                f"{item.get('label', '')} · {format_listened(item.get('listened_ms', 0))}"
                f" · {t('stats.plays_count', count=item.get('plays', 0))}"
            )
        else:
            self.setToolTip("")
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = -1
        self.update()
        super().leaveEvent(event)


class StatsPage(Page):
    toast_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(t("stats.title"), t("stats.subtitle"), parent)
        self._path: Path | None = None
        self._period = Period.WEEK
        self._last_refresh = 0.0
        self._summary: dict = {}
        self._build_period()
        self._build_tiles()
        self._build_chart()
        self._build_tops()
        self._build_recent()

    # ------------------------------------------------------------------ build

    def _build_period(self) -> None:
        row = QHBoxLayout()
        row.setSpacing(4)
        holder = QFrame(self)
        holder.setObjectName("soft")
        inner = QHBoxLayout(holder)
        inner.setContentsMargins(4, 4, 4, 4)
        inner.setSpacing(2)
        group = QButtonGroup(self)
        group.setExclusive(True)
        self._period_group = group
        for index, (period, label) in enumerate(
            (
                (Period.DAY, t("stats.period_day")),
                (Period.WEEK, t("stats.period_week")),
                (Period.MONTH, t("stats.period_month")),
                (Period.ALL, t("stats.period_all")),
            )
        ):
            button = QPushButton(label, holder)
            button.setObjectName("segment")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setChecked(period == self._period)
            group.addButton(button, index)
            inner.addWidget(button)
        group.idClicked.connect(self._period_clicked)
        row.addWidget(holder)
        row.addStretch(1)
        self.export_button = QPushButton(t("stats.export"), self)
        self.export_button.setIcon(icons.icon("download", theme.MUTED, 15))
        self.export_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.export_button.clicked.connect(self._export)
        row.addWidget(self.export_button)
        self.add_layout(row)

        self.empty_label = QLabel(t("stats.empty"), self)
        self.empty_label.setObjectName("muted")
        self.empty_label.setVisible(False)
        self.add(self.empty_label)

    def _period_clicked(self, index: int) -> None:
        button = self._period_group.button(index)
        period = button.property("period")
        self._period = Period(period) if period else list(Period)[index]
        self.refresh()

    def _build_tiles(self) -> None:
        row = QHBoxLayout()
        row.setSpacing(10)
        self.tile_time = StatTile(t("stats.time"), "clock", self)
        self.tile_plays = StatTile(t("stats.plays"), "play", self)
        self.tile_tracks = StatTile(t("stats.tracks"), "music", self)
        self.tile_artists = StatTile(t("stats.artists"), "headphones", self)
        for tile in (self.tile_time, self.tile_plays, self.tile_tracks, self.tile_artists):
            row.addWidget(tile, 1)
        self.add_layout(row)

    def _build_chart(self) -> None:
        card = Card(padding=18)
        header = QHBoxLayout()
        title = QLabel(t("stats.chart_title"), card)
        title.setObjectName("h2")
        header.addWidget(title)
        header.addStretch(1)
        self.minimum_hint = QLabel(t("stats.minimum_hint"), card)
        self.minimum_hint.setObjectName("tiny")
        header.addWidget(self.minimum_hint)
        card.add_layout(header)
        self.chart = ActivityChart(card)
        card.add(self.chart)
        self.add(card)

    def _build_tops(self) -> None:
        row = QHBoxLayout()
        row.setSpacing(10)
        self.top_tracks_card, self.top_tracks_box = self._list_card(t("stats.top_tracks"))
        self.top_artists_card, self.top_artists_box = self._list_card(t("stats.top_artists"))
        row.addWidget(self.top_tracks_card, 1)
        row.addWidget(self.top_artists_card, 1)
        self.add_layout(row)

    def _list_card(self, title: str) -> tuple[Card, QVBoxLayout]:
        card = Card(padding=16)
        label = QLabel(title, card)
        label.setObjectName("h2")
        card.add(label)
        box = QVBoxLayout()
        box.setSpacing(2)
        card.add_layout(box)
        return card, box

    def _build_recent(self) -> None:
        card = Card(padding=16)
        title = QLabel(t("stats.recent"), card)
        title.setObjectName("h2")
        card.add(title)
        self.table = QTableWidget(card)
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            [
                t("stats.title_col"),
                t("stats.artist_col"),
                t("stats.album_col"),
                t("stats.source_col"),
                t("stats.when_col"),
            ]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.setWordWrap(False)
        self.table.setMinimumHeight(220)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setColumnWidth(1, 150)
        self.table.setColumnWidth(3, 120)
        self.table.setColumnWidth(4, 110)
        card.add(self.table)
        self.add(card)

    # ------------------------------------------------------------------ data

    def set_stats_path(self, path: Path | None) -> None:
        self._path = path

    def refresh(self) -> None:
        self._last_refresh = time.monotonic()
        path = self._path
        if path is None:
            return
        try:
            data = stats_service.summary(path, self._period)
            daily = stats_service.daily_activity(path, 14)
        except Exception:  # noqa: BLE001
            data = stats_service.empty_summary()
            daily = []
        self._summary = data
        self.chart.set_data(daily)
        self.tile_time.set(format_listened(data["listened_ms"]), t("stats.listened"))
        self.tile_plays.set(str(data["plays"]), t("stats.period_caption"))
        self.tile_tracks.set(str(data["tracks"]), t("stats.period_caption"))
        self.tile_artists.set(str(data["artists"]), t("stats.period_caption"))
        self.empty_label.setVisible(data["plays"] == 0)
        self.export_button.setEnabled(data["plays"] > 0)
        self._fill_tracks(data.get("top_tracks", []))
        self._fill_artists(data.get("top_artists", []))
        self._fill_recent(data.get("recent", []))

    def _clear(self, layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _fill_tracks(self, rows: list[dict]) -> None:
        self._clear(self.top_tracks_box)
        if not rows:
            empty = QLabel(t("stats.empty"), self.top_tracks_card)
            empty.setObjectName("tiny")
            empty.setWordWrap(True)
            self.top_tracks_box.addWidget(empty)
            return
        for index, row in enumerate(rows[:8], 1):
            self.top_tracks_box.addWidget(self._top_row(index, row, artist=row.get("artist", "")))

    def _fill_artists(self, rows: list[dict]) -> None:
        self._clear(self.top_artists_box)
        if not rows:
            empty = QLabel(t("stats.empty"), self.top_artists_card)
            empty.setObjectName("tiny")
            empty.setWordWrap(True)
            self.top_artists_box.addWidget(empty)
            return
        for index, row in enumerate(rows[:8], 1):
            self.top_artists_box.addWidget(
                self._top_row(index, row, artist="", plays=row.get("plays", 0))
            )

    def _top_row(self, index: int, row: dict, *, artist: str, plays: int | None = None) -> QWidget:
        widget = QWidget(self)
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 5, 0, 5)
        layout.setSpacing(9)
        rank = QLabel(str(index), widget)
        rank.setObjectName("tiny")
        rank.setFixedWidth(16)
        rank.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(rank)
        text = QVBoxLayout()
        text.setSpacing(0)
        title = ElidedLabel(row.get("title") or row.get("artist") or "—", widget)
        title.setStyleSheet("font-weight: 600;")
        text.addWidget(title)
        subtitle = ElidedLabel(artist, widget)
        subtitle.setObjectName("tiny")
        if artist:
            text.addWidget(subtitle)
        layout.addLayout(text, 1)
        right = QVBoxLayout()
        right.setSpacing(0)
        count = QLabel(t("stats.plays_count", count=plays if plays is not None else row.get("plays", 0)), widget)
        count.setObjectName("tiny")
        count.setAlignment(Qt.AlignmentFlag.AlignRight)
        right.addWidget(count)
        duration = QLabel(format_listened(row.get("listened_ms", 0)), widget)
        duration.setObjectName("tiny")
        duration.setAlignment(Qt.AlignmentFlag.AlignRight)
        right.addWidget(duration)
        layout.addLayout(right)
        return widget

    def _fill_recent(self, rows: list[dict]) -> None:
        self.table.setRowCount(len(rows[:20]))
        for row_index, row in enumerate(rows[:20]):
            values = (
                row.get("title", ""),
                row.get("artist", ""),
                row.get("album", ""),
                row.get("source", ""),
                datetime.fromtimestamp(row.get("started_at", 0)).strftime("%d.%m %H:%M"),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column == 4:
                    item.setForeground(QColor(theme.MUTED_DIM))
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(row_index, column, item)
        self.table.setVisible(bool(rows))

    def _export(self) -> None:
        if self._path is None:
            return
        default = data_dir() / f"history-{datetime.now():%Y-%m-%d}.csv"
        target, _filter = QFileDialog.getSaveFileName(
            self, t("stats.export"), str(default), "CSV (*.csv)"
        )
        if not target:
            return
        try:
            path = stats_service.export_csv(self._path, Path(target))
        except Exception as error:  # noqa: BLE001
            self.toast_requested.emit(str(error))
            return
        self.toast_requested.emit(t("stats.exported", path=str(path)))

    def update_view(self, view: PlaybackView) -> None:
        if self.isVisible() and time.monotonic() - self._last_refresh > 12:
            self.refresh()

    def on_shown(self) -> None:
        self.refresh()
