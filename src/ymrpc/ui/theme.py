"""Тёмная тема, палитра и оформление Qt-приложения."""

from __future__ import annotations

import ctypes
import sys

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QWidget

BG = "#0e0f13"
SIDEBAR = "#0a0b0f"
SURFACE = "#16181f"
SURFACE_2 = "#1d2029"
SURFACE_3 = "#252935"
BORDER = "#272b35"
BORDER_SOFT = "#1f222b"
TEXT = "#f4f5f7"
MUTED = "#969dab"
MUTED_DIM = "#6c7382"
ACCENT = "#ffcc00"
ACCENT_HOVER = "#ffd84d"
ACCENT_PRESSED = "#d9ad00"
ACCENT_SOFT = "rgba(255, 204, 0, 0.12)"
GREEN = "#3ddc84"
RED = "#ff6b6b"
BLUE = "#69a8ff"
ORANGE = "#ffa94d"

# Layout tokens. Keep spacing and widths in one place so pages stay aligned.
PAGE_MAX_WIDTH = 1040
PAGE_GAP = 16
PAGE_MARGIN_X = 32
PAGE_MARGIN_TOP = 24
PAGE_MARGIN_BOTTOM = 32
FOOTER_HEIGHT = 48
SIDEBAR_WIDTH = 228


def palette() -> QPalette:
    result = QPalette()
    result.setColor(QPalette.ColorRole.Window, QColor(BG))
    result.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    result.setColor(QPalette.ColorRole.Base, QColor("#101218"))
    result.setColor(QPalette.ColorRole.AlternateBase, QColor(SURFACE))
    result.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    result.setColor(QPalette.ColorRole.Button, QColor(SURFACE_2))
    result.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT))
    result.setColor(QPalette.ColorRole.BrightText, QColor("#ffffff"))
    result.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT))
    result.setColor(QPalette.ColorRole.HighlightedText, QColor("#121212"))
    result.setColor(QPalette.ColorRole.ToolTipBase, QColor(SURFACE_2))
    result.setColor(QPalette.ColorRole.ToolTipText, QColor(TEXT))
    result.setColor(QPalette.ColorRole.PlaceholderText, QColor(MUTED_DIM))
    result.setColor(QPalette.ColorRole.Link, QColor(ACCENT))
    for group in (QPalette.ColorGroup.Disabled,):
        result.setColor(group, QPalette.ColorRole.Text, QColor(MUTED_DIM))
        result.setColor(group, QPalette.ColorRole.WindowText, QColor(MUTED_DIM))
        result.setColor(group, QPalette.ColorRole.ButtonText, QColor(MUTED_DIM))
    return result


def apply(app: QApplication) -> None:
    app.setStyle("Fusion")
    app.setPalette(palette())
    app.setStyleSheet(stylesheet())


