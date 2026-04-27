"""
15-state error-state INS/GPS Extended Kalman Filter (MEKF).

Nominal state (16 elements):
    p   (3) inertial position    [m]
    v   (3) inertial velocity    [m/s]
    q   (4) body-to-inertial quaternion [w, x, y, z]
    b_a (3) accelerometer bias   [m/s^2]   (body-frame, additive)
    b_g (3) gyroscope bias       [rad/s]   (body-frame, additive)

Error state used for the 15x15 covariance:
    [delta_p, delta_v, delta_theta, delta_b_a, delta_b_g]

The accelerometer measures specific force in body frame:
    a_meas = R^T (a_n - g_n) + b_a + n_a
where g_n = [0, 0, -g] is gravity in the ENU navigation frame, so the
filter integrates v_dot = R(q)(a_meas - b_a) + g_n.

The gyroscope measures angular rate in body frame:
    w_meas = omega_body + b_g + n_g

GPS updates are loose-coupled position fixes:
    z = p + n_gps,    H = [I, 0, 0, 0, 0]

Consistency diagnostics (NEES / NIS) are surfaced for the standard
"is my filter tuned" check.
"""

from __future__ import annotations

from dataclasses import dataclass
import numpy as np

from ..utils.quaternion import (
    skew, quat_multiply, quat_normalize, quat_to_rotmat,
    euler_to_quat, quat_to_euler, quat_from_small_angle,
)


@dataclass
class InsGpsEKFConfig:
    sigma_a: float = 0.20         # accel white-noise PSD-equivalent [m/s^2]
    sigma_g_deg: float = 1.5      # gyro  white-noise PSD-equivalent [deg/s]
    sigma_ba: float = 0.005       # accel bias random walk           [m/s^2 / sqrt(s)]
    sigma_bg_deg: float = 0.05    # gyro  bias random walk           [deg/s / sqrt(s)]

    sigma_gps: float = 0.05       # GPS position 1-sigma             [m]

    init_pos_std: float = 0.5
    init_vel_std: float = 0.5
    init_att_std_deg: float = 5.0
    init_ba_std: float = 0.10
    init_bg_std_deg: float = 1.0

    g: float = 9.81


