"""
Position / velocity Extended Kalman Filter.

A 6-state nearly-constant-velocity model fused with noisy GPS-style
position measurements. State and process model:

    x = [px, py, pz, vx, vy, vz]^T
    x_{k+1} = F x_k + w,   F = [[ I, dt I ], [ 0,    I ]]
    Q is built from a white-noise *jerk* assumption (G G^T * sigma_jerk^2)
    so velocity uncertainty grows as the filter coasts and shrinks when
    a position fix arrives.

Measurement model (position-only fix):

    z = H x + v,   H = [ I, 0 ],   R = sigma_pos^2 * I

The EKF is functionally a Kalman filter here (linear F, H), but the API
keeps the EKF naming so the same class can later host a non-linear
attitude/velocity update without breaking callers.
"""

from __future__ import annotations

import numpy as np


class PositionEKF:
    def __init__(self,
                 sigma_pos: float = 0.05,
                 sigma_jerk: float = 4.0,
                 init_pos: np.ndarray | None = None,
                 init_vel: np.ndarray | None = None,
                 init_pos_cov: float = 0.5,
                 init_vel_cov: float = 1.0):
        self.x = np.zeros(6)
        if init_pos is not None:
            self.x[0:3] = np.asarray(init_pos, dtype=float)
        if init_vel is not None:
            self.x[3:6] = np.asarray(init_vel, dtype=float)
        self.P = np.diag([init_pos_cov] * 3 + [init_vel_cov] * 3).astype(float)
        self.sigma_pos = float(sigma_pos)
        self.sigma_jerk = float(sigma_jerk)

    def predict(self, dt: float) -> None:
        F = np.eye(6)
        F[0:3, 3:6] = dt * np.eye(3)

        # Discrete-time process noise from a continuous white-jerk driver.
        G = np.zeros((6, 3))
        G[0:3, :] = 0.5 * dt * dt * np.eye(3)
        G[3:6, :] = dt * np.eye(3)
        Q = (G @ G.T) * (self.sigma_jerk ** 2)

        self.x = F @ self.x
        self.P = F @ self.P @ F.T + Q

    def update_position(self, z_pos: np.ndarray) -> None:
        H = np.zeros((3, 6))
        H[:, 0:3] = np.eye(3)
        R = np.eye(3) * (self.sigma_pos ** 2)

        z = np.asarray(z_pos, dtype=float).reshape(3)
        y = z - H @ self.x
        S = H @ self.P @ H.T + R
        K = self.P @ H.T @ np.linalg.inv(S)
        self.x = self.x + K @ y
        self.P = (np.eye(6) - K @ H) @ self.P
        # Symmetrise to fight numerical drift.
        self.P = 0.5 * (self.P + self.P.T)

    @property
    def pos(self) -> np.ndarray:
        return self.x[0:3].copy()

    @property
    def vel(self) -> np.ndarray:
        return self.x[3:6].copy()

    @property
    def pos_cov_trace(self) -> float:
        return float(np.trace(self.P[0:3, 0:3]))

    @property
    def vel_cov_trace(self) -> float:
        return float(np.trace(self.P[3:6, 3:6]))

    @property
    def pos_std(self) -> np.ndarray:
        """Per-axis 1-sigma position uncertainty."""
        return np.sqrt(np.diag(self.P[0:3, 0:3]))
