"""
Tests for the realistic sensor models (IMU + star tracker).

  1. ``SensorNoise.imu`` with default args matches the legacy constant-bias
     white-noise model (regression guard for the EKF integration test).
  2. Scale factor + misalignment show up correctly in the measurement.
  3. ``step_biases`` produces a random walk whose growth is ~ sigma sqrt(t).
  4. ``StarTracker`` measurement is close to truth (≤ 5σ in angular
     distance) and respects the configured measurement rate.
"""

from __future__ import annotations

import unittest

import numpy as np

from src.disturbances import SensorNoise, StarTracker
from src.utils.quaternion import euler_to_quat, quat_multiply


def _quat_inverse(q):
    return np.array([q[0], -q[1], -q[2], -q[3]])


def _angular_distance(q_a, q_b) -> float:
    q_err = quat_multiply(q_a, _quat_inverse(q_b))
    w = abs(float(q_err[0]))
    return 2.0 * np.arccos(min(w, 1.0))


class IMUModelTests(unittest.TestCase):

    def test_default_imu_is_legacy(self):
        # No scale, no misalignment, no walk — should reduce to the
        # original a_true + b_a + n_a, w_true + b_g + n_g.
        rng = np.random.default_rng(0)
        sens = SensorNoise(rng=rng)
        a_true = np.array([0.5, -0.2, 9.81])
        w_true = np.array([0.1, 0.0, -0.05])
        a, w = sens.imu(a_true, w_true)
        # Mean of many draws should converge to a_true + bias.
        rng2 = np.random.default_rng(0)
        sens2 = SensorNoise(rng=rng2)
        N = 5000
        acc = np.zeros(3)
        for _ in range(N):
            ai, _ = sens2.imu(a_true, w_true)
            acc += ai
        mean_a = acc / N
        expected = a_true + sens2.accel_bias
        self.assertLess(np.linalg.norm(mean_a - expected), 0.02,
                        f"IMU mean drifted: {mean_a} vs {expected}")

    def test_misalignment_couples_axes(self):
        # 5° rotation about z should leak ~sin(5°) of x-acceleration into y.
        sens = SensorNoise(
            accel_bias=(0, 0, 0), gyro_bias_deg=(0, 0, 0),
            accel_std=0.0, gyro_std_deg=0.0,
            accel_misalignment_deg=(0.0, 0.0, 5.0),
            rng=np.random.default_rng(0),
        )
        a, _ = sens.imu(np.array([1.0, 0.0, 0.0]), np.zeros(3))
        # Rotated x-axis in the misaligned frame: (cos5, sin5, 0)
        self.assertAlmostEqual(a[0], np.cos(np.deg2rad(5)), places=5)
        self.assertAlmostEqual(a[1], np.sin(np.deg2rad(5)), places=5)

    def test_scale_factor(self):
        sens = SensorNoise(
            accel_bias=(0, 0, 0), gyro_bias_deg=(0, 0, 0),
            accel_std=0.0, gyro_std_deg=0.0,
            accel_scale_factor=(1.02, 0.98, 1.00),
            rng=np.random.default_rng(0),
        )
        a, _ = sens.imu(np.array([1.0, 1.0, 1.0]), np.zeros(3))
        np.testing.assert_allclose(a, [1.02, 0.98, 1.0], atol=1e-6)

    def test_bias_random_walk_growth(self):
        # Walk std after T seconds: sigma_walk * sqrt(T)
        sigma = 0.01  # m/s^2 / sqrt(s)
        T = 100.0
        dt = 0.01
        N_steps = int(T / dt)
        N_runs = 200
        finals = np.zeros((N_runs, 3))
        for r in range(N_runs):
            sens = SensorNoise(
                accel_bias=(0, 0, 0), gyro_bias_deg=(0, 0, 0),
                accel_bias_walk=sigma,
                rng=np.random.default_rng(1000 + r),
            )
            for _ in range(N_steps):
                sens.step_biases(dt)
            finals[r] = sens.accel_bias
        empirical = finals.std(axis=0).mean()
        expected  = sigma * np.sqrt(T)
        # Allow 25% Monte-Carlo slack on the std estimate.
        self.assertLess(abs(empirical - expected) / expected, 0.25,
                        f"bias walk std {empirical:.4f} vs expected {expected:.4f}")


class StarTrackerTests(unittest.TestCase):

    def test_measurement_close_to_truth(self):
        st = StarTracker(rate_hz=2.0, boresight_arcsec=5.0, roll_arcsec=30.0,
                         rng=np.random.default_rng(7))
        q_true = euler_to_quat(0.05, -0.10, 0.30)
        # 95th-percentile of angular distance should be on the order of
        # the largest noise component (roll ≈ 30 arcsec ≈ 1.45e-4 rad).
        N = 1000
        errs = np.zeros(N)
        for i in range(N):
            q_meas = st.measure(q_true)
            errs[i] = _angular_distance(q_true, q_meas)
        p95 = np.percentile(errs, 95)
        roll_rad = np.deg2rad(30.0 / 3600.0)
        self.assertLess(p95, 5.0 * roll_rad,
                        f"star tracker 95p err {p95:.2e} rad >> 5σ_roll {5*roll_rad:.2e}")

    def test_rate_gating(self):
        st = StarTracker(rate_hz=2.0, rng=np.random.default_rng(0))
        # At 2 Hz: dt_meas = 0.5s. ready() should fire at t=0, 0.5, 1.0, ...
        self.assertTrue(st.ready(0.0))
        self.assertFalse(st.ready(0.1))
        self.assertFalse(st.ready(0.4))
        self.assertTrue(st.ready(0.5))
        self.assertTrue(st.ready(1.0))

    def test_anisotropic_noise(self):
        # Roll-axis noise should dominate the cross-boresight components when
        # roll_arcsec >> boresight_arcsec.
        st = StarTracker(boresight_arcsec=2.0, roll_arcsec=60.0,
                         boresight_axis=(1.0, 0.0, 0.0),
                         rng=np.random.default_rng(11))
        q_true = np.array([1.0, 0.0, 0.0, 0.0])  # identity
        N = 2000
        dthetas = np.zeros((N, 3))
        for i in range(N):
            qm = st.measure(q_true)
            # Small-angle: dtheta ≈ 2 * vec(qm) (since q_true is identity)
            dthetas[i] = 2.0 * qm[1:4] * np.sign(qm[0])
        std = dthetas.std(axis=0)
        # Boresight (x) should be ~10x noisier than y/z.
        self.assertGreater(std[0], 4.0 * std[1])
        self.assertGreater(std[0], 4.0 * std[2])


if __name__ == "__main__":
    unittest.main()
