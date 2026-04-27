"""
Star tracker attitude sensor.

A star tracker outputs an estimate of the body-to-inertial attitude
quaternion at a slow but very accurate rate (typ 1–10 Hz, arcsec class).
The dominant noise model is anisotropic: noise about the boresight axis
(roll-about-the-camera) is ~3–10x larger than cross-boresight, because
roll is constrained only by star spacing, not by the focal-plane angular
resolution.

Convention:
  - Boresight is body +x by default. Override via ``boresight_axis``.
  - Quaternion = body-to-inertial, scalar-first (matches utils/quaternion.py).
  - Output rate is enforced via ``ready(t, dt)``; the simulator polls
    ``ready`` and only consumes a fix when True.
"""

from __future__ import annotations

import numpy as np

from ..utils.quaternion import quat_multiply, quat_normalize, quat_from_small_angle


class StarTracker:
    def __init__(self,
                 rate_hz: float = 2.0,
                 boresight_arcsec: float = 5.0,
                 roll_arcsec: float = 30.0,
                 boresight_axis: tuple[float, float, float] = (1.0, 0.0, 0.0),
                 rng: np.random.Generator | None = None):
        self.dt_meas = 1.0 / float(rate_hz)
        self.sigma_b = np.deg2rad(boresight_arcsec / 3600.0)
        self.sigma_r = np.deg2rad(roll_arcsec / 3600.0)

        b = np.asarray(boresight_axis, dtype=float)
        b = b / max(np.linalg.norm(b), 1e-12)
        self.boresight = b

        # Build an orthonormal frame whose first column is the boresight axis.
        # The two cross-boresight axes share sigma_b; the boresight axis carries
        # the larger roll noise.
        helper = np.array([0.0, 0.0, 1.0]) if abs(b[2]) < 0.9 else np.array([0.0, 1.0, 0.0])
        c1 = np.cross(b, helper); c1 /= np.linalg.norm(c1)
        c2 = np.cross(b, c1)
        # Per-axis sigma in this body-aligned frame (boresight axis = high noise)
        self._noise_basis = np.column_stack([b, c1, c2])
        self._noise_sigma = np.array([self.sigma_r, self.sigma_b, self.sigma_b])

        self.rng = rng if rng is not None else np.random.default_rng(2)
        self._t_next = 0.0

    def ready(self, t: float) -> bool:
        if t + 1e-12 >= self._t_next:
            self._t_next = t + self.dt_meas
            return True
        return False

    def measure(self, q_true: np.ndarray) -> np.ndarray:
        """Return a noisy body-to-inertial quaternion measurement.

        Applies a small-angle rotation expressed in the body frame so that
        the boresight axis carries the larger roll noise component.
        """
        n = self.rng.standard_normal(3) * self._noise_sigma
        # Rotate the per-axis sample into body frame: dtheta_body = M @ n
        dtheta_body = self._noise_basis @ n
        q_noise = quat_from_small_angle(dtheta_body)
        return quat_normalize(quat_multiply(q_true, q_noise))
