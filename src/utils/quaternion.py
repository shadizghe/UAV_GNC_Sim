"""
Quaternion helpers for the INS/GPS EKF.

Convention (Hamilton, scalar-first):
    q = [w, x, y, z],   body-to-inertial rotation,
    v_inertial = q (x) v_body (x) q*

The quaternion product (x) used here is q1 (x) q2 = R(q1) R(q2) when
interpreted as rotation composition, i.e. q1 then q2 in the active form.
"""

from __future__ import annotations

import numpy as np


def skew(v: np.ndarray) -> np.ndarray:
    """3x3 skew-symmetric matrix from a 3-vector (cross-product operator)."""
    x, y, z = float(v[0]), float(v[1]), float(v[2])
    return np.array([
        [0.0, -z,   y  ],
        [z,    0.0, -x ],
        [-y,   x,   0.0],
    ])


def quat_normalize(q: np.ndarray) -> np.ndarray:
    q = np.asarray(q, dtype=float)
    n = np.linalg.norm(q)
    if n == 0.0:
        return np.array([1.0, 0.0, 0.0, 0.0])
    return q / n


def quat_multiply(p: np.ndarray, q: np.ndarray) -> np.ndarray:
    """Hamilton product: r = p (x) q."""
    pw, px, py, pz = p
    qw, qx, qy, qz = q
    return np.array([
        pw * qw - px * qx - py * qy - pz * qz,
        pw * qx + px * qw + py * qz - pz * qy,
        pw * qy - px * qz + py * qw + pz * qx,
        pw * qz + px * qy - py * qx + pz * qw,
    ])


def quat_conjugate(q: np.ndarray) -> np.ndarray:
    return np.array([q[0], -q[1], -q[2], -q[3]])


def quat_to_rotmat(q: np.ndarray) -> np.ndarray:
    """Body-to-inertial rotation matrix from a unit quaternion."""
    w, x, y, z = q
    return np.array([
        [1 - 2*(y*y + z*z),   2*(x*y - z*w),     2*(x*z + y*w)  ],
        [2*(x*y + z*w),       1 - 2*(x*x + z*z), 2*(y*z - x*w)  ],
        [2*(x*z - y*w),       2*(y*z + x*w),     1 - 2*(x*x + y*y)],
    ])


def rotmat_to_quat(R: np.ndarray) -> np.ndarray:
    """Stable conversion from a 3x3 rotation matrix to a unit quaternion."""
    tr = R[0, 0] + R[1, 1] + R[2, 2]
    if tr > 0.0:
        s = 2.0 * np.sqrt(1.0 + tr)
        w = 0.25 * s
        x = (R[2, 1] - R[1, 2]) / s
        y = (R[0, 2] - R[2, 0]) / s
        z = (R[1, 0] - R[0, 1]) / s
    elif R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
        s = 2.0 * np.sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2])
        w = (R[2, 1] - R[1, 2]) / s
        x = 0.25 * s
        y = (R[0, 1] + R[1, 0]) / s
        z = (R[0, 2] + R[2, 0]) / s
    elif R[1, 1] > R[2, 2]:
        s = 2.0 * np.sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2])
        w = (R[0, 2] - R[2, 0]) / s
        x = (R[0, 1] + R[1, 0]) / s
        y = 0.25 * s
        z = (R[1, 2] + R[2, 1]) / s
    else:
        s = 2.0 * np.sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1])
        w = (R[1, 0] - R[0, 1]) / s
        x = (R[0, 2] + R[2, 0]) / s
        y = (R[1, 2] + R[2, 1]) / s
        z = 0.25 * s
    q = np.array([w, x, y, z])
    return quat_normalize(q)


def euler_to_quat(phi: float, theta: float, psi: float) -> np.ndarray:
    """ZYX Euler (roll, pitch, yaw) → body-to-inertial quaternion."""
    cp, sp = np.cos(phi / 2), np.sin(phi / 2)
    ct, st = np.cos(theta / 2), np.sin(theta / 2)
    cs, ss = np.cos(psi / 2), np.sin(psi / 2)
    return np.array([
        cp * ct * cs + sp * st * ss,
        sp * ct * cs - cp * st * ss,
        cp * st * cs + sp * ct * ss,
        cp * ct * ss - sp * st * cs,
    ])


def quat_to_euler(q: np.ndarray) -> np.ndarray:
    """Body-to-inertial quaternion → ZYX Euler (roll, pitch, yaw)."""
    w, x, y, z = q
    sinr_cosp = 2.0 * (w * x + y * z)
    cosr_cosp = 1.0 - 2.0 * (x * x + y * y)
    phi = np.arctan2(sinr_cosp, cosr_cosp)

    sinp = 2.0 * (w * y - z * x)
    sinp = np.clip(sinp, -1.0, 1.0)
    theta = np.arcsin(sinp)

    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    psi = np.arctan2(siny_cosp, cosy_cosp)
    return np.array([phi, theta, psi])


def quat_from_small_angle(dtheta: np.ndarray) -> np.ndarray:
    """Exponential map of a small rotation vector dtheta (rad) to a quaternion.

    Uses the exact small-angle formula q = [cos(|θ|/2), sin(|θ|/2) θ̂].
    For very small angles the half-angle approximations are used to avoid
    division by zero.
    """
    theta = float(np.linalg.norm(dtheta))
    if theta < 1e-9:
        # Second-order Taylor in θ — keeps unit norm to first order.
        return quat_normalize(np.array([1.0, 0.5 * dtheta[0], 0.5 * dtheta[1], 0.5 * dtheta[2]]))
    half = 0.5 * theta
    s = np.sin(half) / theta
    return np.array([np.cos(half), s * dtheta[0], s * dtheta[1], s * dtheta[2]])
