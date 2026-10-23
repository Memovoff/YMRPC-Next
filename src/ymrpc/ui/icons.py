"""Векторные иконки, нарисованные QPainter (без внешних ресурсов)."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from ..constants import resource_path
from . import theme


def pixmap(name: str, color: str = theme.TEXT, size: int = 20, dpr: int = 2) -> QPixmap:
    physical = max(1, int(size * dpr))
    image = QPixmap(physical, physical)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(physical / 24.0, physical / 24.0)
    _draw(painter, name, QColor(color))
    painter.end()
    image.setDevicePixelRatio(dpr)
    return image


def icon(name: str, color: str = theme.TEXT, size: int = 20) -> QIcon:
    return QIcon(pixmap(name, color, size))


def nav_icon(name: str, size: int = 19) -> QIcon:
    result = QIcon()
    result.addPixmap(pixmap(name, theme.MUTED, size), QIcon.Mode.Normal, QIcon.State.Off)
    result.addPixmap(pixmap(name, theme.ACCENT, size), QIcon.Mode.Normal, QIcon.State.On)
    result.addPixmap(pixmap(name, theme.TEXT, size), QIcon.Mode.Active, QIcon.State.Off)
    result.addPixmap(pixmap(name, theme.ACCENT, size), QIcon.Mode.Active, QIcon.State.On)
    result.addPixmap(pixmap(name, theme.MUTED_DIM, size), QIcon.Mode.Disabled, QIcon.State.Off)
    return result


def app_icon() -> QIcon:
    for name in ("icon.ico", "icon.png"):
        path = resource_path(name)
        if path.exists():
            loaded = QIcon(str(path))
            if not loaded.isNull():
                return loaded
    return QIcon(pixmap("music", theme.ACCENT, 64, dpr=1))


def logo_pixmap(size: int = 38) -> QPixmap:
    physical = size * 2
    image = QPixmap(physical, physical)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(physical / 24.0, physical / 24.0)
    path = QPainterPath()
    path.addRoundedRect(QRectF(1.5, 1.5, 21, 21), 6.5, 6.5)
    painter.fillPath(path, QColor(theme.ACCENT))
    _draw(painter, "music", QColor("#141414"), width=2.2)
    painter.end()
    image.setDevicePixelRatio(2)
    return image


# ---------------------------------------------------------------------- drawing


def _draw(painter: QPainter, name: str, color: QColor, width: float = 1.8) -> None:
    pen = QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    method = _ICONS.get(name, _ICONS["music"])
    method(painter, color)


def _fill(painter: QPainter, color: QColor, path: QPainterPath) -> None:
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawPath(path)


def _round_poly(points: list[tuple[float, float]], close: bool = True) -> QPainterPath:
    path = QPainterPath()
    path.moveTo(*points[0])
    for point in points[1:]:
        path.lineTo(*point)
    if close:
        path.closeSubpath()
    return path


def _icon_overview(painter: QPainter, color: QColor) -> None:
    painter.drawPath(
        _round_poly([(3.2, 10.4), (12, 3.4), (20.8, 10.4)], close=False)
    )
    painter.drawPath(
        _round_poly([(5.4, 9.4), (5.4, 20.2), (18.6, 20.2), (18.6, 9.4)], close=False)
    )
    painter.drawRoundedRect(QRectF(10.0, 14.3, 4.0, 5.9), 1.2, 1.2)


def _icon_sources(painter: QPainter, color: QColor) -> None:
    painter.drawEllipse(QRectF(4.0, 15.1, 5.3, 4.4))
    painter.drawLine(QPointF(9.3, 17.3), QPointF(9.3, 5.8))
    path = QPainterPath(QPointF(9.3, 5.8))
    path.cubicTo(13.0, 5.0, 16.4, 7.4, 19.4, 10.2)
    painter.drawPath(path)
    painter.drawLine(QPointF(16.6, 9.9), QPointF(16.6, 15.8))
    painter.drawEllipse(QRectF(11.8, 14.6, 4.8, 4.0))


def _icon_discord(painter: QPainter, color: QColor) -> None:
    path = QPainterPath()
    path.addRoundedRect(QRectF(3.0, 4.4, 18.0, 13.4), 4.4, 4.4)
    painter.drawPath(path)
    painter.drawLine(QPointF(7.2, 17.4), QPointF(6.2, 21.0))
    painter.drawLine(QPointF(6.2, 21.0), QPointF(10.6, 17.5))
    painter.setBrush(color)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(QRectF(8.5, 9.8, 1.7, 1.7))
    painter.drawEllipse(QRectF(13.8, 9.8, 1.7, 1.7))


def _icon_overlay(painter: QPainter, color: QColor) -> None:
    painter.drawRoundedRect(QRectF(3.0, 4.8, 12.4, 10.2), 2.6, 2.6)
    painter.setBrush(QColor(theme.SURFACE))
    painter.drawRoundedRect(QRectF(8.6, 9.0, 12.4, 10.2), 2.6, 2.6)


def _icon_stats(painter: QPainter, color: QColor) -> None:
    pen = painter.pen()
    pen.setWidthF(3.0)
    painter.setPen(pen)
    painter.drawLine(QPointF(5.4, 20.2), QPointF(5.4, 13.8))
    painter.drawLine(QPointF(12.0, 20.2), QPointF(12.0, 8.2))
    painter.drawLine(QPointF(18.6, 20.2), QPointF(18.6, 4.0))


def _icon_app(painter: QPainter, color: QColor) -> None:
    painter.drawEllipse(QRectF(9.1, 9.1, 5.8, 5.8))
    for index in range(8):
        angle = math.radians(index * 45)
        inner = 7.0
        outer = 9.8
        painter.drawLine(
            QPointF(12 + math.cos(angle) * inner, 12 + math.sin(angle) * inner),
            QPointF(12 + math.cos(angle) * outer, 12 + math.sin(angle) * outer),
        )


def _icon_music(painter: QPainter, color: QColor) -> None:
    painter.drawEllipse(QRectF(4.6, 14.6, 5.6, 4.6))
    painter.drawLine(QPointF(10.2, 16.9), QPointF(10.2, 4.6))
    path = QPainterPath(QPointF(10.2, 4.6))
    path.cubicTo(14.2, 4.0, 17.6, 6.4, 20.0, 9.6)
    painter.drawPath(path)
    painter.drawLine(QPointF(17.0, 8.9), QPointF(17.0, 15.1))
    painter.drawEllipse(QRectF(12.4, 14.2, 4.6, 3.9))


def _icon_play(painter: QPainter, color: QColor) -> None:
    _fill(painter, color, _round_poly([(7.4, 4.8), (19.0, 12.0), (7.4, 19.2)]))


def _icon_pause(painter: QPainter, color: QColor) -> None:
    _fill(painter, color, _round_poly([(6.2, 4.6), (10.1, 4.6), (10.1, 19.4), (6.2, 19.4)]))
    _fill(painter, color, _round_poly([(13.9, 4.6), (17.8, 4.6), (17.8, 19.4), (13.9, 19.4)]))


def _icon_next(painter: QPainter, color: QColor) -> None:
    _fill(painter, color, _round_poly([(4.6, 5.0), (13.4, 12.0), (4.6, 19.0)]))
    _fill(painter, color, _round_poly([(14.6, 5.0), (16.8, 5.0), (16.8, 19.0), (14.6, 19.0)]))


def _icon_prev(painter: QPainter, color: QColor) -> None:
    _fill(painter, color, _round_poly([(19.4, 5.0), (10.6, 12.0), (19.4, 19.0)]))
    _fill(painter, color, _round_poly([(7.2, 5.0), (9.4, 5.0), (9.4, 19.0), (7.2, 19.0)]))


def _icon_lyrics(painter: QPainter, color: QColor) -> None:
    for index, right in enumerate((20.0, 16.4, 19.4, 13.6)):
        y = 5.2 + index * 4.2
        painter.drawLine(QPointF(4.0, y), QPointF(right, y))


def _icon_close(painter: QPainter, color: QColor) -> None:
    painter.drawLine(QPointF(6.2, 6.2), QPointF(17.8, 17.8))
    painter.drawLine(QPointF(17.8, 6.2), QPointF(6.2, 17.8))


def _icon_minimize(painter: QPainter, color: QColor) -> None:
    painter.drawLine(QPointF(5.2, 12.0), QPointF(18.8, 12.0))


def _icon_external(painter: QPainter, color: QColor) -> None:
    painter.drawPath(_round_poly([(13.4, 5.0), (5.0, 5.0), (5.0, 19.0), (19.0, 19.0), (19.0, 10.6)], close=False))
    painter.drawLine(QPointF(11.2, 12.8), QPointF(20.0, 4.0))
    painter.drawPath(_round_poly([(14.8, 4.0), (20.0, 4.0), (20.0, 9.2)], close=False))


def _icon_folder(painter: QPainter, color: QColor) -> None:
    path = QPainterPath(QPointF(3.2, 6.4))
    path.lineTo(9.2, 6.4)
    path.lineTo(11.2, 8.6)
    path.lineTo(20.8, 8.6)
    path.lineTo(20.8, 19.2)
    path.lineTo(3.2, 19.2)
    path.closeSubpath()
    painter.drawPath(path)


def _icon_refresh(painter: QPainter, color: QColor) -> None:
    painter.drawArc(QRectF(4.6, 4.6, 14.8, 14.8), 35 * 16, 290 * 16)
    painter.drawPath(_round_poly([(15.6, 3.4), (19.6, 5.4), (17.0, 8.8)], close=False))
    painter.drawPath(_round_poly([(8.4, 20.6), (4.4, 18.6), (7.0, 15.2)], close=False))


def _icon_download(painter: QPainter, color: QColor) -> None:
    painter.drawLine(QPointF(12.0, 3.8), QPointF(12.0, 15.4))
    painter.drawPath(_round_poly([(7.2, 10.6), (12.0, 15.4), (16.8, 10.6)], close=False))
    painter.drawPath(_round_poly([(4.6, 19.4), (19.4, 19.4)], close=False))


def _icon_check(painter: QPainter, color: QColor) -> None:
    painter.drawPath(_round_poly([(5.0, 12.4), (10.0, 17.2), (19.2, 6.8)], close=False))


def _icon_plus(painter: QPainter, color: QColor) -> None:
    painter.drawLine(QPointF(12.0, 5.0), QPointF(12.0, 19.0))
    painter.drawLine(QPointF(5.0, 12.0), QPointF(19.0, 12.0))


def _icon_trash(painter: QPainter, color: QColor) -> None:
    painter.drawLine(QPointF(4.6, 6.8), QPointF(19.4, 6.8))
    painter.drawPath(_round_poly([(9.0, 6.8), (9.0, 4.4), (15.0, 4.4), (15.0, 6.8)], close=False))
    painter.drawPath(_round_poly([(6.4, 6.8), (7.4, 20.0), (16.6, 20.0), (17.6, 6.8)], close=False))
    painter.drawLine(QPointF(10.4, 10.2), QPointF(10.8, 16.8))
    painter.drawLine(QPointF(13.6, 10.2), QPointF(13.2, 16.8))


def _icon_logout(painter: QPainter, color: QColor) -> None:
    painter.drawPath(_round_poly([(10.0, 4.2), (4.8, 4.2), (4.8, 19.8), (10.0, 19.8)], close=False))
    painter.drawLine(QPointF(10.2, 12.0), QPointF(20.0, 12.0))
    painter.drawPath(_round_poly([(16.0, 8.0), (20.0, 12.0), (16.0, 16.0)], close=False))


def _icon_login(painter: QPainter, color: QColor) -> None:
    painter.drawPath(_round_poly([(14.0, 4.2), (19.2, 4.2), (19.2, 19.8), (14.0, 19.8)], close=False))
    painter.drawLine(QPointF(4.0, 12.0), QPointF(13.8, 12.0))
    painter.drawPath(_round_poly([(9.8, 8.0), (13.8, 12.0), (9.8, 16.0)], close=False))


def _icon_copy(painter: QPainter, color: QColor) -> None:
    painter.drawRoundedRect(QRectF(8.2, 8.2, 11.6, 11.6), 2.2, 2.2)
    painter.drawPath(_round_poly([(5.2, 15.8), (4.2, 15.8), (4.2, 4.2), (15.8, 4.2), (15.8, 5.2)], close=False))


def _icon_eye(painter: QPainter, color: QColor) -> None:
    path = QPainterPath(QPointF(2.8, 12.0))
    path.cubicTo(6.2, 6.4, 17.8, 6.4, 21.2, 12.0)
    path.cubicTo(17.8, 17.6, 6.2, 17.6, 2.8, 12.0)
    painter.drawPath(path)
    painter.drawEllipse(QRectF(9.4, 9.4, 5.2, 5.2))


def _icon_eye_off(painter: QPainter, color: QColor) -> None:
    _icon_eye(painter, color)
    painter.drawLine(QPointF(4.0, 4.0), QPointF(20.0, 20.0))


def _icon_clock(painter: QPainter, color: QColor) -> None:
    painter.drawEllipse(QRectF(3.8, 3.8, 16.4, 16.4))
    painter.drawLine(QPointF(12.0, 7.2), QPointF(12.0, 12.0))
    painter.drawLine(QPointF(12.0, 12.0), QPointF(15.4, 14.4))


def _icon_headphones(painter: QPainter, color: QColor) -> None:
    painter.drawArc(QRectF(4.0, 4.4, 16.0, 15.0), 0, 180 * 16)
    painter.drawRoundedRect(QRectF(4.0, 12.6, 3.6, 7.0), 1.6, 1.6)
    painter.drawRoundedRect(QRectF(16.4, 12.6, 3.6, 7.0), 1.6, 1.6)


def _icon_pin(painter: QPainter, color: QColor) -> None:
    painter.drawLine(QPointF(8.4, 4.4), QPointF(15.6, 4.4))
    painter.drawLine(QPointF(9.2, 4.4), QPointF(9.2, 9.6))
    painter.drawLine(QPointF(14.8, 4.4), QPointF(14.8, 9.6))
    painter.drawPath(_round_poly([(6.6, 9.6), (17.4, 9.6), (14.8, 14.4), (9.2, 14.4)], close=False))
    painter.drawLine(QPointF(12.0, 14.4), QPointF(12.0, 20.0))


def _icon_warning(painter: QPainter, color: QColor) -> None:
    painter.drawPath(_round_poly([(12.0, 3.6), (21.2, 20.0), (2.8, 20.0)]))
    painter.drawLine(QPointF(12.0, 9.0), QPointF(12.0, 14.0))
    painter.setBrush(color)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(QRectF(11.1, 16.0, 1.8, 1.8))


def _icon_dot(painter: QPainter, color: QColor) -> None:
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawEllipse(QRectF(7.2, 7.2, 9.6, 9.6))


def _icon_chevron_down(painter: QPainter, color: QColor) -> None:
    painter.drawPath(_round_poly([(6.0, 9.0), (12.0, 15.0), (18.0, 9.0)], close=False))


def _icon_more(painter: QPainter, color: QColor) -> None:
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    for x in (5.6, 12.0, 18.4):
        painter.drawEllipse(QRectF(x - 1.4, 10.6, 2.8, 2.8))


_ICONS = {
    "overview": _icon_overview,
    "sources": _icon_sources,
    "discord": _icon_discord,
    "overlay": _icon_overlay,
    "stats": _icon_stats,
    "app": _icon_app,
    "music": _icon_music,
    "play": _icon_play,
    "pause": _icon_pause,
    "next": _icon_next,
    "prev": _icon_prev,
    "lyrics": _icon_lyrics,
    "close": _icon_close,
    "minimize": _icon_minimize,
    "external": _icon_external,
    "folder": _icon_folder,
    "refresh": _icon_refresh,
    "download": _icon_download,
    "check": _icon_check,
    "plus": _icon_plus,
    "trash": _icon_trash,
    "logout": _icon_logout,
    "login": _icon_login,
    "copy": _icon_copy,
    "eye": _icon_eye,
    "eye_off": _icon_eye_off,
    "clock": _icon_clock,
    "headphones": _icon_headphones,
    "pin": _icon_pin,
    "warning": _icon_warning,
    "dot": _icon_dot,
    "chevron_down": _icon_chevron_down,
    "more": _icon_more,
}
