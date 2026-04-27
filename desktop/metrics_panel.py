"""
Summary card for the post-run performance metrics.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QGridLayout, QLabel, QFrame

from .theme import PALETTE


class MetricsPanel(QFrame):
    LABELS = [
        ("total_mission_time",   "Mission time",       "s",  "{:.2f}"),
        ("rms_position_error",   "RMS position err",   "m",  "{:.2f}"),
        ("final_position_error", "Final pos err",      "m",  "{:.2f}"),
        ("settle_time_z",        "Altitude settle",    "s",  "{:.2f}"),
        ("overshoot_z",          "Altitude overshoot", "%",  "{:.1%}"),
        ("waypoints_reached",    "Waypoints reached",  "",   "{}"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet(
            f"QFrame {{ background: {PALETTE['panel']}; "
            f"border: 1px solid {PALETTE['border']}; border-radius: 4px; }}"
        )

        grid = QGridLayout(self)
        grid.setContentsMargins(12, 10, 12, 10)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(4)

        self._value_lbls: dict[str, QLabel] = {}
        for i, (key, title, unit, _fmt) in enumerate(self.LABELS):
            col = i % 3
            row_base = (i // 3) * 2

            t = QLabel(title.upper())
            t.setObjectName("CardTitle")

            v = QLabel("—")
            v.setObjectName("ValueLabel")

            u = QLabel(unit)
            u.setObjectName("UnitLabel")

            wrap = QWidget()
            from PySide6.QtWidgets import QHBoxLayout
            h = QHBoxLayout(wrap)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(4)
            h.addWidget(v)
            h.addWidget(u)
            h.addStretch(1)

            grid.addWidget(t,    row_base,     col, Qt.AlignLeft)
            grid.addWidget(wrap, row_base + 1, col, Qt.AlignLeft)
            self._value_lbls[key] = v

    def update_from_metrics(self, m) -> None:
        for key, _title, _unit, fmt in self.LABELS:
            val = getattr(m, key, None)
            if val is None:
                self._value_lbls[key].setText("—")
                continue
            if key == "waypoints_reached":
                total = getattr(m, "waypoints_total", None)
                text = f"{int(val)} / {int(total)}" if total is not None else f"{int(val)}"
            else:
                try:
                    text = fmt.format(val)
                except (ValueError, TypeError):
                    text = str(val)
            self._value_lbls[key].setText(text)

    def clear(self) -> None:
        for lbl in self._value_lbls.values():
            lbl.setText("—")