def stylesheet() -> str:
    return f"""
    * {{ outline: none; }}
    QWidget {{
        color: {TEXT};
        font-family: "Segoe UI Variable Text", "Segoe UI", "Inter", sans-serif;
        font-size: 13px;
    }}
    QMainWindow, QDialog, QWidget#root {{ background: {BG}; }}
    QWidget#transparent {{ background: transparent; }}
    QWidget#sidebar {{ background: {SIDEBAR}; border-right: 1px solid {BORDER_SOFT}; }}
    QLabel {{ background: transparent; }}
    QLabel#h1 {{ font-family: "Segoe UI Variable Display", "Segoe UI", sans-serif; font-size: 28px; font-weight: 700; color: {TEXT}; }}
    QLabel#h2 {{ font-size: 18px; font-weight: 600; color: {TEXT}; }}
    QLabel#h3 {{ font-size: 14px; font-weight: 600; color: {TEXT}; }}
    QLabel#muted {{ color: {MUTED}; }}
    QLabel#tiny {{ color: {MUTED_DIM}; font-size: 11px; }}
    QLabel#value {{ font-size: 25px; font-weight: 700; color: {TEXT}; }}
    QLabel#accent {{ color: {ACCENT}; }}
    QLabel#danger {{ color: {RED}; }}
    QLabel#success {{ color: {GREEN}; }}
    QLabel#link {{ color: {ACCENT}; }}
    QLabel#mono {{ font-family: "Cascadia Mono", "Consolas", monospace; font-size: 11px; color: {MUTED}; }}

    QFrame#card {{
        background: {SURFACE};
        border: 1px solid {BORDER};
        border-radius: 16px;
    }}
    QFrame#accentCard {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 #1d1c18, stop:0.52 #181a20, stop:1 {SURFACE});
        border: 1px solid #353327;
        border-radius: 18px;
    }}
    QFrame#soft {{
        background: {SURFACE_2};
        border: 1px solid {BORDER_SOFT};
        border-radius: 12px;
    }}
    QFrame#footer {{ background: {BG}; border-top: 1px solid {BORDER_SOFT}; }}
    QFrame#separator {{ background: {BORDER_SOFT}; max-height: 1px; border: none; }}

    QToolButton#navButton {{
        border: none;
        border-left: 3px solid transparent;
        border-radius: 10px;
        padding: 9px 12px 9px 9px;
        text-align: left;
        color: {MUTED};
        font-size: 13px;
        font-weight: 600;
    }}
    QToolButton#navButton:hover {{ background: {SURFACE}; color: {TEXT}; }}
    QToolButton#navButton:checked {{
        background: {SURFACE};
        color: {TEXT};
        border-left: 3px solid {ACCENT};
    }}

    QPushButton {{
        background: {SURFACE_3};
        border: 1px solid {BORDER};
        border-radius: 9px;
        padding: 8px 14px;
        color: {TEXT};
        font-weight: 600;
    }}
    QPushButton:hover {{ background: #2c3140; border-color: #343a48; }}
    QPushButton:pressed {{ background: #222632; }}
    QPushButton:disabled {{ background: {SURFACE_2}; color: {MUTED_DIM}; border-color: {BORDER_SOFT}; }}
    QPushButton#primary {{
        background: {ACCENT};
        border: 1px solid {ACCENT};
        color: #141414;
        padding: 9px 18px;
    }}
    QPushButton#primary:hover {{ background: {ACCENT_HOVER}; border-color: {ACCENT_HOVER}; }}
    QPushButton#primary:pressed {{ background: {ACCENT_PRESSED}; border-color: {ACCENT_PRESSED}; }}
    QPushButton#primary:disabled {{ background: #3a351d; border-color: #3a351d; color: {MUTED_DIM}; }}
    QPushButton#ghost {{ background: transparent; border: 1px solid transparent; color: {MUTED}; }}
    QPushButton#ghost:hover {{ background: {SURFACE_2}; color: {TEXT}; }}
    QPushButton#danger {{ background: rgba(255,107,107,.12); border: 1px solid rgba(255,107,107,.28); color: {RED}; }}
    QPushButton#danger:hover {{ background: rgba(255,107,107,.2); }}
    QPushButton#tile {{
        background: {SURFACE};
        border: 1px solid {BORDER};
        border-radius: 13px;
        padding: 14px;
        text-align: left;
        font-weight: 600;
        color: {TEXT};
    }}
    QPushButton#tile:hover {{ background: {SURFACE_2}; border-color: #353b49; }}
    QPushButton#tile:checked {{ background: {ACCENT_SOFT}; border-color: rgba(255,204,0,.38); color: {TEXT}; }}
    QPushButton#iconButton {{
        background: transparent;
        border: none;
        border-radius: 9px;
        padding: 0;
    }}
    QPushButton#iconButton:hover {{ background: {SURFACE_2}; }}
    QPushButton#iconButton:pressed {{ background: {SURFACE_3}; }}
    QPushButton#playButton {{
        background: {ACCENT};
        border: none;
        border-radius: 22px;
        padding: 0;
    }}
    QPushButton#playButton:hover {{ background: {ACCENT_HOVER}; }}
    QPushButton#playButton:pressed {{ background: {ACCENT_PRESSED}; }}
    QPushButton#playButton:disabled {{ background: #3a351d; }}
    QPushButton#segment {{
        background: transparent;
        border: 1px solid transparent;
        border-radius: 8px;
        padding: 6px 14px;
        color: {MUTED};
        font-weight: 600;
    }}
    QPushButton#segment:hover {{ background: {SURFACE_2}; color: {TEXT}; }}
    QPushButton#segment:checked {{ background: {SURFACE_3}; color: {TEXT}; border-color: {BORDER}; }}

    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit {{
        background: #101218;
        border: 1px solid {BORDER};
        border-radius: 9px;
        padding: 7px 10px;
        min-height: 20px;
        selection-background-color: {ACCENT};
        selection-color: #111111;
    }}
    QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {{ border-color: #363c4a; }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QPlainTextEdit:focus {{ border-color: {ACCENT}; }}
    QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{ color: {MUTED_DIM}; background: #0d0f13; }}
    QComboBox {{ padding-right: 26px; }}
    QComboBox::drop-down {{ border: none; width: 26px; }}
    QComboBox::down-arrow {{ width: 9px; height: 9px; }}
    QComboBox QAbstractItemView {{
        background: {SURFACE_2};
        border: 1px solid {BORDER};
        border-radius: 8px;
        padding: 4px;
        selection-background-color: {SURFACE_3};
        selection-color: {TEXT};
        outline: none;
    }}
    QSpinBox::up-button, QDoubleSpinBox::up-button {{ width: 16px; border: none; }}
    QSpinBox::down-button, QDoubleSpinBox::down-button {{ width: 16px; border: none; }}
    QCheckBox {{ color: {TEXT}; spacing: 8px; }}
    QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 5px; border: 1px solid {BORDER}; background: #101218; }}
    QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}

    QScrollArea {{ background: transparent; border: none; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: #2c313c; min-height: 28px; border-radius: 4px; }}
    QScrollBar::handle:vertical:hover {{ background: #3a4150; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
    QScrollBar:horizontal {{ height: 0; }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

    QListWidget {{ background: transparent; border: none; outline: none; }}
    QListWidget::item {{ border: none; padding: 5px 4px; border-radius: 7px; }}
    QListWidget::item:selected {{ background: {SURFACE_2}; color: {TEXT}; }}
    QListWidget::item:hover {{ background: rgba(255,255,255,.035); }}

    QTableWidget {{ background: transparent; border: none; gridline-color: transparent; }}
    QTableWidget::item {{ padding: 7px 6px; border-bottom: 1px solid {BORDER_SOFT}; }}
    QTableWidget::item:selected {{ background: {SURFACE_2}; color: {TEXT}; }}
    QHeaderView::section {{
        background: transparent;
        color: {MUTED_DIM};
        border: none;
        border-bottom: 1px solid {BORDER};
        padding: 7px 6px;
        font-size: 11px;
        font-weight: 600;
    }}
    QTableCornerButton::section {{ background: transparent; border: none; }}

    QMenu {{
        background: {SURFACE_2};
        border: 1px solid {BORDER};
        border-radius: 10px;
        padding: 6px;
    }}
    QMenu::item {{ padding: 7px 26px 7px 12px; border-radius: 6px; color: {TEXT}; }}
    QMenu::item:selected {{ background: {SURFACE_3}; }}
    QMenu::item:disabled {{ color: {MUTED_DIM}; }}
    QMenu::separator {{ height: 1px; background: {BORDER_SOFT}; margin: 5px 8px; }}
    QMenu::indicator {{ width: 14px; height: 14px; }}

    QToolTip {{
        background: {SURFACE_3};
        color: {TEXT};
        border: 1px solid {BORDER};
        border-radius: 6px;
        padding: 5px 8px;
    }}
    QProgressBar {{ background: {SURFACE_3}; border: none; border-radius: 3px; height: 6px; text-align: center; }}
    QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}
    QMessageBox {{ background: {SURFACE}; }}
    QColorDialog {{ background: {SURFACE}; }}
    """


def apply_dark_title_bar(widget: QWidget) -> None:
    """Делает системный заголовок окна тёмным на Windows 10/11."""
    if sys.platform != "win32":
        return
    try:
        hwnd = int(widget.winId())
        value = ctypes.c_int(1)
        for attribute in (20, 19):
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)
            )
        corner = ctypes.c_int(2)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 33, ctypes.byref(corner), ctypes.sizeof(corner)
        )
    except Exception:  # noqa: BLE001
        pass
