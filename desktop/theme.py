"""
Visual theme for the desktop GCS.

Centralises the colour palette and Qt stylesheet so every widget reads
from the same aerospace-dark look-and-feel.
"""

from __future__ import annotations


PALETTE = {
    "bg":       "#0a0e1a",
    "panel":    "#141a2e",
    "panel_hi": "#1b2440",
    "border":   "#223355",
    "text":     "#e1e8f0",
    "muted":    "#8aa0bf",
    "cyan":     "#00d4ff",
    "amber":    "#ffc107",
    "green":    "#2ecc71",
    "red":      "#ff4d6d",
    "violet":   "#b388ff",
    "pink":     "#ff4081",
    "grid":     "#223355",
}


STYLESHEET = f"""
QMainWindow, QWidget {{
    background-color: {PALETTE['bg']};
    color: {PALETTE['text']};
    font-family: "Segoe UI", "Inter", "Arial";
    font-size: 10pt;
}}

QDockWidget {{
    color: {PALETTE['cyan']};
    titlebar-close-icon: none;
    titlebar-normal-icon: none;
}}
QDockWidget::title {{
    background: {PALETTE['panel']};
    padding: 6px 10px;
    border-bottom: 1px solid {PALETTE['border']};
    text-align: left;
    font-weight: 600;
    letter-spacing: 1px;
    text-transform: uppercase;
}}

QGroupBox {{
    background: {PALETTE['panel']};
    border: 1px solid {PALETTE['border']};
    border-radius: 4px;
    margin-top: 14px;
    padding: 10px;
    font-weight: 600;
    color: {PALETTE['cyan']};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 6px;
    background: {PALETTE['bg']};
}}

QLabel#ValueLabel {{
    color: {PALETTE['cyan']};
    font-family: "Consolas", "JetBrains Mono", monospace;
    font-size: 14pt;
    font-weight: 600;
}}
QLabel#UnitLabel {{
    color: {PALETTE['muted']};
    font-size: 8pt;
    text-transform: uppercase;
    letter-spacing: 1px;
}}
QLabel#CardTitle {{
    color: {PALETTE['muted']};
    font-size: 8pt;
    text-transform: uppercase;
    letter-spacing: 1.5px;
}}

QPushButton {{
    background: {PALETTE['panel_hi']};
    color: {PALETTE['text']};
    border: 1px solid {PALETTE['border']};
    border-radius: 3px;
    padding: 6px 14px;
    font-weight: 600;
    letter-spacing: 0.5px;
}}
QPushButton:hover {{
    border-color: {PALETTE['cyan']};
    color: {PALETTE['cyan']};
}}
QPushButton:pressed {{
    background: {PALETTE['border']};
}}
QPushButton:disabled {{
    color: {PALETTE['muted']};
    border-color: {PALETTE['border']};
}}
QPushButton#PrimaryButton {{
    background: {PALETTE['cyan']};
    color: {PALETTE['bg']};
    border: 1px solid {PALETTE['cyan']};
}}
QPushButton#PrimaryButton:hover {{
    background: #33dfff;
}}
QPushButton#DangerButton {{
    color: {PALETTE['red']};
    border-color: {PALETTE['red']};
}}

QDoubleSpinBox, QSpinBox, QLineEdit {{
    background: {PALETTE['bg']};
    border: 1px solid {PALETTE['border']};
    border-radius: 3px;
    padding: 4px 6px;
    color: {PALETTE['text']};
    selection-background-color: {PALETTE['cyan']};
    selection-color: {PALETTE['bg']};
}}
QDoubleSpinBox:focus, QSpinBox:focus, QLineEdit:focus {{
    border-color: {PALETTE['cyan']};
}}

QCheckBox {{ color: {PALETTE['text']}; }}
QCheckBox::indicator {{
    width: 14px; height: 14px;
    border: 1px solid {PALETTE['border']};
    background: {PALETTE['bg']};
    border-radius: 2px;
}}
QCheckBox::indicator:checked {{
    background: {PALETTE['cyan']};
    border-color: {PALETTE['cyan']};
}}

QTableWidget {{
    background: {PALETTE['bg']};
    alternate-background-color: {PALETTE['panel']};
    gridline-color: {PALETTE['border']};
    border: 1px solid {PALETTE['border']};
    selection-background-color: {PALETTE['panel_hi']};
    selection-color: {PALETTE['cyan']};
}}
QHeaderView::section {{
    background: {PALETTE['panel']};
    color: {PALETTE['muted']};
    padding: 6px;
    border: none;
    border-right: 1px solid {PALETTE['border']};
    border-bottom: 1px solid {PALETTE['border']};
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 1px;
    font-size: 8pt;
}}

QTabWidget::pane {{
    border: 1px solid {PALETTE['border']};
    top: -1px;
}}
QTabBar::tab {{
    background: {PALETTE['panel']};
    color: {PALETTE['muted']};
    padding: 6px 14px;
    border: 1px solid {PALETTE['border']};
    border-bottom: none;
    text-transform: uppercase;
    font-size: 8pt;
    letter-spacing: 1px;
}}
QTabBar::tab:selected {{
    background: {PALETTE['bg']};
    color: {PALETTE['cyan']};
    border-bottom: 1px solid {PALETTE['bg']};
}}

QProgressBar {{
    background: {PALETTE['panel']};
    border: 1px solid {PALETTE['border']};
    border-radius: 2px;
    text-align: center;
    color: {PALETTE['text']};
    height: 14px;
}}
QProgressBar::chunk {{
    background: {PALETTE['cyan']};
}}

QScrollBar:vertical {{
    background: {PALETTE['bg']};
    width: 10px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {PALETTE['border']};
    border-radius: 4px;
    min-height: 20px;
}}
QScrollBar::handle:vertical:hover {{ background: {PALETTE['cyan']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}

QStatusBar {{
    background: {PALETTE['panel']};
    color: {PALETTE['muted']};
    border-top: 1px solid {PALETTE['border']};
}}

QSplitter::handle {{ background: {PALETTE['border']}; }}
"""
