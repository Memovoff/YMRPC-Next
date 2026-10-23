"""Переиспользуемые виджеты интерфейса."""

from __future__ import annotations

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..models import PlaybackView
from . import icons, theme


class Card(QFrame):
    def __init__(self, parent: QWidget | None = None, *, accent: bool = False, padding: int = 18):
        super().__init__(parent)
        self.setObjectName("accentCard" if accent else "card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(padding, padding, padding, padding)
        self.body.setSpacing(12)

    def add(self, widget: QWidget, stretch: int = 0) -> QWidget:
        self.body.addWidget(widget, stretch)
        return widget

    def add_layout(self, layout) -> None:
        self.body.addLayout(layout)


class SoftCard(QFrame):
    def __init__(self, parent: QWidget | None = None, padding: int = 14):
        super().__init__(parent)
        self.setObjectName("soft")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(padding, padding, padding, padding)
        self.body.setSpacing(8)


class Page(QWidget):
    """Страница с заголовком и прокручиваемым содержимым."""

    changed = Signal()

    def __init__(self, title: str, subtitle: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self._loading = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(34, 26, 30, 0)
        outer.setSpacing(16)

        header = QWidget(self)
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(3)
        self.title_label = QLabel(title, header)
        self.title_label.setObjectName("h1")
        header_layout.addWidget(self.title_label)
        self.subtitle_label = QLabel(subtitle, header)
        self.subtitle_label.setObjectName("muted")
        self.subtitle_label.setWordWrap(True)
        header_layout.addWidget(self.subtitle_label)
        outer.addWidget(header)

        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        container = QWidget(self.scroll)
        container.setObjectName("transparent")
        self.body = QVBoxLayout(container)
        self.body.setContentsMargins(0, 2, 10, 26)
        self.body.setSpacing(16)
        self.scroll.setWidget(container)
        outer.addWidget(self.scroll, 1)

    def add(self, widget: QWidget, stretch: int = 0) -> QWidget:
        self.body.addWidget(widget, stretch)
        return widget

    def add_layout(self, layout) -> None:
        self.body.addLayout(layout)

    def add_stretch(self) -> None:
        self.body.addStretch(1)

    def notify(self) -> None:
        if not self._loading:
            self.changed.emit()

    def load(self, settings) -> None:
        self._loading = True
        try:
            self._load(settings)
        finally:
            self._loading = False

    def _load(self, settings) -> None:  # pragma: no cover - переопределяется
        pass

    def apply_to(self, settings):
        return settings

    def validate(self) -> str | None:
        return None

    def on_shown(self) -> None:
        pass

    def update_view(self, view: PlaybackView) -> None:
        pass


class ElidedLabel(QLabel):
    def __init__(self, text: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self._full = ""
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.set_full_text(text)

    def set_full_text(self, text: str) -> None:
        self._full = text or ""
        self._refresh()

    def full_text(self) -> str:
        return self._full

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._refresh()

    def _refresh(self) -> None:
        available = max(0, self.width() - 2)
        text = self._full
        if available and self.fontMetrics().horizontalAdvance(text) > available:
            text = self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideRight, available)
        self.setText(text)
        self.setToolTip(self._full if text != self._full else "")


class IconButton(QPushButton):
    def __init__(
        self,
        name: str,
        tooltip: str = "",
        parent: QWidget | None = None,
        *,
        size: int = 34,
        icon_size: int = 18,
        color: str = theme.MUTED,
        object_name: str = "iconButton",
    ):
        super().__init__(parent)
        self.setObjectName(object_name)
        self.setFixedSize(size, size)
        self.setIcon(icons.icon(name, color, icon_size))
        self.setIconSize(QSize(icon_size, icon_size))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if tooltip:
            self.setToolTip(tooltip)

    def set_icon(self, name: str, color: str = theme.MUTED, size: int = 18) -> None:
        self.setIcon(icons.icon(name, color, size))
        self.setIconSize(QSize(size, size))


class Switch(QAbstractButton):
    """Анимированный переключатель вместо стандартного чекбокса."""

    def __init__(self, parent: QWidget | None = None, checked: bool = False):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(44, 24)
        self._offset = 1.0 if checked else 0.0
        self._animation = QPropertyAnimation(self, b"offset", self)
        self._animation.setDuration(140)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate)

    def _get_offset(self) -> float:
        return self._offset

    def _set_offset(self, value: float) -> None:
        self._offset = value
        self.update()

    offset = Property(float, _get_offset, _set_offset)

    def _animate(self, checked: bool) -> None:
        self._animation.stop()
        self._animation.setStartValue(self._offset)
        self._animation.setEndValue(1.0 if checked else 0.0)
        self._animation.start()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(44, 24)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0, 0, self.width(), self.height())
        track = QColor(theme.ACCENT if self.isChecked() else "#2c313c")
        if self.isEnabled() and self.underMouse() and not self.isChecked():
            track = QColor("#363c48")
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(track)
        painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        diameter = self.height() - 6
        x = 3 + self._offset * (self.width() - diameter - 6)
        knob = QRectF(x, 3, diameter, diameter)
        painter.setBrush(QColor("#ffffff" if self.isChecked() else "#c7ccd6"))
        painter.drawEllipse(knob)
        painter.end()


