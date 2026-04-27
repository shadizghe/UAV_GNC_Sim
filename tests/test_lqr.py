"""
Closed-loop tests for the outer-loop LQRController.

Drives the real nonlinear 12-state QuadrotorModel from a 1 m position
offset back to a hover setpoint with the LQR + inner-loop attitude PID
stack, and checks:

  1. The LQR gain is computed and stabilising (P > 0, A - BK Hurwitz).
  2. Closed-loop position error settles to < 5 cm within 8 s.
  3. RMS tracking error is competitive with the existing PID controller
     on the same scenario (within 2x).
"""

from __future__ import annotations

import unittest

import numpy as np

from src.dynamics import QuadrotorModel, QuadrotorParams
from src.control import LQRController, PositionController, AttitudeController


def _run_step(controller, t_final: float = 8.0, dt: float = 0.01) -> np.ndarray:
    """Run a closed-loop 1 m horizontal step and return state history."""
    model = QuadrotorModel(QuadrotorParams())
    att = AttitudeController(
        roll_gains=(6.0, 0.1, 1.2),
        pitch_gains=(6.0, 0.1, 1.2),
        yaw_gains=(4.0, 0.05, 0.8),
        tau_limit=2.0,
    )
    state = QuadrotorModel.initial_state(position=(0.0, 0.0, 2.5))
    target = np.array([1.0, 0.0, 2.5])

    N = int(t_final / dt)
    hist = np.zeros((N, 12))
    for k in range(N):
        pos = state[0:3]
        vel = state[3:6]
        eul = state[6:9]
        euler_cmd, thrust = controller.update(target, pos, eul[2], 0.0, dt, vel)
        tau = att.update(euler_cmd, eul, dt)
        u = np.array([thrust, *tau])
        state = model.rk4_step(state, u, dt)
        hist[k] = state
    return hist, target


class LQRControllerTests(unittest.TestCase):

    def test_gain_is_stabilising(self):
        ctrl = LQRController(mass=1.2)
        Acl = ctrl.A - ctrl.B @ ctrl.K
        eigs = np.linalg.eigvals(Acl)
        self.assertTrue(np.all(eigs.real < -1e-3),
                        f"closed-loop eigenvalues not Hurwitz: {eigs}")
        # P from CARE must be SPD
        eigP = np.linalg.eigvalsh(0.5 * (ctrl.P + ctrl.P.T))
        self.assertTrue(np.all(eigP > 0), f"P not SPD: {eigP}")

    def test_step_response_settles(self):
        ctrl = LQRController(mass=1.2)
        hist, target = _run_step(ctrl)
        final_err = np.linalg.norm(hist[-1, 0:3] - target)
        self.assertLess(final_err, 0.05,
                        f"LQR did not settle: final pos error = {final_err:.3f} m")

    def test_competitive_with_pid(self):
        lqr = LQRController(mass=1.2)
        pid = PositionController(
            mass=1.2, g=9.81,
            xy_gains=(1.2, 0.0, 1.6), z_gains=(4.0, 1.0, 3.0),
            max_tilt_deg=25.0, max_accel_xy=6.0, thrust_limits=(0, 30),
        )
        hist_lqr, target = _run_step(lqr)
        hist_pid, _      = _run_step(pid)

        rms_lqr = np.sqrt(np.mean(np.sum((hist_lqr[:, 0:3] - target) ** 2, axis=1)))
        rms_pid = np.sqrt(np.mean(np.sum((hist_pid[:, 0:3] - target) ** 2, axis=1)))
        # LQR shouldn't be wildly worse than the hand-tuned PID baseline.
        self.assertLess(rms_lqr, 2.0 * rms_pid,
                        f"LQR RMS {rms_lqr:.3f} vs PID {rms_pid:.3f} — uncompetitive")


if __name__ == "__main__":
    unittest.main()
