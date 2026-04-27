"""
Visualization for the simulation output.

Produces:
    - 3D trajectory with waypoints
    - Top-down XY view
    - Altitude tracking (z vs t)
    - Per-axis position error
    - Attitude (commanded vs measured)
    - Control inputs (thrust + torques)
    - Wind disturbance time history
"""

from __future__ import annotations
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401 (registers 3D projection)


def _save(fig, path: Path) -> None:
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_all(result, output_dir: str | Path = "results", show: bool = False) -> None:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    t        = result.t
    pos      = result.state[:, 0:3]
    euler    = result.state[:, 6:9]
    euler_cmd = result.euler_cmd
    u        = result.control
    wps      = result.waypoints
    err      = pos - result.waypoint

    # --- 3D trajectory --------------------------------------------------
    fig = plt.figure(figsize=(9, 7))
    ax = fig.add_subplot(111, projection='3d')
    ax.plot(pos[:, 0], pos[:, 1], pos[:, 2], lw=1.8, label='Trajectory')
    ax.scatter(wps[:, 0], wps[:, 1], wps[:, 2],
               c='red', s=60, marker='o', label='Waypoints')
    for i, w in enumerate(wps):
        ax.text(w[0], w[1], w[2] + 0.3, f'  WP{i}', fontsize=9)
    ax.scatter(pos[0, 0], pos[0, 1], pos[0, 2], c='green', s=60, marker='^',
               label='Start')
    ax.set_xlabel('East X [m]')
    ax.set_ylabel('North Y [m]')
    ax.set_zlabel('Up Z [m]')
    ax.set_title('Quadrotor 3D Flight Path')
    ax.legend()
    _save(fig, out / "01_trajectory_3d.png")

    # --- Top-down XY ----------------------------------------------------
    fig, ax = plt.subplots(figsize=(8, 7))
    ax.plot(pos[:, 0], pos[:, 1], lw=1.8, label='Trajectory')
    ax.scatter(wps[:, 0], wps[:, 1], c='red', s=60, label='Waypoints')
    for i, w in enumerate(wps):
        ax.annotate(f'WP{i}', (w[0], w[1]),
                    textcoords='offset points', xytext=(6, 6), fontsize=9)
    ax.set_xlabel('East X [m]')
    ax.set_ylabel('North Y [m]')
    ax.set_title('Top-Down View (XY Plane)')
    ax.grid(True, alpha=0.4)
    ax.set_aspect('equal', adjustable='datalim')
    ax.legend()
    _save(fig, out / "02_trajectory_xy.png")

    # --- Altitude vs time ----------------------------------------------
    fig, ax = plt.subplots(figsize=(10, 4.5))
    ax.plot(t, pos[:, 2], label='Altitude z', lw=1.6)
    ax.plot(t, result.waypoint[:, 2], '--', label='Commanded z', lw=1.2)
    ax.set_xlabel('Time [s]')
    ax.set_ylabel('Altitude [m]')
    ax.set_title('Altitude Tracking')
    ax.grid(True, alpha=0.4)
    ax.legend()
    _save(fig, out / "03_altitude.png")

    # --- Per-axis tracking error ---------------------------------------
    fig, ax = plt.subplots(figsize=(10, 4.5))
    ax.plot(t, err[:, 0], label='x error')
    ax.plot(t, err[:, 1], label='y error')
    ax.plot(t, err[:, 2], label='z error')
    ax.plot(t, np.linalg.norm(err, axis=1), 'k--', label='|error|', lw=1.2)
    ax.set_xlabel('Time [s]')
    ax.set_ylabel('Position error [m]')
    ax.set_title('Position Tracking Error')
    ax.grid(True, alpha=0.4)
    ax.legend()
    _save(fig, out / "04_position_error.png")

    # --- Attitude (cmd vs meas) ----------------------------------------
    fig, axes = plt.subplots(3, 1, figsize=(10, 8), sharex=True)
    labels = ['Roll  phi', 'Pitch theta', 'Yaw  psi']
    for i in range(3):
        axes[i].plot(t, np.rad2deg(euler[:, i]),     label='measured')
        axes[i].plot(t, np.rad2deg(euler_cmd[:, i]), '--', label='commanded')
        axes[i].set_ylabel(labels[i] + ' [deg]')
        axes[i].grid(True, alpha=0.4)
        axes[i].legend(loc='upper right')
    axes[-1].set_xlabel('Time [s]')
    axes[0].set_title('Attitude: Commanded vs. Measured')
    _save(fig, out / "05_attitude.png")

    # --- Control inputs ------------------------------------------------
    fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
    axes[0].plot(t, u[:, 0], lw=1.4)
    axes[0].set_ylabel('Thrust T [N]')
    axes[0].set_title('Control Inputs')
    axes[0].grid(True, alpha=0.4)
    axes[1].plot(t, u[:, 1], label='tau_phi')
    axes[1].plot(t, u[:, 2], label='tau_theta')
    axes[1].plot(t, u[:, 3], label='tau_psi')
    axes[1].set_ylabel('Torque [N.m]')
    axes[1].set_xlabel('Time [s]')
    axes[1].grid(True, alpha=0.4)
    axes[1].legend()
    _save(fig, out / "06_control_inputs.png")

    # --- Wind disturbance ----------------------------------------------
    if np.any(result.wind_force):
        fig, ax = plt.subplots(figsize=(10, 4.5))
        ax.plot(t, result.wind_force[:, 0], label='Fx')
        ax.plot(t, result.wind_force[:, 1], label='Fy')
        ax.plot(t, result.wind_force[:, 2], label='Fz')
        ax.set_xlabel('Time [s]')
        ax.set_ylabel('Wind force [N]')
        ax.set_title('External Disturbance Time History')
        ax.grid(True, alpha=0.4)
        ax.legend()
        _save(fig, out / "07_disturbance.png")

    # --- EKF residuals + 3-sigma envelope ------------------------------
    if getattr(result, "estimator_kind", "none") == "ins_gps":
        try:
            from scipy import stats as _stats
        except ImportError:  # plotter is best-effort
            _stats = None

        pos_err = result.state_est[:, 0:3] - pos
        # Per-axis 3-sigma envelope from the position covariance diagonal.
        sigma = np.sqrt(np.maximum(result.pos_cov_diag, 0.0))
        labels = ['x [m]', 'y [m]', 'z [m]']
        fig, axes = plt.subplots(3, 1, figsize=(10, 7), sharex=True)
        for i in range(3):
            axes[i].plot(t, pos_err[:, i], lw=1.2, label='estimate − truth')
            axes[i].plot(t,  3.0 * sigma[:, i], '--', color='gray', lw=1.0,
                         label='±3σ' if i == 0 else None)
            axes[i].plot(t, -3.0 * sigma[:, i], '--', color='gray', lw=1.0)
            axes[i].axhline(0.0, color='k', lw=0.5, alpha=0.3)
            axes[i].set_ylabel(labels[i])
            axes[i].grid(True, alpha=0.4)
        axes[0].legend(loc='upper right')
        axes[0].set_title('EKF Position Error vs. 3σ Envelope (consistency check)')
        axes[-1].set_xlabel('Time [s]')
        _save(fig, out / "08_ekf_residual.png")

        # NEES + NIS (filter + innovation consistency).
        nees_lo = nees_hi = nis_lo = nis_hi = None
        if _stats is not None:
            nees_lo, nees_hi = _stats.chi2.interval(0.95, df=9)
            nis_lo,  nis_hi  = _stats.chi2.interval(0.95, df=3)

        fig, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
        axes[0].plot(t, result.nees, lw=1.0, label='NEES (9-DoF nav)')
        axes[0].axhline(9.0, color='k', lw=0.6, alpha=0.4, label='E[χ²] = 9')
        if nees_lo is not None:
            axes[0].axhspan(nees_lo, nees_hi, color='tab:green', alpha=0.12,
                            label='95% χ² band')
        axes[0].set_ylabel('NEES')
        axes[0].set_yscale('log')
        axes[0].grid(True, alpha=0.4)
        axes[0].legend(loc='upper right', fontsize=9)
        axes[0].set_title('Filter consistency: NEES (truth-vs-estimate) and NIS (innovation)')

        finite = np.isfinite(result.nis)
        axes[1].plot(t[finite], result.nis[finite], '.', ms=3, label='NIS (3-DoF GPS)')
        axes[1].axhline(3.0, color='k', lw=0.6, alpha=0.4, label='E[χ²] = 3')
        if nis_lo is not None:
            axes[1].axhspan(nis_lo, nis_hi, color='tab:green', alpha=0.12,
                            label='95% χ² band')
        axes[1].set_ylabel('NIS')
        axes[1].set_xlabel('Time [s]')
        axes[1].grid(True, alpha=0.4)
        axes[1].legend(loc='upper right', fontsize=9)
        _save(fig, out / "09_ekf_consistency.png")

        # Estimated IMU biases — observability check.
        fig, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
        axes[0].plot(t, result.accel_bias_est[:, 0], label='b_a_x')
        axes[0].plot(t, result.accel_bias_est[:, 1], label='b_a_y')
        axes[0].plot(t, result.accel_bias_est[:, 2], label='b_a_z')
        axes[0].set_ylabel('Accel bias [m/s²]')
        axes[0].grid(True, alpha=0.4)
        axes[0].legend(loc='upper right', fontsize=9)
        axes[0].set_title('EKF-estimated IMU biases')
        axes[1].plot(t, np.rad2deg(result.gyro_bias_est[:, 0]), label='b_g_x')
        axes[1].plot(t, np.rad2deg(result.gyro_bias_est[:, 1]), label='b_g_y')
        axes[1].plot(t, np.rad2deg(result.gyro_bias_est[:, 2]), label='b_g_z')
        axes[1].set_ylabel('Gyro bias [deg/s]')
        axes[1].set_xlabel('Time [s]')
        axes[1].grid(True, alpha=0.4)
        axes[1].legend(loc='upper right', fontsize=9)
        _save(fig, out / "10_ekf_biases.png")

    if show:
        plt.show()