class ToggleRow(QWidget):
    def __init__(
        self,
        title: str,
        hint: str = "",
        parent: QWidget | None = None,
        *,
        checked: bool = False,
    ):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        text = QVBoxLayout()
        text.setSpacing(2)
        self.title = QLabel(title, self)
        self.title.setObjectName("h3")
        text.addWidget(self.title)
        self.hint = QLabel(hint, self)
        self.hint.setObjectName("muted")
        self.hint.setWordWrap(True)
        if hint:
            text.addWidget(self.hint)
        layout.addLayout(text, 1)
        self.switch = Switch(self, checked)
        layout.addWidget(self.switch, 0, Qt.AlignmentFlag.AlignVCenter)

    def set_hint(self, text: str) -> None:
        self.hint.setText(text)
        self.hint.setVisible(bool(text))


class Field(QWidget):
    def __init__(self, label: str, widget: QWidget, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        self.label = QLabel(label, self)
        self.label.setObjectName("tiny")
        layout.addWidget(self.label)
        self.widget = widget
        layout.addWidget(widget)


class SectionHeader(QWidget):
    def __init__(self, title: str, subtitle: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self.title = QLabel(title, self)
        self.title.setObjectName("h2")
        layout.addWidget(self.title)
        if subtitle:
            self.subtitle = QLabel(subtitle, self)
            self.subtitle.setObjectName("muted")
            self.subtitle.setWordWrap(True)
            layout.addWidget(self.subtitle)


class IconBadge(QLabel):
    def __init__(
        self,
        name: str,
        color: str = theme.ACCENT,
        parent: QWidget | None = None,
        *,
        size: int = 38,
    ):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(
            f"background: rgba(255,255,255,.05); border-radius: {size // 3}px;"
        )
        self.setPixmap(icons.pixmap(name, color, int(size * 0.5), dpr=2))


class Pill(QLabel):
    def __init__(
        self,
        text: str = "",
        color: str = theme.MUTED,
        parent: QWidget | None = None,
        *,
        background: str | None = None,
    ):
        super().__init__(text, parent)
        self.setObjectName("chip")
        self.setTextFormat(Qt.TextFormat.PlainText)
        self._background = background
        self.set_color(color)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

    def set_color(self, color: str, background: str | None = None) -> None:
        if background is not None:
            self._background = background
        if self._background is None:
            self._background = _alpha(color, 0.12)
        self.setStyleSheet(
            "QLabel#chip {"
            f"color: {color}; background: {self._background};"
            "border-radius: 9px; padding: 3px 9px; font-size: 11px; font-weight: 600;"
            "}"
        )

    def set_text(self, text: str, color: str | None = None) -> None:
        self.setText(text)
        if color:
            self._background = None
            self.set_color(color)


class OptionCard(QAbstractButton):
    """Кликабельная карточка выбора с заголовком и описанием."""

    def __init__(self, title: str, hint: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(89)
        self._hover = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(48, 13, 14, 13)
        layout.setSpacing(4)
        self.title_label = QLabel(title, self)
        self.title_label.setObjectName("h3")
        self.title_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.hint_label = QLabel(hint, self)
        self.hint_label.setObjectName("muted")
        self.hint_label.setWordWrap(True)
        self.hint_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(self.title_label)
        layout.addWidget(self.hint_label)

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        checked = self.isChecked()
        background = QColor(theme.ACCENT)
        background.setAlpha(28 if checked else (24 if self._hover else 20))
        if not checked:
            background = QColor(theme.SURFACE_2)
        border = QColor(theme.ACCENT if checked else (theme.SURFACE_3 if self._hover else theme.BORDER))
        painter.setPen(QPen(border, 1.0))
        painter.setBrush(background)
        painter.drawRoundedRect(rect, 12, 12)

        center = QPointF(24, 27)
        painter.setPen(QPen(QColor(theme.ACCENT if checked else theme.MUTED_DIM), 1.6))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(center, 8.5, 8.5)
        if checked:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.ACCENT))
            painter.drawEllipse(center, 4.4, 4.4)
        painter.end()


class CoverWidget(QWidget):
    def __init__(self, size: int = 132, radius: int = 14, parent: QWidget | None = None):
        super().__init__(parent)
        self._size = size
        self._radius = radius
        self._pixmap = QPixmap()
        self._path = ""
        self.setFixedSize(size, size)
        self.setObjectName("cover")

    def set_path(self, path: str | None) -> None:
        path = path or ""
        if path == self._path:
            return
        self._path = path
        self._pixmap = QPixmap(path) if path else QPixmap()
        self.update()

    def set_pixmap(self, image: QPixmap) -> None:
        self._path = ""
        self._pixmap = image
        self.update()

    def resizeEvent(self, event) -> None:  # noqa: N802
        self._size = min(self.width(), self.height())
        super().resizeEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = QRectF(1, 1, self.width() - 2, self.height() - 2)
        path = QPainterPath()
        path.addRoundedRect(rect, self._radius, self._radius)
        painter.setClipPath(path)
        if not self._pixmap.isNull():
            image = self._pixmap.scaled(
                int(rect.width()),
                int(rect.height()),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = rect.x() + (rect.width() - image.width()) / 2
            y = rect.y() + (rect.height() - image.height()) / 2
            painter.drawPixmap(int(x), int(y), image)
        else:
            gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
            gradient.setColorAt(0, QColor("#2b2610"))
            gradient.setColorAt(1, QColor("#191b21"))
            painter.fillRect(rect, gradient)
            note = icons.pixmap("music", theme.ACCENT, int(rect.width() * 0.32), dpr=2)
            note.setDevicePixelRatio(1)
            scale = int(rect.width() * 0.32)
            painter.setOpacity(0.9)
            painter.drawPixmap(
                int(rect.center().x() - note.width() / 2),
                int(rect.center().y() - note.height() / 2),
                note.scaled(scale, scale, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation),
            )
            painter.setOpacity(1.0)
        painter.setClipping(False)
        painter.setPen(QPen(QColor(255, 255, 255, 22), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, self._radius, self._radius)
        painter.end()


class SeekBar(QWidget):
    """Полоса прогресса с перемоткой по клику."""

    seek_requested = Signal(float)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        height: int = 6,
        interactive: bool = True,
    ):
        super().__init__(parent)
        self._position = 0.0
        self._duration = 0.0
        self._hover = False
        self._interactive = interactive
        self._bar_height = max(2, height - 2)
        self.setFixedHeight(height)
        self.setMouseTracking(True)
        if interactive:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    @property
    def position(self) -> float:
        return self._position

    def set_state(self, position: float, duration: float) -> None:
        self._position = max(0.0, position)
        self._duration = max(0.0, duration)
        self.update()

    def _ratio(self) -> float:
        if self._duration <= 0:
            return 0.0
        return min(1.0, max(0.0, self._position / self._duration))

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        top = (self.height() - self._bar_height) / 2
        track = QRectF(0, top, self.width(), self._bar_height)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 26))
        painter.drawRoundedRect(track, self._bar_height / 2, self._bar_height / 2)
        ratio = self._ratio()
        if ratio > 0:
            fill = QRectF(0, top, max(self._bar_height, self.width() * ratio), self._bar_height)
            painter.setBrush(QColor(theme.ACCENT))
            painter.drawRoundedRect(fill, self._bar_height / 2, self._bar_height / 2)
        if self._interactive and self._hover and self._duration > 0:
            x = min(self.width() - 1, self.width() * ratio)
            painter.setBrush(QColor("#ffffff"))
            painter.drawEllipse(QPointF(x, self.height() / 2), 4.4, 4.4)
        painter.end()

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self._interactive and self._duration > 0 and event.button() == Qt.MouseButton.LeftButton:
            ratio = min(1.0, max(0.0, event.position().x() / max(1, self.width())))
            self.seek_requested.emit(ratio * self._duration)
        super().mousePressEvent(event)


