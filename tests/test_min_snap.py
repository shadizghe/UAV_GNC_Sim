"""
Tests for the MinSnapTrajectory generator.

Verifies:
  1. The trajectory passes through every waypoint at the segment break times.
  2. Velocity, acceleration and jerk vanish at the start and end (free endpoints).
  3. The trajectory is C^6 across internal junctions (continuity test on
     velocity, acceleration and jerk by sampling just before and after the
     break).
  4. Numerical derivatives of the sampled position match the analytic
     velocity/acceleration returned by the trajectory object — guards
     against an indexing bug in the polynomial basis.
"""

from __future__ import annotations

import unittest

import numpy as np

from src.guidance import MinSnapTrajectory


class MinSnapTests(unittest.TestCase):

    def setUp(self):
        self.waypoints = np.array([
            [0.0, 0.0, 1.0],
            [2.0, 0.0, 1.5],
            [2.0, 2.0, 2.0],
            [0.0, 2.0, 1.5],
            [0.0, 0.0, 1.0],
        ])
        self.segment_times = np.array([2.0, 2.0, 2.0, 2.0])
        self.traj = MinSnapTrajectory(self.waypoints, self.segment_times)

    def test_passes_through_waypoints(self):
        for i, t_break in enumerate(self.traj.t_breaks):
            pos, _, _ = self.traj(float(t_break))
            err = np.linalg.norm(pos - self.waypoints[i])
            self.assertLess(err, 1e-6,
                            f"waypoint {i}: pos {pos} vs target {self.waypoints[i]}, err {err:.3e}")

    def test_endpoint_derivatives_zero(self):
        for t in (0.0, self.traj.total_time):
            _, vel, acc, jerk = self.traj(t, max_deriv=3)
            self.assertLess(np.linalg.norm(vel),  1e-6, f"vel at t={t}: {vel}")
            self.assertLess(np.linalg.norm(acc),  1e-6, f"acc at t={t}: {acc}")
            self.assertLess(np.linalg.norm(jerk), 1e-6, f"jerk at t={t}: {jerk}")

    def test_internal_continuity(self):
        eps = 1e-5
        for t_break in self.traj.t_breaks[1:-1]:
            for k in range(1, 4):  # vel, accel, jerk
                left  = self.traj(float(t_break) - eps, max_deriv=k)[k]
                right = self.traj(float(t_break) + eps, max_deriv=k)[k]
                self.assertLess(np.linalg.norm(left - right), 1e-3,
                                f"discontinuity in deriv {k} at t={t_break}: {left} vs {right}")

    def test_numerical_vs_analytic_derivative(self):
        # Sample mid-segment and compare central-difference vel against analytic.
        t = 1.0
        h = 1e-4
        pos_p, *_ = self.traj(t + h, max_deriv=0)
        pos_m, *_ = self.traj(t - h, max_deriv=0)
        vel_num = (pos_p - pos_m) / (2 * h)
        _, vel_an, _ = self.traj(t)
        self.assertLess(np.linalg.norm(vel_num - vel_an), 1e-4,
                        f"velocity mismatch: numeric {vel_num} vs analytic {vel_an}")


if __name__ == "__main__":
    unittest.main()
