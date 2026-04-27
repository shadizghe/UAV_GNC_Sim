"""
Heads-up-display strip with live telemetry cards.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QLabel, QHBoxLayout, QVBoxLayout, QFrame, QProgressBar,
)

from .theme import PALETTE


class HudCard(QFrame):
    def __init__(self, title: str, unit: str, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet(
            f"QFrame {{ background: {PALETTE['panel']}; "
            f"border: 1px solid {PALETTE['border']}; border-radius: 4px; }}"
        )

        title_lbl = QLabel(title.upper())
        title_lbl.setObjectName("CardTitle")

        self._value = QLabel("—")
        self._value.setObjectName("ValueLabel")

        unit_lbl = QLabel(unit)
        unit_lbl.setObjectName("UnitLabel")

        self._bar = QProgressBar()
        self._bar.setRange(0, 1000)
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(4)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(2)
        lay.addWidget(title_lbl)
        lay.addWidget(self._value)
        lay.addWidget(unit_lbl)
        lay.addWidget(self._bar)

        self._min = 0.0
        self._max = 1.0
        self._bar_color = PALETTE["cyan"]

    def set_range(self, lo: float, hi: float) -> None:
        self._min, self._max = lo, hi

    def set_bar_color(self, color: str) -> None:
        self._bar_color = color
        self._bar.setStyleSheet(
            f"QProgressBar::chunk {{ background: {color}; }}"
            f"QProgressBar {{ background: {PALETTE['bg']}; border: none; }}"
        )

    def set_value(self, v: float, fmt: str = "{:+.2f}") -> None:
        self._value.setText(fmt.format(v))
        span = max(self._max - self._min, 1e-9)
        frac = (v - self._min) / span
        frac = max(0.0, min(1.0, frac))
        self._bar.setValue(int(frac * 1000))


class HudStrip(QWidget):
    """Row of cards showing altitude, speed, thrust, tilt, mission status."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self.altitude = HudCard("Altitude", "metres AGL")
        self.altitude.set_range(0, 5)
        self.altitude.set_bar_color(PALETTE["cyan"])

        self.speed = HudCard("Ground Speed", "m/s")
        self.speed.set_range(0, 6)
        self.speed.set_bar_color(PALETTE["violet"])

        self.thrust = HudCard("Thrust", "N")
        self.thrust.set_range(0, 30)
        self.thrust.set_bar_color(PALETTE["green"])

        self.tilt = HudCard("Tilt", "deg")
        self.tilt.set_range(0, 25)
        self.tilt.set_bar_color(PALETTE["amber"])

        self.mission = HudCard("Mission", "waypoints")
        self.mission.set_bar_color(PALETTE["pink"])

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        for card in (self.altitude, self.speed, self.thrust, self.tilt, self.mission):
            lay.addWidget(card, 1)

    def update_from_state(self, state, u, wp_idx, wp_total) -> None:
        import numpy as np
        z = float(state[2])
        vx, vy, vz = state[3:6]
        spd = float(np.sqrt(vx * vx + vy * vy + vz * vz))
        thrust = float(u[0])
        phi, theta = float(state[6]), float(state[7])
        tilt_deg = float(np.degrees(np.arccos(max(-1.0, min(1.0,
                    np.cos(phi) * np.cos(theta))))))

        self.altitude.set_value(z, "{:.2f}")
        self.speed.set_value(spd, "{:.2f}")
        self.thrust.set_value(thrust, "{:.1f}")
        self.tilt.set_value(tilt_deg, "{:.1f}")

        self.mission.set_range(0, max(1, wp_total))
        self.mission.set_value(wp_idx, f"{{:.0f}} / {wp_total}")

    def reset(self) -> None:
        for c in (self.altitude, self.speed, self.thrust, self.tilt, self.mission):
            c.set_value(0.0, "{:.2f}")