class InsGpsEKF:
    """Loose-coupled IMU + GPS EKF with quaternion attitude."""

    NX = 15      # error-state dimension

    def __init__(self, cfg: InsGpsEKFConfig | None = None):
        self.cfg = cfg if cfg is not None else InsGpsEKFConfig()

        # Nominal state
        self.p = np.zeros(3)
        self.v = np.zeros(3)
        self.q = np.array([1.0, 0.0, 0.0, 0.0])   # identity attitude
        self.b_a = np.zeros(3)
        self.b_g = np.zeros(3)

        # Covariance (15x15)
        sg = np.deg2rad(self.cfg.init_att_std_deg)
        sbg = np.deg2rad(self.cfg.init_bg_std_deg)
        self.P = np.diag(np.concatenate([
            np.full(3, self.cfg.init_pos_std ** 2),
            np.full(3, self.cfg.init_vel_std ** 2),
            np.full(3, sg ** 2),
            np.full(3, self.cfg.init_ba_std ** 2),
            np.full(3, sbg ** 2),
        ])).astype(float)

        # Cached diagnostics from the last GPS update
        self.last_innovation: np.ndarray = np.zeros(3)
        self.last_innovation_cov: np.ndarray = np.eye(3)
        self.last_nis: float = 0.0

    # ------------------------------------------------------------------ #
    # Initialisation helpers
    # ------------------------------------------------------------------ #
    def seed_from_truth(self, position: np.ndarray, velocity: np.ndarray,
                        euler: np.ndarray) -> None:
        """Initialise nominal state from a known truth pose.

        Used by the simulator to skip filter warm-up so plots focus on
        the steady-state behaviour we care about.
        """
        self.p = np.asarray(position, dtype=float).copy()
        self.v = np.asarray(velocity, dtype=float).copy()
        self.q = euler_to_quat(*euler)
        self.b_a[:] = 0.0
        self.b_g[:] = 0.0

    # ------------------------------------------------------------------ #
    # Predict on IMU
    # ------------------------------------------------------------------ #
    def predict(self, accel_meas: np.ndarray, gyro_meas: np.ndarray,
                dt: float) -> None:
        cfg = self.cfg

        a_b = np.asarray(accel_meas, dtype=float) - self.b_a
        w_b = np.asarray(gyro_meas,  dtype=float) - self.b_g

        R = quat_to_rotmat(self.q)
        g_n = np.array([0.0, 0.0, -cfg.g])

        # --- Nominal-state strapdown integration --------------------------
        a_n = R @ a_b + g_n
        # Trapezoidal position update is more accurate than v*dt for
        # accelerated flight; cost is one extra add.
        self.p = self.p + self.v * dt + 0.5 * a_n * (dt ** 2)
        self.v = self.v + a_n * dt
        self.q = quat_normalize(
            quat_multiply(self.q, quat_from_small_angle(w_b * dt))
        )

        # --- Error-state Jacobian F (continuous) --------------------------
        F = np.zeros((self.NX, self.NX))
        I3 = np.eye(3)
        F[0:3,   3:6 ] = I3
        F[3:6,   6:9 ] = -R @ skew(a_b)
        F[3:6,   9:12] = -R
        F[6:9,   6:9 ] = -skew(w_b)
        F[6:9,  12:15] = -I3
        # bias rows are zero — biases are random walks driven by Q

        Phi = np.eye(self.NX) + F * dt        # 1st-order discretisation

        # --- Discrete process-noise Q -------------------------------------
        sa2 = cfg.sigma_a ** 2
        sg2 = np.deg2rad(cfg.sigma_g_deg) ** 2
        sba2 = cfg.sigma_ba ** 2
        sbg2 = np.deg2rad(cfg.sigma_bg_deg) ** 2

        Q = np.zeros((self.NX, self.NX))
        Q[3:6,   3:6 ] = sa2 * I3 * dt
        Q[6:9,   6:9 ] = sg2 * I3 * dt
        Q[9:12,  9:12] = sba2 * I3 * dt
        Q[12:15, 12:15] = sbg2 * I3 * dt

        self.P = Phi @ self.P @ Phi.T + Q
        # Symmetrise to fight numerical drift
        self.P = 0.5 * (self.P + self.P.T)

    # ------------------------------------------------------------------ #
    # Update on GPS position fix
    # ------------------------------------------------------------------ #
    def update_position(self, z_pos: np.ndarray) -> None:
        H = np.zeros((3, self.NX))
        H[:, 0:3] = np.eye(3)
        R_gps = np.eye(3) * (self.cfg.sigma_gps ** 2)

        z = np.asarray(z_pos, dtype=float).reshape(3)
        y = z - self.p                             # innovation
        S = H @ self.P @ H.T + R_gps
        S_inv = np.linalg.inv(S)
        K = self.P @ H.T @ S_inv                   # 15x3 gain

        dx = K @ y                                  # 15-vec error state

        # Inject error into nominal state and reset dx ---------------------
        self.p   = self.p   + dx[0:3]
        self.v   = self.v   + dx[3:6]
        self.q   = quat_normalize(
            quat_multiply(self.q, quat_from_small_angle(dx[6:9]))
        )
        self.b_a = self.b_a + dx[9:12]
        self.b_g = self.b_g + dx[12:15]

        # Joseph-form covariance update for numerical stability ------------
        I = np.eye(self.NX)
        self.P = (I - K @ H) @ self.P @ (I - K @ H).T + K @ R_gps @ K.T
        self.P = 0.5 * (self.P + self.P.T)

        # Diagnostics
        self.last_innovation = y
        self.last_innovation_cov = S
        self.last_nis = float(y @ S_inv @ y)

    # ------------------------------------------------------------------ #
    # Consistency diagnostics
    # ------------------------------------------------------------------ #
    def nees_nav(self, p_true: np.ndarray, v_true: np.ndarray,
                 q_true: np.ndarray) -> float:
        """9-dim navigation NEES = e^T P_nav^{-1} e for [dp, dv, dtheta]."""
        dp = np.asarray(p_true, dtype=float) - self.p
        dv = np.asarray(v_true, dtype=float) - self.v
        # Attitude error: q_err = q_true * q_est^{-1};
        # for unit quaternions, dtheta ≈ 2 * vec(q_err).
        q_err = quat_multiply(q_true, np.array([self.q[0], -self.q[1], -self.q[2], -self.q[3]]))
        dtheta = 2.0 * q_err[1:4] * (1.0 if q_err[0] >= 0 else -1.0)

        e = np.concatenate([dp, dv, dtheta])
        P_nav = self.P[0:9, 0:9]
        # Add a tiny floor so a numerically singular P_nav doesn't crash
        # the diagnostic during the first few warm-up steps.
        try:
            return float(e @ np.linalg.solve(P_nav, e))
        except np.linalg.LinAlgError:
            return float(e @ np.linalg.lstsq(P_nav, e, rcond=None)[0])

    # ------------------------------------------------------------------ #
    # Read-only views consumed by the simulator and the UI
    # ------------------------------------------------------------------ #
    @property
    def pos(self) -> np.ndarray:
        return self.p.copy()

    @property
    def vel(self) -> np.ndarray:
        return self.v.copy()

    @property
    def euler(self) -> np.ndarray:
        return quat_to_euler(self.q)

    @property
    def quat(self) -> np.ndarray:
        return self.q.copy()

    @property
    def accel_bias(self) -> np.ndarray:
        return self.b_a.copy()

    @property
    def gyro_bias(self) -> np.ndarray:
        return self.b_g.copy()

    @property
    def pos_cov(self) -> np.ndarray:
        return self.P[0:3, 0:3].copy()

    @property
    def pos_std(self) -> np.ndarray:
        return np.sqrt(np.diag(self.P[0:3, 0:3]))

    @property
    def vel_std(self) -> np.ndarray:
        return np.sqrt(np.diag(self.P[3:6, 3:6]))

    @property
    def pos_cov_trace(self) -> float:
        return float(np.trace(self.P[0:3, 0:3]))

    @property
    def vel_cov_trace(self) -> float:
        return float(np.trace(self.P[3:6, 3:6]))
