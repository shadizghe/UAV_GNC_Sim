"""
Inner-loop attitude controller.

Three independent PID loops (roll, pitch, yaw) produce body-axis torques
from commanded Euler angles. Yaw error is wrapped to (-pi, pi] so the
drone always takes the shortest angular path.
"""

import numpy as np
from .pid import PID


def wrap_angle(a: float) -> float:
    return (a + np.pi) % (2 * np.pi) - np.pi


class AttitudeController:
    def __init__(self,
                 roll_gains=(6.0, 0.1, 1.2),
                 pitch_gains=(6.0, 0.1, 1.2),
                 yaw_gains=(4.0, 0.05, 0.8),
                 tau_limit: float = 2.0):
        lim = (-tau_limit, tau_limit)
        i_lim = (-0.5, 0.5)
        self.roll_pid  = PID(*roll_gains,  output_limits=lim, integral_limits=i_lim)
        self.pitch_pid = PID(*pitch_gains, output_limits=lim, integral_limits=i_lim)
        self.yaw_pid   = PID(*yaw_gains,   output_limits=lim, integral_limits=i_lim)

    def reset(self) -> None:
        self.roll_pid.reset()
        self.pitch_pid.reset()
        self.yaw_pid.reset()

    def update(self, euler_cmd: np.ndarray, euler_meas: np.ndarray,
               dt: float) -> np.ndarray:
        phi_cmd, theta_cmd, psi_cmd = euler_cmd
        phi, theta, psi = euler_meas

        # Shortest-path yaw correction.
        psi_err = wrap_angle(psi_cmd - psi)
        psi_meas_effective = psi_cmd - psi_err  # so PID sees (cmd - meas) = psi_err

        tau_phi   = self.roll_pid.update(phi_cmd,   phi,   dt)
        tau_theta = self.pitch_pid.update(theta_cmd, theta, dt)
        tau_psi   = self.yaw_pid.update(psi_cmd,   psi_meas_effective, dt)

        return np.array([tau_phi, tau_theta, tau_psi])
