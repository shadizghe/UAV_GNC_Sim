"""
Background simulation worker.

Runs the quadrotor sim on a QThread so the GUI stays responsive, and
emits the full SimulationResult when the run finishes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import numpy as np
from PySide6.QtCore import QObject, QThread, Signal

from config import sim_config as cfg
from src.dynamics import QuadrotorModel, QuadrotorParams
from src.control import AttitudeController, PositionController
from src.guidance import WaypointManager
from src.disturbances import WindModel, SensorNoise
from src.simulation import Simulator, SimulationResult
from src.utils import compute_performance_metrics


@dataclass
class SimParams:
    """User-tunable knobs gathered from the GUI side panels."""
    dt: float = cfg.DT
    t_final: float = cfg.T_FINAL
    mass: float = cfg.QUADROTOR.mass
    seed: int = cfg.RNG_SEED

    pos_xy_gains: tuple = cfg.POSITION_XY_GAINS
    pos_z_gains:  tuple = cfg.POSITION_Z_GAINS
    roll_gains:   tuple = cfg.ROLL_GAINS
    pitch_gains:  tuple = cfg.PITCH_GAINS
    yaw_gains:    tuple = cfg.YAW_GAINS

    enable_wind: bool = cfg.ENABLE_WIND
    mean_wind: tuple = cfg.MEAN_WIND
    gust_std:  tuple = cfg.GUST_STD

    enable_noise: bool = cfg.ENABLE_SENSOR_NOISE

    waypoints: np.ndarray = field(default_factory=lambda: cfg.WAYPOINTS.copy())
    yaw_setpoints: np.ndarray = field(default_factory=lambda: cfg.YAW_SETPOINTS.copy())


def build_simulator(p: SimParams) -> Simulator:
    params = QuadrotorParams(
        mass=p.mass,
        g=cfg.QUADROTOR.g,
        Ixx=cfg.QUADROTOR.Ixx,
        Iyy=cfg.QUADROTOR.Iyy,
        Izz=cfg.QUADROTOR.Izz,
        drag_coeff=cfg.QUADROTOR.drag_coeff.copy(),
        thrust_min=cfg.QUADROTOR.thrust_min,
        thrust_max=cfg.QUADROTOR.thrust_max,
        tau_max=cfg.QUADROTOR.tau_max,
    )
    model = QuadrotorModel(params)

    pos_ctrl = PositionController(
        mass=params.mass, g=params.g,
        xy_gains=p.pos_xy_gains, z_gains=p.pos_z_gains,
        max_tilt_deg=cfg.MAX_TILT_DEG, max_accel_xy=cfg.MAX_ACCEL_XY,
        thrust_limits=(params.thrust_min, params.thrust_max),
    )
    att_ctrl = AttitudeController(
        roll_gains=p.roll_gains, pitch_gains=p.pitch_gains, yaw_gains=p.yaw_gains,
        tau_limit=params.tau_max,
    )
    wp_mgr = WaypointManager(
        waypoints=p.waypoints, acceptance_radius=cfg.ACCEPTANCE_RADIUS,
        yaw_setpoints=p.yaw_setpoints,
    )

    wind = WindModel(
        mean_wind=p.mean_wind, gust_std=p.gust_std,
        gust_time_constant=cfg.GUST_TIME_CONSTANT,
        rng=np.random.default_rng(p.seed),
    ) if p.enable_wind else None

    noise = SensorNoise(
        position_std=cfg.POSITION_STD, velocity_std=cfg.VELOCITY_STD,
        attitude_std_deg=cfg.ATTITUDE_STD_DEG, rate_std_deg=cfg.RATE_STD_DEG,
        rng=np.random.default_rng(p.seed + 1),
    ) if p.enable_noise else None

    state0 = QuadrotorModel.initial_state(
        position=cfg.INITIAL_POSITION, euler=cfg.INITIAL_EULER,
    )

    return Simulator(
        model=model, position_ctrl=pos_ctrl, attitude_ctrl=att_ctrl,
        waypoint_mgr=wp_mgr, wind=wind, sensor_noise=noise,
        dt=p.dt, t_final=p.t_final, initial_state=state0,
    )


class SimWorker(QObject):
    finished = Signal(object, object)   # (SimulationResult, metrics)
    failed = Signal(str)

    def __init__(self, params: SimParams):
        super().__init__()
        self.params = params

    def run(self) -> None:
        try:
            sim = build_simulator(self.params)
            result = sim.run()
            metrics = compute_performance_metrics(result)
            self.finished.emit(result, metrics)
        except Exception as exc:  # surface to GUI rather than crashing thread
            self.failed.emit(f"{type(exc).__name__}: {exc}")


def run_in_thread(params: SimParams,
                  on_finished,
                  on_failed) -> tuple[QThread, SimWorker]:
    """Spin a worker + thread; caller owns the lifetime."""
    thread = QThread()
    worker = SimWorker(params)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(on_finished)
    worker.failed.connect(on_failed)
    worker.finished.connect(thread.quit)
    worker.failed.connect(thread.quit)
    thread.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    return thread, worker
