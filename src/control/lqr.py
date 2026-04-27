"""
Outer-loop LQR for the cascaded quadrotor controller.

Linearises translational dynamics about hover in the yaw-aligned ("course")
frame, where horizontal motion is decoupled from yaw:

    state  xi = [ex_c, ey_c, ez, vx_c, vy_c, vz]^T   (course-frame errors + vel)
    input  u  = [theta_cmd, phi_cmd, dT]^T

with continuous-time model

    xi_dot = A xi + B u,
    A = [[0_3, I_3], [0_3, 0_3]],
    B = [[0_3], [diag(g, -g, 1/m)]]

The infinite-horizon LQR gain is K = R^{-1} B^T P, with P from
solve_continuous_are(A, B, Q, R). On every update the controller rotates
the inertial position error and velocity into the yaw-aligned frame, applies
u = -K xi, then maps the third channel back to body thrust as
T = m*g + dT. Output mirrors `PositionController.update` so the two are
swappable in the cascaded loop.
"""

from __future__ import annotations

import numpy as np
from scipy.linalg import solve_continuous_are


class LQRController:
    def __init__(self,
                 mass: float,
                 g: float = 9.81,
                 Q: np.ndarray | None = None,
                 R: np.ndarray | None = None,
                 max_tilt_deg: float = 25.0,
                 thrust_limits: tuple[float, float] = (0.0, 30.0)):
        self.mass = float(mass)
        self.g = float(g)
        self.max_tilt = np.deg2rad(max_tilt_deg)
        self.thrust_limits = thrust_limits

        # Bryson-rule defaults, hand-tuned for a ~1 kg quad.
        if Q is None:
            Q = np.diag([10.0, 10.0, 20.0, 3.0, 3.0, 8.0])
        if R is None:
            R = np.diag([8.0, 8.0, 0.05])

        A = np.zeros((6, 6))
        A[0:3, 3:6] = np.eye(3)
        B = np.zeros((6, 3))
        B[3, 0] = self.g          # vx_c_dot = +g * theta_cmd
        B[4, 1] = -self.g         # vy_c_dot = -g * phi_cmd
        B[5, 2] = 1.0 / self.mass # vz_dot   = (1/m) * dT

        self.A, self.B, self.Q, self.R = A, B, Q, R
        self.P = solve_continuous_are(A, B, Q, R)
        self.K = np.linalg.solve(R, B.T @ self.P)

    def reset(self) -> None:
        # Stateless controller; nothing to reset. Kept for API parity.
        pass

    def update(self, pos_cmd: np.ndarray, pos_meas: np.ndarray,
               yaw_meas: float, yaw_cmd: float, dt: float,
               vel_meas: np.ndarray | None = None,
               vel_cmd: np.ndarray | None = None,
               accel_cmd: np.ndarray | None = None,
               ) -> tuple[np.ndarray, float]:
        if vel_meas is None:
            vel_meas = np.zeros(3)
        if vel_cmd is None:
            vel_cmd = np.zeros(3)
        if accel_cmd is None:
            accel_cmd = np.zeros(3)

        c, s = np.cos(yaw_meas), np.sin(yaw_meas)
        Rzy = np.array([[ c,  s, 0.0],
                        [-s,  c, 0.0],
                        [0.0, 0.0, 1.0]])

        err_w = np.asarray(pos_meas, dtype=float) - np.asarray(pos_cmd, dtype=float)
        vel_err_w = np.asarray(vel_meas, dtype=float) - np.asarray(vel_cmd, dtype=float)

        xi = np.concatenate([Rzy @ err_w, Rzy @ vel_err_w])
        u_fb = -self.K @ xi

        # Trajectory feedforward: invert the linearised dynamics to find the
        # control that would track the reference exactly (in the absence of
        # disturbances). The regulator then only has to handle errors.
        a_c = Rzy @ np.asarray(accel_cmd, dtype=float)
        u_ff = np.array([
             a_c[0] / self.g,
            -a_c[1] / self.g,
             self.mass * a_c[2],
        ])

        u = u_fb + u_ff

        theta_cmd = float(np.clip(u[0], -self.max_tilt, self.max_tilt))
        phi_cmd   = float(np.clip(u[1], -self.max_tilt, self.max_tilt))
        thrust    = float(np.clip(self.mass * self.g + u[2], *self.thrust_limits))

        euler_cmd = np.array([phi_cmd, theta_cmd, yaw_cmd])
        return euler_cmd, thrust
