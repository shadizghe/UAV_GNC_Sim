"""
Main GCS window. Docks the control panel, mission table, 3D scene,
HUD, metrics, and time-series tabs around a central playback strip.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QMainWindow, QDockWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QSlider, QLabel, QStatusBar, QMessageBox,
)

from config import sim_config as cfg
from .theme import STYLESHEET, PALETTE
from .scene3d import Scene3D
from .hud import HudStrip
from .timeseries import TimeSeriesTabs
from .mission_table import MissionTable
from .control_panel import ControlPanel
from .metrics_panel import MetricsPanel
from .sim_worker import run_in_thread


class PlaybackBar(QWidget):
    """Scrubber + play/pause/reset + speed for the flown trajectory."""
    frame_changed = Signal(int)
    play_toggled = Signal(bool)
    reset_requested = Signal()
    speed_changed = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.btn_play = QPushButton("▶  Play")
        self.btn_reset = QPushButton("⟲  Reset")
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 0)
        self.time_lbl = QLabel("t = 0.00 s")
        self.time_lbl.setObjectName("ValueLabel")

        self.speed_btns: list[QPushButton] = []
        speed_row = QHBoxLayout()
        speed_row.setSpacing(4)
        for label, val in (("0.5×", 0.5), ("1×", 1.0), ("2×", 2.0), ("4×", 4.0)):
            b = QPushButton(label)
            b.setCheckable(True)
            b.setFixedWidth(42)
            b.clicked.connect(lambda _, v=val, btn=b: self._set_speed(v, btn))
            speed_row.addWidget(b)
            self.speed_btns.append(b)
        self.speed_btns[1].setChecked(True)  # 1x default

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(12)
        lay.addWidget(self.btn_play)
        lay.addWidget(self.btn_reset)
        lay.addWidget(self.slider, 1)
        lay.addWidget(self.time_lbl)
        lay.addLayout(speed_row)

        self._playing = False
        self.btn_play.clicked.connect(self._toggle)
        self.btn_reset.clicked.connect(self.reset_requested.emit)
        self.slider.valueChanged.connect(self.frame_changed)

    def _set_speed(self, v: float, btn: QPushButton) -> None:
        for b in self.speed_btns:
            b.setChecked(b is btn)
        self.speed_changed.emit(v)

    def _toggle(self) -> None:
        self._playing = not self._playing
        self.btn_play.setText("❚❚  Pause" if self._playing else "▶  Play")
        self.play_toggled.emit(self._playing)

    def set_playing(self, playing: bool) -> None:
        self._playing = playing
        self.btn_play.setText("❚❚  Pause" if playing else "▶  Play")

    def set_total_frames(self, n: int) -> None:
        self.slider.setRange(0, max(0, n - 1))

    def set_frame(self, i: int) -> None:
        self.slider.blockSignals(True)
        self.slider.setValue(i)
        self.slider.blockSignals(False)

    def set_time(self, t: float) -> None:
        self.time_lbl.setText(f"t = {t:6.2f} s")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Quadrotor GNC — Ground Control Station")
        self.resize(1500, 900)
        self.setStyleSheet(STYLESHEET)

        self.scene = Scene3D()
        self.hud = HudStrip()
        self.series = TimeSeriesTabs()
        self.mission = MissionTable()
        self.controls = ControlPanel()
        self.metrics = MetricsPanel()
        self.playback = PlaybackBar()

        self._build_central()
        self._build_docks()
        self._build_menu()
        self._build_statusbar()

        # ---- State --------------------------------------------------
        self._result = None
        self._thread = None
        self._worker = None
        self._timer = QTimer(self)
        self._timer.setInterval(33)  # ~30 fps UI ticks
        self._timer.timeout.connect(self._tick)
        self._speed = 1.0
        self._frame = 0

        # ---- Wiring -------------------------------------------------
        self.mission.set_waypoints(cfg.WAYPOINTS.copy(), cfg.YAW_SETPOINTS.copy())
        self.mission.waypoints_changed.connect(self._on_mission_changed)
        self._on_mission_changed(*self.mission.get_waypoints())

        self.playback.frame_changed.connect(self._seek)
        self.playback.play_toggled.connect(self._on_play_toggle)
        self.playback.reset_requested.connect(self._on_reset)
        self.playback.speed_changed.connect(self._on_speed)

    # ------------------------------------------------------------------ #
    def _build_central(self) -> None:
        central = QWidget()
        lay = QVBoxLayout(central)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)
        lay.addWidget(self.hud)
        lay.addWidget(self.scene, 1)
        lay.addWidget(self.playback)
        self.setCentralWidget(central)

    def _dock(self, title: str, widget: QWidget, area: Qt.DockWidgetArea) -> QDockWidget:
        d = QDockWidget(title, self)
        d.setAllowedAreas(Qt.AllDockWidgetAreas)
        d.setWidget(widget)
        self.addDockWidget(area, d)
        return d

    def _build_docks(self) -> None:
        self._dock("Controls", self.controls, Qt.LeftDockWidgetArea)
        self._dock("Mission Plan", self.mission, Qt.LeftDockWidgetArea)
        self._dock("Telemetry", self.series, Qt.BottomDockWidgetArea)
        self._dock("Performance", self.metrics, Qt.BottomDockWidgetArea)

    def _build_menu(self) -> None:
        mbar = self.menuBar()
        sim_menu = mbar.addMenu("&Simulation")

        run_act = QAction("&Run simulation", self)
        run_act.setShortcut(QKeySequence("Ctrl+R"))
        run_act.triggered.connect(self._run_sim)
        sim_menu.addAction(run_act)

        stop_act = QAction("&Stop playback", self)
        stop_act.setShortcut(QKeySequence("Ctrl+."))
        stop_act.triggered.connect(lambda: self._on_play_toggle(False))
        sim_menu.addAction(stop_act)

        sim_menu.addSeparator()
        quit_act = QAction("&Quit", self)
        quit_act.setShortcut(QKeySequence.Quit)
        quit_act.triggered.connect(self.close)
        sim_menu.addAction(quit_act)

        view_menu = mbar.addMenu("&View")
        reset_view = QAction("Reset 3D view", self)
        reset_view.triggered.connect(
            lambda: self.scene.view.setCameraPosition(distance=18, elevation=22, azimuth=-55))
        view_menu.addAction(reset_view)

    def _build_statusbar(self) -> None:
        bar = QStatusBar()
        self.setStatusBar(bar)
        self._status_lbl = QLabel("Ready. Edit the mission, tune gains, then press ▶ Run.")
        bar.addWidget(self._status_lbl, 1)

        self.btn_run = QPushButton("▶  RUN SIMULATION")
        self.btn_run.setObjectName("PrimaryButton")
        self.btn_run.clicked.connect(self._run_sim)
        bar.addPermanentWidget(self.btn_run)

    # ------------------------------------------------------------------ #
    # Mission
    # ------------------------------------------------------------------ #
    def _on_mission_changed(self, wps: np.ndarray, _yaws: np.ndarray) -> None:
        if len(wps) >= 2:
            self.scene.set_mission(wps)

    # ------------------------------------------------------------------ #
    # Simulation lifecycle
    # ------------------------------------------------------------------ #
    def _run_sim(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            return

        wps, yaws = self.mission.get_waypoints()
        if len(wps) < 2:
            QMessageBox.warning(self, "Mission too short",
                                "Need at least two waypoints.")
            return

        params = self.controls.current_params(wps, yaws)
        self.btn_run.setEnabled(False)
        self.btn_run.setText("SIMULATING…")
        self._status_lbl.setText(
            f"Running sim: dt={params.dt}s, horizon={params.t_final}s, "
            f"{len(wps)} waypoints.")
        self.playback.set_playing(False)
        self._timer.stop()

        self._thread, self._worker = run_in_thread(
            params, self._on_sim_finished, self._on_sim_failed,
        )
        self._thread.start()

    def _on_sim_finished(self, result, metrics) -> None:
        self._result = result
        self.btn_run.setEnabled(True)
        self.btn_run.setText("▶  RUN SIMULATION")
        self._status_lbl.setText(
            f"Sim complete: {metrics.waypoints_reached}/{metrics.waypoints_total} "
            f"waypoints, RMS error {metrics.rms_position_error:.2f} m.")

        self.series.update_from_result(result)
        self.metrics.update_from_metrics(metrics)
        self.scene.set_mission(result.waypoints)
        self.scene.set_trajectory(result.state[:, 0:3])

        self.playback.set_total_frames(len(result.t))
        self._frame = 0
        self._apply_frame(0)
        self.playback.set_frame(0)

        # autoplay
        self.playback.set_playing(True)
        self._timer.start()

    def _on_sim_failed(self, msg: str) -> None:
        self.btn_run.setEnabled(True)
        self.btn_run.setText("▶  RUN SIMULATION")
        self._status_lbl.setText(f"Simulation failed: {msg}")
        QMessageBox.critical(self, "Simulation failed", msg)

    # ------------------------------------------------------------------ #
    # Playback
    # ------------------------------------------------------------------ #
    def _on_play_toggle(self, playing: bool) -> None:
        self.playback.set_playing(playing)
        if playing and self._result is not None:
            if self._frame >= len(self._result.t) - 1:
                self._frame = 0
            self._timer.start()
        else:
            self._timer.stop()

    def _on_reset(self) -> None:
        self._frame = 0
        self._apply_frame(0)
        self.playback.set_frame(0)

    def _on_speed(self, v: float) -> None:
        self._speed = v

    def _seek(self, i: int) -> None:
        self._frame = i
        self._apply_frame(i)

    def _tick(self) -> None:
        if self._result is None:
            return
        n = len(self._result.t)
        # advance by (tick_dt * speed) seconds in sim time
        tick_dt_s = self._timer.interval() / 1000.0
        sim_dt = self._result.t[1] - self._result.t[0]
        step = max(1, int(round(tick_dt_s * self._speed / sim_dt)))
        self._frame += step
        if self._frame >= n:
            self._frame = n - 1
            self._timer.stop()
            self.playback.set_playing(False)
        self._apply_frame(self._frame)
        self.playback.set_frame(self._frame)

    def _apply_frame(self, k: int) -> None:
        if self._result is None:
            return
        r = self._result
        k = max(0, min(k, len(r.t) - 1))
        t = float(r.t[k])
        pos = r.state[k, 0:3]
        euler = r.state[k, 6:9]

        self.scene.set_drone_pose(pos, euler)
        self.scene.set_trajectory(r.state[:k + 1, 0:3])

        # active waypoint index from reached_log or current setpoint
        active_wp = self._active_waypoint_index(k)
        self.hud.update_from_state(r.state[k], r.control[k],
                                    active_wp, len(r.waypoints))
        self.series.set_cursor_time(t)
        self.playback.set_time(t)

    def _active_waypoint_index(self, k: int) -> int:
        r = self._result
        target = r.waypoint[k]
        diffs = np.linalg.norm(r.waypoints - target, axis=1)
        return int(np.argmin(diffs)) + 1  # 1-based for HUD

    # ------------------------------------------------------------------ #
    def closeEvent(self, event):
        self._timer.stop()
        if self._thread is not None and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(1000)
        super().closeEvent(event)
