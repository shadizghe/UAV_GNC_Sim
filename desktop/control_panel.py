"""
Left-hand panel: simulation, PID, and environment controls.

All widgets write into a SimParams object when `current_params()` is
called. The main window grabs that snapshot and hands it to the worker.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QDoubleSpinBox, QSpinBox, QCheckBox, QScrollArea, QLabel,
)

from config import sim_config as cfg
from .sim_worker import SimParams


def _spin(val: float, lo: float, hi: float, step: float = 0.1,
          decimals: int = 2) -> QDoubleSpinBox:
    w = QDoubleSpinBox()
    w.setRange(lo, hi)
    w.setDecimals(decimals)
    w.setSingleStep(step)
    w.setValue(val)
    w.setButtonSymbols(QDoubleSpinBox.NoButtons)
    w.setAlignment(Qt.AlignRight)
    return w


def _ispin(val: int, lo: int, hi: int) -> QSpinBox:
    w = QSpinBox()
    w.setRange(lo, hi)
    w.setValue(val)
    w.setAlignment(Qt.AlignRight)
    return w


def _pid_row(label_kp: str, gains: tuple) -> tuple[QHBoxLayout, tuple[QDoubleSpinBox, ...]]:
    kp, ki, kd = gains
    wkp = _spin(kp, 0, 50, 0.1, 2)
    wki = _spin(ki, 0, 20, 0.05, 2)
    wkd = _spin(kd, 0, 20, 0.1, 2)
    row = QHBoxLayout()
    row.setSpacing(4)
    for w in (wkp, wki, wkd):
        w.setFixedWidth(72)
        row.addWidget(w)
    return row, (wkp, wki, wkd)


class ControlPanel(QWidget):
    run_requested = Signal()
    stop_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        # ---- Simulation ---------------------------------------------
        self.dt = _spin(cfg.DT, 0.001, 0.05, 0.001, 3)
        self.tfinal = _spin(cfg.T_FINAL, 5.0, 120.0, 1.0, 1)
        self.seed = _ispin(cfg.RNG_SEED, 0, 99999)
        self.mass = _spin(cfg.QUADROTOR.mass, 0.3, 5.0, 0.05, 2)

        sim_box = QGroupBox("Simulation")
        f = QFormLayout(sim_box)
        f.addRow("dt [s]", self.dt)
        f.addRow("t_final [s]", self.tfinal)
        f.addRow("Mass [kg]", self.mass)
        f.addRow("RNG seed", self.seed)

        # ---- Position PID -------------------------------------------
        xy_row, self.xy_gains = _pid_row("xy", cfg.POSITION_XY_GAINS)
        z_row,  self.z_gains  = _pid_row("z",  cfg.POSITION_Z_GAINS)

        pos_box = QGroupBox("Position PID (kp / ki / kd)")
        pf = QFormLayout(pos_box)
        pf.addRow("xy loop", self._wrap_row(xy_row))
        pf.addRow("z loop",  self._wrap_row(z_row))

        # ---- Attitude PID -------------------------------------------
        roll_row,  self.roll_gains  = _pid_row("roll",  cfg.ROLL_GAINS)
        pitch_row, self.pitch_gains = _pid_row("pitch", cfg.PITCH_GAINS)
        yaw_row,   self.yaw_gains   = _pid_row("yaw",   cfg.YAW_GAINS)

        att_box = QGroupBox("Attitude PID (kp / ki / kd)")
        af = QFormLayout(att_box)
        af.addRow("roll",  self._wrap_row(roll_row))
        af.addRow("pitch", self._wrap_row(pitch_row))
        af.addRow("yaw",   self._wrap_row(yaw_row))

        # ---- Environment --------------------------------------------
        self.wind_en = QCheckBox("Enable wind + gusts")
        self.wind_en.setChecked(cfg.ENABLE_WIND)

        self.wind_x = _spin(cfg.MEAN_WIND[0], -10, 10, 0.1, 2)
        self.wind_y = _spin(cfg.MEAN_WIND[1], -10, 10, 0.1, 2)
        self.wind_z = _spin(cfg.MEAN_WIND[2], -10, 10, 0.1, 2)

        self.gust_x = _spin(cfg.GUST_STD[0], 0, 5, 0.05, 2)
        self.gust_y = _spin(cfg.GUST_STD[1], 0, 5, 0.05, 2)
        self.gust_z = _spin(cfg.GUST_STD[2], 0, 5, 0.05, 2)

        self.noise_en = QCheckBox("Enable sensor noise")
        self.noise_en.setChecked(cfg.ENABLE_SENSOR_NOISE)

        env_box = QGroupBox("Environment")
        ef = QFormLayout(env_box)
        ef.addRow(self.wind_en)
        ef.addRow("Mean wind x/y/z [m/s]", self._triple(self.wind_x, self.wind_y, self.wind_z))
        ef.addRow("Gust std x/y/z [m/s]",  self._triple(self.gust_x, self.gust_y, self.gust_z))
        ef.addRow(self.noise_en)

        # ---- Layout --------------------------------------------------
        inner = QWidget()
        inner_lay = QVBoxLayout(inner)
        inner_lay.setContentsMargins(4, 4, 4, 4)
        inner_lay.setSpacing(10)
        inner_lay.addWidget(sim_box)
        inner_lay.addWidget(pos_box)
        inner_lay.addWidget(att_box)
        inner_lay.addWidget(env_box)
        inner_lay.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidget(inner)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    # ------------------------------------------------------------------ #
    def _wrap_row(self, layout: QHBoxLayout) -> QWidget:
        w = QWidget()
        w.setLayout(layout)
        return w

    def _triple(self, a, b, c) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        for spin in (a, b, c):
            spin.setFixedWidth(72)
            h.addWidget(spin)
        return w

    # ------------------------------------------------------------------ #
    def current_params(self, waypoints: np.ndarray, yaws: np.ndarray) -> SimParams:
        return SimParams(
            dt=self.dt.value(),
            t_final=self.tfinal.value(),
            mass=self.mass.value(),
            seed=self.seed.value(),
            pos_xy_gains=tuple(s.value() for s in self.xy_gains),
            pos_z_gains =tuple(s.value() for s in self.z_gains),
            roll_gains  =tuple(s.value() for s in self.roll_gains),
            pitch_gains =tuple(s.value() for s in self.pitch_gains),
            yaw_gains   =tuple(s.value() for s in self.yaw_gains),
            enable_wind=self.wind_en.isChecked(),
            mean_wind=(self.wind_x.value(), self.wind_y.value(), self.wind_z.value()),
            gust_std =(self.gust_x.value(), self.gust_y.value(), self.gust_z.value()),
            enable_noise=self.noise_en.isChecked(),
            waypoints=np.asarray(waypoints, dtype=float),
            yaw_setpoints=np.asarray(yaws, dtype=float),
        )
