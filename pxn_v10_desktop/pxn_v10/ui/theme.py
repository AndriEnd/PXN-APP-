"""Dark 'cockpit' design system: palette + application stylesheet."""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont

# ------------------------------------------------------------------ palette
BG = "#0D0F13"
SURFACE = "#14181F"
SURFACE_2 = "#1A1F28"
SURFACE_3 = "#222833"
BORDER = "#2A313D"
BORDER_SOFT = "#20262F"
TEXT = "#E9ECF1"
TEXT_DIM = "#9AA3B2"
TEXT_MUTED = "#677083"
ACCENT = "#FF5230"
ACCENT_2 = "#FF8A1F"
ACCENT_SOFT = "#3A1E19"
GREEN = "#2FD27A"
RED = "#FF4B55"
BLUE = "#3B9EFF"
AMBER = "#FFB020"

FONT_FAMILY = "Segoe UI"


def qcolor(hex_value: str, alpha: int = 255) -> QColor:
    c = QColor(hex_value)
    c.setAlpha(alpha)
    return c


def app_font(point_size: float = 10.0, bold: bool = False) -> QFont:
    f = QFont(FONT_FAMILY, 0)
    f.setPointSizeF(point_size)
    f.setBold(bold)
    f.setStyleHint(QFont.SansSerif)
    return f