class StatTile(Card):
    def __init__(self, title: str, icon_name: str = "stats", parent: QWidget | None = None):
        super().__init__(parent, padding=15)
        self.setMinimumHeight(108)
        top = QHBoxLayout()
        top.setSpacing(8)
        label = QLabel(title, self)
        label.setObjectName("muted")
        top.addWidget(label, 1)
        badge = IconBadge(icon_name, theme.ACCENT, self, size=30)
        top.addWidget(badge)
        self.body.addLayout(top)
        self.value = QLabel("—", self)
        self.value.setObjectName("value")
        self.value.setTextFormat(Qt.TextFormat.PlainText)
        self.body.addWidget(self.value)
        self.caption = QLabel("", self)
        self.caption.setObjectName("tiny")
        self.caption.setTextFormat(Qt.TextFormat.PlainText)
        self.body.addWidget(self.caption)

    def set(self, value: str, caption: str = "") -> None:
        self.value.setText(value)
        self.caption.setText(caption)


class Banner(QFrame):
    """Плашка с новостью или обновлением."""

    action_clicked = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("soft")
        self.setVisible(False)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 12, 10)
        layout.setSpacing(12)
        self.badge = IconBadge("download", theme.ACCENT, self, size=32)
        layout.addWidget(self.badge)
        text = QVBoxLayout()
        text.setSpacing(1)
        self.title = QLabel("", self)
        self.title.setObjectName("h3")
        text.addWidget(self.title)
        self.detail = QLabel("", self)
        self.detail.setObjectName("tiny")
        self.detail.setTextFormat(Qt.TextFormat.PlainText)
        text.addWidget(self.detail)
        layout.addLayout(text, 1)
        self.button = QPushButton("", self)
        self.button.setObjectName("primary")
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.clicked.connect(self.action_clicked)
        layout.addWidget(self.button)

    def show_banner(self, title: str, detail: str, action: str) -> None:
        self.title.setText(title)
        self.detail.setText(detail)
        self.button.setText(action)
        self.setVisible(True)


def format_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02}:{seconds:02}"
    return f"{minutes}:{seconds:02}"


def format_listened(milliseconds: int) -> str:
    minutes = int(milliseconds / 60000)
    if minutes < 60:
        return f"{minutes} мин"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours} ч {minutes:02d} мин"
    days, hours = divmod(hours, 24)
    return f"{days} д {hours} ч"


def _alpha(color: str, alpha: float) -> str:
    value = QColor(color)
    return f"rgba({value.red()}, {value.green()}, {value.blue()}, {alpha})"


def apply_font(widget: QWidget, size: int | None = None, weight: QFont.Weight | None = None) -> None:
    font = widget.font()
    if size is not None:
        font.setPointSize(size)
    if weight is not None:
        font.setWeight(weight)
    widget.setFont(font)
