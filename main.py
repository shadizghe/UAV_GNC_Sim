"""
Entry point for the drone flight control and waypoint navigation demo.

Run from the project root:

    python main.py

Plots are written to the results/ directory and a performance summary
is printed to stdout.
"""

import numpy as np

from config import sim_config as cfg
from src.dynamics import QuadrotorModel
from src.control import AttitudeController, LQRController, PositionController
from src.guidance import MinSnapTrajectory, WaypointManager
from src.disturbances import WindModel, SensorNoise
from src.estimation import InsGpsEKF, InsGpsEKFConfig
from src.simulation import Simulator
from src.visualization import plot_all
from src.utils import compute_performance_metrics


def build_simulator() -> Simulator:
    model = QuadrotorModel(cfg.QUADROTOR)

    controller_kind = getattr(cfg, "CONTROLLER", "pid").lower()
    if controller_kind == "lqr":
        pos_ctrl = LQRController(
            mass=cfg.QUADROTOR.mass,
            g=cfg.QUADROTOR.g,
            Q=np.diag(cfg.LQR_Q_DIAG),
            R=np.diag(cfg.LQR_R_DIAG),
            max_tilt_deg=cfg.MAX_TILT_DEG,
            thrust_limits=(cfg.QUADROTOR.thrust_min, cfg.QUADROTOR.thrust_max),
        )
    elif controller_kind == "pid":
        pos_ctrl = PositionController(
            mass=cfg.QUADROTOR.mass,
            g=cfg.QUADROTOR.g,
            xy_gains=cfg.POSITION_XY_GAINS,
            z_gains=cfg.POSITION_Z_GAINS,
            max_tilt_deg=cfg.MAX_TILT_DEG,
            max_accel_xy=cfg.MAX_ACCEL_XY,
            thrust_limits=(cfg.QUADROTOR.thrust_min, cfg.QUADROTOR.thrust_max),
        )
    else:
        raise ValueError(f"Unknown CONTROLLER {controller_kind!r}; expected 'pid' or 'lqr'")

    att_ctrl = AttitudeController(
        roll_gains=cfg.ROLL_GAINS,
        pitch_gains=cfg.PITCH_GAINS,
        yaw_gains=cfg.YAW_GAINS,
        tau_limit=cfg.QUADROTOR.tau_max,
    )

    wp_mgr = WaypointManager(
        waypoints=cfg.WAYPOINTS,
        acceptance_radius=cfg.ACCEPTANCE_RADIUS,
        yaw_setpoints=cfg.YAW_SETPOINTS,
    )

    rng = np.random.default_rng(cfg.RNG_SEED)
    wind = WindModel(
        mean_wind=cfg.MEAN_WIND,
        gust_std=cfg.GUST_STD,
        gust_time_constant=cfg.GUST_TIME_CONSTANT,
        rng=rng,
    ) if cfg.ENABLE_WIND else None

    noise = SensorNoise(
        position_std=cfg.POSITION_STD,
        velocity_std=cfg.VELOCITY_STD,
        attitude_std_deg=cfg.ATTITUDE_STD_DEG,
        rate_std_deg=cfg.RATE_STD_DEG,
        gps_rate_hz=cfg.EKF_GPS_RATE_HZ,
        rng=np.random.default_rng(cfg.RNG_SEED + 1),
    ) if cfg.ENABLE_SENSOR_NOISE else None

    estimator = InsGpsEKF(InsGpsEKFConfig(
        sigma_a=cfg.EKF_SIGMA_A,
        sigma_g_deg=cfg.EKF_SIGMA_G_DEG,
        sigma_ba=cfg.EKF_SIGMA_BA,
        sigma_bg_deg=cfg.EKF_SIGMA_BG_DEG,
        sigma_gps=cfg.EKF_SIGMA_GPS,
    )) if cfg.ENABLE_EKF else None

    state0 = QuadrotorModel.initial_state(
        position=cfg.INITIAL_POSITION,
        euler=cfg.INITIAL_EULER,
    )

    trajectory_kind = getattr(cfg, "TRAJECTORY", "waypoint").lower()
    if trajectory_kind == "minsnap":
        wps = np.vstack([np.asarray(cfg.INITIAL_POSITION, dtype=float), cfg.WAYPOINTS])
        seg_T = float(getattr(cfg, "MINSNAP_SEGMENT_TIME", 4.0))
        trajectory = MinSnapTrajectory(
            waypoints=wps,
            segment_times=np.full(len(wps) - 1, seg_T),
        )
    elif trajectory_kind == "waypoint":
        trajectory = None
    else:
        raise ValueError(f"Unknown TRAJECTORY {trajectory_kind!r}; expected 'waypoint' or 'minsnap'")

    return Simulator(
        model=model,
        position_ctrl=pos_ctrl,
        attitude_ctrl=att_ctrl,
        waypoint_mgr=wp_mgr,
        wind=wind,
        sensor_noise=noise,
        estimator=estimator,
        trajectory=trajectory,
        dt=cfg.DT,
        t_final=cfg.T_FINAL,
        initial_state=state0,
    )


def main() -> None:
    print("Running quadrotor waypoint-navigation simulation...")
    sim = build_simulator()
    result = sim.run()

    metrics = compute_performance_metrics(result)
    print("\n" + metrics.summary())

    if result.estimator_kind == "ins_gps":
        truth_pos = result.state[:, 0:3]
        raw_rms = float(np.sqrt(np.mean((result.meas_pos - truth_pos) ** 2)))
        ekf_rms = float(np.sqrt(np.mean((result.state_est[:, 0:3] - truth_pos) ** 2)))
        nis_finite = result.nis[np.isfinite(result.nis)]
        print(
            "  EKF position RMS       : {:.4f} m   (raw GPS: {:.4f} m)".format(
                ekf_rms, raw_rms
            )
        )
        print(
            "  NEES mean / NIS mean   : {:.2f} / {:.2f}   (theoretical 9 / 3)".format(
                float(np.mean(result.nees)),
                float(np.mean(nis_finite)) if nis_finite.size else float("nan"),
            )
        )

    plot_all(result, output_dir="results")
    print("\nPlots written to ./results/")


if __name__ == "__main__":
    main()
