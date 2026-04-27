"""
Rotation utilities for quadrotor kinematics.

Convention
----------
- Inertial frame: ENU (x = East, y = North, z = Up).
- Body frame:     x forward, y left, z up (thrust along +z_body).
- Euler angles:   ZYX sequence (yaw psi, pitch theta, roll phi).
  Rotation from body to inertial: R = Rz(psi) * Ry(theta) * Rx(phi).
"""

import numpy as np


def euler_to_rotmat(phi: float, theta: float, psi: float) -> np.ndarray:
    """Body-to-inertial rotation matrix (ZYX Euler)."""
    cph, sph = np.cos(phi), np.sin(phi)
    cth, sth = np.cos(theta), np.sin(theta)
    cps, sps = np.cos(psi), np.sin(psi)

    R = np.array([
        [cth * cps, sph * sth * cps - cph * sps, cph * sth * cps + sph * sps],
        [cth * sps, sph * sth * sps + cph * cps, cph * sth * sps - sph * cps],
        [-sth,      sph * cth,                    cph * cth],
    ])
    return R


def body_rates_to_euler_rates(phi: float, theta: float,
                               p: float, q: float, r: float) -> np.ndarray:
    """Map body angular rates [p, q, r] to Euler angle derivatives."""
    cph, sph = np.cos(phi), np.sin(phi)
    cth, sth = np.cos(theta), np.sin(theta)
    # Guard against gimbal lock (theta = +/- pi/2). Quadrotors rarely reach this.
    cth = cth if abs(cth) > 1e-6 else np.sign(cth) * 1e-6

    T = np.array([
        [1.0, sph * sth / cth, cph * sth / cth],
        [0.0, cph,             -sph],
        [0.0, sph / cth,       cph / cth],
    ])
    return T @ np.array([p, q, r])


def euler_rates_to_body_rates(phi: float, theta: float,
                               phi_dot: float, theta_dot: float, psi_dot: float
                               ) -> np.ndarray:
    """Inverse transform: Euler-angle derivatives to body rates."""
    cph, sph = np.cos(phi), np.sin(phi)
    cth, sth = np.cos(theta), np.sin(theta)

    W = np.array([
        [1.0,  0.0,  -sth],
        [0.0,  cph,   sph * cth],
        [0.0, -sph,   cph * cth],
    ])
    return W @ np.array([phi_dot, theta_dot, psi_dot])
