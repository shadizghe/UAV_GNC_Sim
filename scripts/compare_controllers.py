"""
Side-by-side comparison: PID vs LQR, waypoint hops vs minimum-snap.

Runs three configurations on the same scenario, same wind, same sensor
noise, same EKF, same waypoint plan:

    1. baseline      : PID outer loop + raw waypoint hops
    2. minsnap_pid   : PID outer loop + minimum-snap reference trajectory
    3. minsnap_lqr   : LQR outer loop + minimum-snap reference trajectory
                       (with velocity feedforward from the trajectory)

All runs are scored against the same reference: the minimum-snap polynomial
trajectory through the configured waypoints. This isolates the contribution
of the trajectory generator from the contribution of the controller.

Output:
    results/controller_comparison.png    multi-panel figure
    Stdout                                RMS path error + thrust RMS table
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from config import sim_config as cfg
from src.dynamics import QuadrotorModel
from src.control import AttitudeController, LQRController, PositionController
from src.disturbances import SensorNoise, WindModel
from src.estimation import InsGpsEKF, InsGpsEKFConfig
from src.guidance import MinSnapTrajectory, WaypointManager
from src.simulation import Simulator


def _build_pid() -> PositionController:
    return PositionController(
        mass=cfg.QUADROTOR.mass, g=cfg.QUADROTOR.g,
        xy_gains=cfg.POSITION_XY_GAINS, z_gains=cfg.POSITION_Z_GAINS,
        max_tilt_deg=cfg.MAX_TILT_DEG, max_accel_xy=cfg.MAX_ACCEL_XY,
        thrust_limits=(cfg.QUADROTOR.thrust_min, cfg.QUADROTOR.thrust_max),
    )


def _build_lqr() -> LQRController:
    return LQRController(
        mass=cfg.QUADROTOR.mass, g=cfg.QUADROTOR.g,
        Q=np.diag(cfg.LQR_Q_DIAG), R=np.diag(cfg.LQR_R_DIAG),
        max_tilt_deg=cfg.MAX_TILT_DEG,
        thrust_limits=(cfg.QUADROTOR.thrust_min, cfg.QUADROTOR.thrust_max),
    )


def _build_minsnap() -> MinSnapTrajectory:
    wps = np.vstack([np.asarray(cfg.INITIAL_POSITION, dtype=float), cfg.WAYPOINTS])
    seg_T = float(getattr(cfg, "MINSNAP_SEGMENT_TIME", 4.0))
    return MinSnapTrajectory(wps, np.full(len(wps) - 1, seg_T))


def _run(label: str, controller, trajectory):
    """Run one simulator configuration. Sensor noise / wind / EKF are fresh
    each run so each controller sees the same realisation under the same
    seed."""
    model = QuadrotorModel(cfg.QUADROTOR)
    att = AttitudeController(
        roll_gains=cfg.ROLL_GAINS, pitch_gains=cfg.PITCH_GAINS,
        yaw_gains=cfg.YAW_GAINS, tau_limit=cfg.QUADROTOR.tau_max,
    )
    wp_mgr = WaypointManager(
        waypoints=cfg.WAYPOINTS, acceptance_radius=cfg.ACCEPTANCE_RADIUS,
        yaw_setpoints=cfg.YAW_SETPOINTS,
    )
    wind = WindModel(
        mean_wind=cfg.MEAN_WIND, gust_std=cfg.GUST_STD,
        gust_time_constant=cfg.GUST_TIME_CONSTANT,
        rng=np.random.default_rng(cfg.RNG_SEED),
    ) if cfg.ENABLE_WIND else None
    noise = SensorNoise(
        position_std=cfg.POSITION_STD, velocity_std=cfg.VELOCITY_STD,
        attitude_std_deg=cfg.ATTITUDE_STD_DEG, rate_std_deg=cfg.RATE_STD_DEG,
        gps_rate_hz=cfg.EKF_GPS_RATE_HZ,
        rng=np.random.default_rng(cfg.RNG_SEED + 1),
    ) if cfg.ENABLE_SENSOR_NOISE else None
    ekf = InsGpsEKF(InsGpsEKFConfig(
        sigma_a=cfg.EKF_SIGMA_A, sigma_g_deg=cfg.EKF_SIGMA_G_DEG,
        sigma_ba=cfg.EKF_SIGMA_BA, sigma_bg_deg=cfg.EKF_SIGMA_BG_DEG,
        sigma_gps=cfg.EKF_SIGMA_GPS,
    )) if cfg.ENABLE_EKF else None
    state0 = QuadrotorModel.initial_state(
        position=cfg.INITIAL_POSITION, euler=cfg.INITIAL_EULER,
    )

    sim = Simulator(
        model=model, position_ctrl=controller, attitude_ctrl=att,
        waypoint_mgr=wp_mgr, wind=wind, sensor_noise=noise,
        estimator=ekf, trajectory=trajectory,
        dt=cfg.DT, t_final=cfg.T_FINAL, initial_state=state0,
    )
    print(f"  running {label}...")
    return sim.run()


def _path_error(t: np.ndarray, pos: np.ndarray, ref: MinSnapTrajectory) -> np.ndarray:
    err = np.zeros(t.size)
    for i, tk in enumerate(t):
        p_ref, *_ = ref(float(tk), max_deriv=0)
        err[i] = float(np.linalg.norm(pos[i] - p_ref))
    return err


def main() -> None:
    print("Comparing PID vs LQR with waypoint vs min-snap trajectory...\n")
    ref = _build_minsnap()

    runs = {
        "PID + waypoint":   _run("PID + waypoint",   _build_pid(), None),
        "PID + min-snap":   _run("PID + min-snap",   _build_pid(), _build_minsnap()),
        "LQR + min-snap":   _run("LQR + min-snap",   _build_lqr(), _build_minsnap()),
    }

    print("\n  config               RMS path err (m)   max thrust (N)   RMS thrust (N)")
    print("  " + "-" * 74)
    metrics = {}
    for label, r in runs.items():
        err = _path_error(r.t, r.state[:, 0:3], ref)
        rms_err = float(np.sqrt(np.mean(err ** 2)))
        thrust = r.control[:, 0]
        rms_thr = float(np.sqrt(np.mean(thrust ** 2)))
        max_thr = float(np.max(thrust))
        metrics[label] = (err, rms_err, thrust, rms_thr, max_thr)
        print(f"  {label:<20s}     {rms_err:6.3f}              {max_thr:6.2f}            {rms_thr:6.2f}")

    # ---------------- Plotting -------------------------------------------------
    Path("results").mkdir(exist_ok=True)
    fig, axes = plt.subplots(2, 2, figsize=(13, 9))
    colors = {"PID + waypoint": "#888888",
              "PID + min-snap": "#1f77b4",
              "LQR + min-snap": "#d62728"}

    # (a) Top-down xy path
    ax = axes[0, 0]
    for label, r in runs.items():
        ax.plot(r.state[:, 0], r.state[:, 1], color=colors[label], label=label, lw=1.5)
    ax.plot(cfg.WAYPOINTS[:, 0], cfg.WAYPOINTS[:, 1], "ko",
            markersize=7, markerfacecolor="none", label="waypoints")
    # Reference path overlay
    t_ref = np.linspace(0, ref.total_time, 400)
    ref_pos = np.array([ref(float(tk))[0] for tk in t_ref])
    ax.plot(ref_pos[:, 0], ref_pos[:, 1], "--", color="green", lw=1, alpha=0.6, label="min-snap ref")
    ax.set_xlabel("x [m]"); ax.set_ylabel("y [m]")
    ax.set_title("(a) Top-down path"); ax.set_aspect("equal", adjustable="datalim")
    ax.grid(alpha=0.3); ax.legend(fontsize=9)

    # (b) Altitude vs time
    ax = axes[0, 1]
    for label, r in runs.items():
        ax.plot(r.t, r.state[:, 2], color=colors[label], label=label, lw=1.2)
    ax.set_xlabel("t [s]"); ax.set_ylabel("z [m]")
    ax.set_title("(b) Altitude")
    ax.grid(alpha=0.3); ax.legend(fontsize=9)

    # (c) Tracking error against the common min-snap reference
    ax = axes[1, 0]
    for label, r in runs.items():
        err, *_ = metrics[label]
        ax.plot(r.t, err, color=colors[label], label=label, lw=1.2)
    ax.set_xlabel("t [s]"); ax.set_ylabel("|p - p_ref| [m]")
    ax.set_title("(c) Path error vs common reference")
    ax.grid(alpha=0.3); ax.legend(fontsize=9)

    # (d) Thrust effort
    ax = axes[1, 1]
    for label, r in runs.items():
        ax.plot(r.t, r.control[:, 0], color=colors[label], label=label, lw=1.0, alpha=0.85)
    hover = cfg.QUADROTOR.mass * cfg.QUADROTOR.g
    ax.axhline(hover, ls="--", color="black", alpha=0.4, label=f"hover ({hover:.1f} N)")
    ax.set_xlabel("t [s]"); ax.set_ylabel("collective thrust [N]")
    ax.set_title("(d) Control effort")
    ax.grid(alpha=0.3); ax.legend(fontsize=9)

    fig.suptitle("Controller / trajectory comparison", fontsize=14)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    out = Path("results") / "controller_comparison.png"
    fig.savefig(out, dpi=130)
    print(f"\nFigure written to {out}")


if __name__ == "__main__":
    main()
