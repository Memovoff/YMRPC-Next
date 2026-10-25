"""Регрессия геометрии: страницы не должны прокручиваться по горизонтали.

Файл назван так, чтобы PySide6 загружался раньше winrt: на Windows эти
библиотеки конфликтуют при обратном порядке импорта.
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QWidget

from ymrpc.ui import theme
from ymrpc.ui.pages.app import AppPage
from ymrpc.ui.pages.discord import DiscordPage
from ymrpc.ui.pages.overlay import OverlayPage
from ymrpc.ui.pages.overview import OverviewPage
from ymrpc.ui.pages.sources import SourcesPage
from ymrpc.ui.pages.stats import StatsPage
from ymrpc.ui.widgets import ResponsiveGrid

# Ширина окна 1020/1180 минус боковая панель.
PAGE_WIDTHS = (792, 952)
PAGES = (OverviewPage, SourcesPage, DiscordPage, OverlayPage, StatsPage, AppPage)


def _use_real_ui_font(app: QApplication) -> None:
    """Offscreen QPA не находит Segoe UI сам, из-за чего метрики текста раздуваются."""
    candidates = (
        (Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "segoeui.ttf", "Segoe UI"),
        (Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"), "DejaVu Sans"),
        (Path("/usr/share/fonts/TTF/DejaVuSans.ttf"), "DejaVu Sans"),
    )
    for path, fallback in candidates:
        if not path.exists():
            continue
        font_id = QFontDatabase.addApplicationFont(str(path))
        families = QFontDatabase.applicationFontFamilies(font_id)
        font = QFont(families[0] if families else fallback)
        font.setPointSizeF(9.0)
        app.setFont(font)
        return


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    _use_real_ui_font(instance)
    theme.apply(instance)
    yield instance


@pytest.mark.parametrize("page_type", PAGES)
@pytest.mark.parametrize("width", PAGE_WIDTHS)
def test_pages_fit_without_horizontal_scroll(app, page_type, width):
    page = page_type()
    page.resize(width, 640)
    page.show()
    app.processEvents()
    try:
        assert page.scroll.horizontalScrollBar().maximum() == 0
    finally:
        page.close()


def test_responsive_grid_reflows(app):
    grid = ResponsiveGrid(breakpoints=((820, 4), (520, 2), (0, 1)))
    tiles = []
    for _ in range(4):
        tile = QWidget()
        tiles.append(tile)
        grid.add(tile)
    grid.show()
    try:
        grid.resize(900, 120)
        app.processEvents()
        assert len({tile.x() for tile in tiles}) == 4

        grid.resize(600, 240)
        app.processEvents()
        assert len({tile.x() for tile in tiles}) == 2

        grid.resize(400, 480)
        app.processEvents()
        assert len({tile.x() for tile in tiles}) == 1
    finally:
        grid.close()
