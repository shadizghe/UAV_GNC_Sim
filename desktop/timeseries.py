"""
Time-series telemetry tabs (altitude, position error, attitude, control,
disturbance) backed by pyqtgraph.
"""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import QTabWidget, QWidget, QVBoxLayout

from .theme import PALETTE


pg.setConfigOptions(antialias=True, background=PALETTE["bg"], foreground=PALETTE["text"])


def _styled_plot(title: str, y_label: str, y_unit: str = "") -> pg.PlotWidget:
    w = pg.PlotWidget(title=title)
    w.showGrid(x=True, y=True, alpha=0.25)
    w.setLabel("bottom", "Time", units="s",
               **{"color": PALETTE["muted"], "font-size": "9pt"})
    w.setLabel("left", y_label, units=y_unit,
               **{"color": PALETTE["muted"], "font-size": "9pt"})
    w.getPlotItem().titleLabel.setAttr("color", PALETTE["cyan"])
    w.getPlotItem().titleLabel.setAttr("size", "10pt")
    w.getAxis("bottom").setPen(PALETTE["border"])
    w.getAxis("left").setPen(PALETTE["border"])
    w.getAxis("bottom").setTextPen(PALETTE["muted"])
    w.getAxis("left").setTextPen(PALETTE["muted"])
    legend = w.addLegend(offset=(-10, 10))
    legend.setLabelTextColor(PALETTE["text"])
    return w


class TimeSeriesTabs(QTabWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_altitude()
        self._build_position_error()
        self._build_attitude()
        self._build_control()
        self._build_disturbance()

        self._cursor_lines: list[pg.InfiniteLine] = []

    # ------------------------------------------------------------------ #
    def _wrap(self, w: QWidget) -> QWidget:
        c = QWidget()
        lay = QVBoxLayout(c)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addWidget(w)
        return c

    def _build_altitude(self) -> None:
        self.alt_plot = _styled_plot("Altitude tracking", "z", "m")
        self.alt_cmd = self.alt_plot.plot(
            pen=pg.mkPen(PALETTE["amber"], width=2, style=pg.QtCore.Qt.DashLine),
            name="commanded",
        )
        self.alt_meas = self.alt_plot.plot(
            pen=pg.mkPen(PALETTE["cyan"], width=2), name="measured",
        )
        self.addTab(self._wrap(self.alt_plot), "Altitude")

    def _build_position_error(self) -> None:
        self.err_plot = _styled_plot("Position error", "error", "m")
        self.err_x = self.err_plot.plot(pen=pg.mkPen(PALETTE["pink"], width=2),  name="x")
        self.err_y = self.err_plot.plot(pen=pg.mkPen(PALETTE["green"], width=2), name="y")
        self.err_z = self.err_plot.plot(pen=pg.mkPen(PALETTE["violet"], width=2), name="z")
        self.err_norm = self.err_plot.plot(
            pen=pg.mkPen(PALETTE["cyan"], width=2, style=pg.QtCore.Qt.DotLine),
            name="|e|",
        )
        self.addTab(self._wrap(self.err_plot), "Position error")

    def _build_attitude(self) -> None:
        self.att_plot = _styled_plot("Attitude", "angle", "deg")
        self.att_roll  = self.att_plot.plot(pen=pg.mkPen(PALETTE["cyan"],   width=2), name="roll")
        self.att_pitch = self.att_plot.plot(pen=pg.mkPen(PALETTE["amber"],  width=2), name="pitch")
        self.att_yaw   = self.att_plot.plot(pen=pg.mkPen(PALETTE["violet"], width=2), name="yaw")
        self.addTab(self._wrap(self.att_plot), "Attitude")

    def _build_control(self) -> None:
        self.ctrl_plot = _styled_plot("Control inputs", "output")
        self.ctrl_thrust = self.ctrl_plot.plot(
            pen=pg.mkPen(PALETTE["cyan"], width=2), name="thrust [N]")
        self.ctrl_tau_x  = self.ctrl_plot.plot(
            pen=pg.mkPen(PALETTE["pink"], width=1.5), name="tau_x [N·m]")
        self.ctrl_tau_y  = self.ctrl_plot.plot(
            pen=pg.mkPen(PALETTE["green"], width=1.5), name="tau_y [N·m]")
        self.ctrl_tau_z  = self.ctrl_plot.plot(
            pen=pg.mkPen(PALETTE["amber"], width=1.5), name="tau_z [N·m]")
        self.addTab(self._wrap(self.ctrl_plot), "Control")

    def _build_disturbance(self) -> None:
        self.wind_plot = _styled_plot("Wind force on body", "force", "N")
        self.wind_x = self.wind_plot.plot(pen=pg.mkPen(PALETTE["pink"],   width=2), name="Fx")
        self.wind_y = self.wind_plot.plot(pen=pg.mkPen(PALETTE["green"],  width=2), name="Fy")
        self.wind_z = self.wind_plot.plot(pen=pg.mkPen(PALETTE["violet"], width=2), name="Fz")
        self.addTab(self._wrap(self.wind_plot), "Disturbance")

    # ------------------------------------------------------------------ #
    def update_from_result(self, result) -> None:
        t = result.t
        s = result.state
        u = result.control
        wp = result.waypoint

        self.alt_cmd.setData(t, wp[:, 2])
        self.alt_meas.setData(t, s[:, 2])

        err = wp - s[:, 0:3]
        self.err_x.setData(t, err[:, 0])
        self.err_y.setData(t, err[:, 1])
        self.err_z.setData(t, err[:, 2])
        self.err_norm.setData(t, np.linalg.norm(err, axis=1))

        self.att_roll.setData(t,  np.degrees(s[:, 6]))
        self.att_pitch.setData(t, np.degrees(s[:, 7]))
        self.att_yaw.setData(t,   np.degrees(s[:, 8]))

        self.ctrl_thrust.setData(t, u[:, 0])
        self.ctrl_tau_x.setData(t,  u[:, 1])
        self.ctrl_tau_y.setData(t,  u[:, 2])
        self.ctrl_tau_z.setData(t,  u[:, 3])

        wf = result.wind_force
        self.wind_x.setData(t, wf[:, 0])
        self.wind_y.setData(t, wf[:, 1])
        self.wind_z.setData(t, wf[:, 2])

        self._install_cursors()

    def _install_cursors(self) -> None:
        # remove old cursors
        plots = [self.alt_plot, self.err_plot, self.att_plot,
                 self.ctrl_plot, self.wind_plot]
        for line in self._cursor_lines:
            for p in plots:
                if line in p.items():
                    p.removeItem(line)
        self._cursor_lines.clear()

        for p in plots:
            line = pg.InfiniteLine(
                pos=0.0, angle=90,
                pen=pg.mkPen(PALETTE["cyan"], width=1, style=pg.QtCore.Qt.DashLine),
            )
            p.addItem(line)
            self._cursor_lines.append(line)

    def set_cursor_time(self, t_val: float) -> None:
        for line in self._cursor_lines:
            line.setPos(t_val)

    def clear_all(self) -> None:
        for series in (self.alt_cmd, self.alt_meas,
                       self.err_x, self.err_y, self.err_z, self.err_norm,
                       self.att_roll, self.att_pitch, self.att_yaw,
                       self.ctrl_thrust, self.ctrl_tau_x, self.ctrl_tau_y, self.ctrl_tau_z,
                       self.wind_x, self.wind_y, self.wind_z):
            series.clear()