STYLESHEET = f"""
* {{
    font-family: "{FONT_FAMILY}", "Segoe UI Variable", "Inter", "Helvetica Neue", Arial, sans-serif;
    font-size: 10pt;
    color: {TEXT};
    outline: none;
}}
QMainWindow, QDialog, QWidget#root {{ background: {BG}; }}
QWidget {{ background: transparent; }}
QToolTip {{
    background: {SURFACE_3}; color: {TEXT}; border: 1px solid {BORDER};
    padding: 6px 8px; border-radius: 6px;
}}

/* ---------- typography helpers ---------- */
QLabel#h1 {{ font-size: 20pt; font-weight: 700; }}
QLabel#h2 {{ font-size: 13pt; font-weight: 650; }}
QLabel#h3 {{ font-size: 10.5pt; font-weight: 650; color: {TEXT}; }}
QLabel#eyebrow {{ font-size: 8pt; font-weight: 700; color: {TEXT_MUTED}; }}
QLabel#dim {{ color: {TEXT_DIM}; }}
QLabel#muted {{ color: {TEXT_MUTED}; font-size: 9pt; }}
QLabel#mono {{ font-family: "Cascadia Mono", "Consolas", monospace; color: {TEXT_DIM}; }}
QLabel#value {{ font-size: 12pt; font-weight: 700; }}

/* ---------- cards ---------- */
QFrame#card {{
    background: {SURFACE}; border: 1px solid {BORDER_SOFT}; border-radius: 14px;
}}
QFrame#cardInner {{
    background: {SURFACE_2}; border: 1px solid {BORDER_SOFT}; border-radius: 10px;
}}
QFrame#sidebar {{ background: {SURFACE}; border-right: 1px solid {BORDER_SOFT}; }}
QFrame#divider {{ background: {BORDER_SOFT}; max-height: 1px; min-height: 1px; border: none; }}
QFrame#vdivider {{ background: {BORDER_SOFT}; max-width: 1px; min-width: 1px; border: none; }}

/* ---------- buttons ---------- */
QPushButton {{
    background: {SURFACE_3}; border: 1px solid {BORDER}; border-radius: 9px;
    padding: 8px 16px; font-weight: 600;
}}
QPushButton:hover {{ background: #2B3240; border-color: #394251; }}
QPushButton:pressed {{ background: #20262F; }}
QPushButton:disabled {{ color: {TEXT_MUTED}; background: {SURFACE_2}; border-color: {BORDER_SOFT}; }}
QPushButton#primary {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {ACCENT}, stop:1 {ACCENT_2});
    border: none; color: white; padding: 9px 20px;
}}
QPushButton#primary:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #FF6A4D, stop:1 #FFA040);
}}
QPushButton#primary:disabled {{ background: {SURFACE_3}; color: {TEXT_MUTED}; }}
QPushButton#ghost {{ background: transparent; border: 1px solid {BORDER}; }}
QPushButton#ghost:hover {{ background: {SURFACE_2}; }}
QPushButton#danger {{ background: transparent; border: 1px solid #5A2A30; color: {RED}; }}
QPushButton#danger:hover {{ background: #2B1519; }}
QPushButton#icon {{
    background: {SURFACE_2}; border: 1px solid {BORDER_SOFT}; border-radius: 12px;
    padding: 0px; min-width: 24px; max-width: 24px; min-height: 24px; max-height: 24px;
    font-size: 9pt; font-weight: 700; color: {TEXT_DIM};
}}
QPushButton#icon:hover {{ color: {TEXT}; border-color: {ACCENT}; }}
QPushButton#nav {{
    background: transparent; border: none; border-radius: 10px; text-align: left;
    padding: 10px 14px; font-weight: 600; color: {TEXT_DIM};
}}
QPushButton#nav:hover {{ background: {SURFACE_2}; color: {TEXT}; }}
QPushButton#nav:checked {{ background: {ACCENT_SOFT}; color: {ACCENT_2}; }}
QPushButton#nav:disabled {{ color: {TEXT_MUTED}; }}
QPushButton#seg {{
    background: transparent; border: none; border-radius: 8px; padding: 8px 18px;
    color: {TEXT_DIM}; font-weight: 700;
}}
QPushButton#seg:hover {{ color: {TEXT}; }}
QPushButton#seg:checked {{ background: {SURFACE_3}; color: {TEXT}; }}
QFrame#segBar {{ background: {SURFACE}; border: 1px solid {BORDER_SOFT}; border-radius: 11px; }}
QPushButton#chip {{
    background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 14px; padding: 5px 14px;
    font-weight: 700; color: {TEXT};
}}
QPushButton#chip:hover {{ border-color: {ACCENT}; }}

/* ---------- inputs ---------- */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
    background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 8px; padding: 7px 10px;
    selection-background-color: {ACCENT}; selection-color: white;
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{
    border-color: {ACCENT};
}}
QSpinBox {{ padding: 5px 8px; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    width: 0px; border: none;
}}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {SURFACE_2}; border: 1px solid {BORDER}; selection-background-color: {ACCENT_SOFT};
    selection-color: {ACCENT_2}; padding: 4px; outline: none;
}}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{
    width: 18px; height: 18px; border-radius: 5px; border: 1px solid {BORDER}; background: {SURFACE_2};
}}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; image: url({{CHECK}}); }}
QTableView::indicator, QTreeView::indicator, QListView::indicator {{
    width: 18px; height: 18px; border-radius: 5px; border: 1px solid {BORDER}; background: {SURFACE_2};
}}
QTableView::indicator:checked, QTreeView::indicator:checked, QListView::indicator:checked {{
    background: {ACCENT}; border-color: {ACCENT}; image: url({{CHECK}});
}}

/* ---------- slider ---------- */
QSlider::groove:horizontal {{ height: 6px; background: {SURFACE_3}; border-radius: 3px; }}
QSlider::sub-page:horizontal {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {ACCENT}, stop:1 {ACCENT_2});
    border-radius: 3px;
}}
QSlider::handle:horizontal {{
    width: 20px; height: 20px; margin: -8px 0; border-radius: 10px;
    background: #FFFFFF; border: 3px solid {ACCENT};
}}
QSlider::handle:horizontal:hover {{ border-color: {ACCENT_2}; }}
QSlider::groove:horizontal:disabled {{ background: {SURFACE_2}; }}
QSlider::sub-page:horizontal:disabled {{ background: {SURFACE_3}; }}

/* ---------- scroll / lists / trees ---------- */
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {SURFACE_3}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #394251; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {SURFACE_3}; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QListWidget, QTreeWidget, QTableWidget, QTreeView, QTableView {{
    background: {SURFACE}; border: 1px solid {BORDER_SOFT}; border-radius: 12px;
    alternate-background-color: {SURFACE_2}; gridline-color: {BORDER_SOFT};
}}
QListWidget::item {{ padding: 10px 12px; border-radius: 8px; margin: 2px 6px; }}
QListWidget::item:hover {{ background: {SURFACE_2}; }}
QListWidget::item:selected {{ background: {ACCENT_SOFT}; color: {ACCENT_2}; }}
QTreeWidget::item {{ padding: 5px 6px; }}
QTreeWidget::item:selected, QTableWidget::item:selected {{ background: {ACCENT_SOFT}; color: {TEXT}; }}
QTreeWidget::branch {{ background: transparent; }}
QHeaderView::section {{
    background: {SURFACE_2}; color: {TEXT_MUTED}; border: none; border-bottom: 1px solid {BORDER_SOFT};
    padding: 8px 10px; font-weight: 700; font-size: 8.5pt;
}}
QTableWidget::item {{ padding: 4px 8px; }}

QTabWidget::pane {{ border: none; }}
QTabBar::tab {{
    background: transparent; color: {TEXT_DIM}; padding: 10px 18px; font-weight: 700;
    border-bottom: 2px solid transparent; margin-right: 4px;
}}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom: 2px solid {ACCENT}; }}
QTabBar::tab:hover {{ color: {TEXT}; }}

QProgressBar {{
    background: {SURFACE_3}; border: none; border-radius: 4px; height: 8px; text-align: center; color: transparent;
}}
QProgressBar::chunk {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {ACCENT}, stop:1 {ACCENT_2}); border-radius: 4px;
}}
QMenu {{
    background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 10px; padding: 6px;
}}
QMenu::item {{ padding: 8px 22px 8px 14px; border-radius: 6px; }}
QMenu::item:selected {{ background: {ACCENT_SOFT}; color: {ACCENT_2}; }}
QMenu::separator {{ height: 1px; background: {BORDER_SOFT}; margin: 6px 8px; }}
QMessageBox {{ background: {SURFACE}; }}
QStatusBar {{ background: {SURFACE}; color: {TEXT_DIM}; border-top: 1px solid {BORDER_SOFT}; }}
"""


def stylesheet() -> str:
    """STYLESHEET with the white check-mark image for checkboxes (rendered once to the data dir)."""
    from pathlib import Path

    from ..storage.paths import app_data_dir
    from .icons import draw_icon

    path = Path(app_data_dir()) / "assets"
    path.mkdir(parents=True, exist_ok=True)
    check = path / "check.png"
    try:
        draw_icon("check", "#FFFFFF", 20).save(str(check), "PNG")
        url = check.as_posix()
    except Exception:  # noqa: BLE001 - cosmetic only
        url = ""
    return STYLESHEET.replace("{CHECK}", url)
