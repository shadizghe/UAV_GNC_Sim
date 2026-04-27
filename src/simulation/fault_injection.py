"""
Fault injection — motor failures, IMU dropouts, GPS-denied windows.

Lets the dashboard demonstrate how the closed-loop GNC stack copes (or
fails) with realistic in-flight failure modes.  Three fault types:

    MotorFault   — degrades a single rotor's thrust by ``severity``.
                   severity = 0.0 means total motor loss, 1.0 = nominal.
                   The simulator inverts the rotor mixing matrix, scales
                   the affected rotor, then re-mixes back to (T, taus),
                   so the controller sees the resulting attitude error
                   and reacts.

    IMUFault     — freezes the attitude/rate measurements during the
                   window.  Effectively the controller is flying blind
                   on attitude until it ends.

    GPSFault     — skips the EKF position update during the window.
                   With the EKF on, the filter dead-reckons.  Without
                   it, the controller is fed the last known position.

A `FaultInjector` is just a container of these specs plus three query
helpers used by the simulator loop.  No state of its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable
import numpy as np


# --------------------------------------------------------------------- #
# Rotor allocation helpers (X-config quadrotor)                         #
#                                                                       #
# Rotor numbering (looking down on the airframe, CCW from +X axis):     #
#                                                                       #
#       Rotor 0 (FR)                Rotor 3 (FL)                        #
#                 \                /                                    #
#                  \              /                                     #
#                    -----+-----                                        #
#                  /              \                                     #
#                 /                \                                    #
#       Rotor 1 (BR)                Rotor 2 (BL)                        #
#                                                                       #
# Spin direction alternates so net yaw torque comes from the imbalance  #
# of CW vs CCW pairs.  Rotors 0,2 spin CW (+yaw); rotors 1,3 spin CCW.  #
# --------------------------------------------------------------------- #

DEFAULT_ARM_LENGTH = 0.225   # m
DEFAULT_YAW_COEFF  = 0.025   # N.m / N (drag-to-thrust ratio)


def thrust_torque_to_motors(u: np.ndarray,
                            arm_length: float = DEFAULT_ARM_LENGTH,
                            yaw_coeff: float = DEFAULT_YAW_COEFF) -> np.ndarray:
    """Map (T, tau_phi, tau_theta, tau_psi) -> per-rotor thrust [F0..F3]."""
    T, tx, ty, tz = float(u[0]), float(u[1]), float(u[2]), float(u[3])
    L, c = arm_length, yaw_coeff
    # X-config inversion — rows: front-right, back-right, back-left, front-left
    F0 = T / 4 + tx / (4 * L) + ty / (4 * L) + tz / (4 * c)
    F1 = T / 4 - tx / (4 * L) + ty / (4 * L) - tz / (4 * c)
    F2 = T / 4 - tx / (4 * L) - ty / (4 * L) + tz / (4 * c)
    F3 = T / 4 + tx / (4 * L) - ty / (4 * L) - tz / (4 * c)
    return np.array([F0, F1, F2, F3])


def motors_to_thrust_torque(motors: np.ndarray,
                            arm_length: float = DEFAULT_ARM_LENGTH,
                            yaw_coeff: float = DEFAULT_YAW_COEFF) -> np.ndarray:
    """Inverse: per-rotor thrust -> (T, tau_phi, tau_theta, tau_psi)."""
    F0, F1, F2, F3 = motors
    L, c = arm_length, yaw_coeff
    T  = F0 + F1 + F2 + F3
    tx = ( F0 - F1 - F2 + F3) * L
    ty = ( F0 + F1 - F2 - F3) * L
    tz = ( F0 - F1 + F2 - F3) * c
    return np.array([T, tx, ty, tz])


# --------------------------------------------------------------------- #
# Fault dataclasses                                                     #
# --------------------------------------------------------------------- #

@dataclass
class MotorFault:
    rotor: int                # 0..3
    t_start: float
    t_end: float
    severity: float = 0.0     # 0 = total loss, 1 = nominal


@dataclass
class IMUFault:
    t_start: float
    t_end: float


@dataclass
class GPSFault:
    t_start: float
    t_end: float


@dataclass
class FaultInjector:
    motors: list[MotorFault] = field(default_factory=list)
    imus:   list[IMUFault]   = field(default_factory=list)
    gps:    list[GPSFault]   = field(default_factory=list)

    @classmethod
    def empty(cls) -> "FaultInjector":
        return cls()

    @classmethod
    def from_iterables(cls,
                       motors: Iterable[MotorFault] = (),
                       imus:   Iterable[IMUFault]   = (),
                       gps:    Iterable[GPSFault]   = ()) -> "FaultInjector":
        return cls(list(motors), list(imus), list(gps))

    # --- per-step queries ------------------------------------------------- #

    def motor_severities(self, t: float) -> dict[int, float]:
        """{rotor_idx: severity} for any motor faults active at time t.

        If multiple specs target the same rotor we keep the worst (lowest)
        severity, mirroring how concurrent damage would compound.
        """
        out: dict[int, float] = {}
        for f in self.motors:
            if f.t_start <= t <= f.t_end:
                out[f.rotor] = min(out.get(f.rotor, 1.0), float(f.severity))
        return out

    def imu_dropped(self, t: float) -> bool:
        return any(f.t_start <= t <= f.t_end for f in self.imus)

    def gps_denied(self, t: float) -> bool:
        return any(f.t_start <= t <= f.t_end for f in self.gps)

    def has_any(self) -> bool:
        return bool(self.motors or self.imus or self.gps)

    # --- application ----------------------------------------------------- #

    def apply_motor_failure(self, u: np.ndarray, t: float,
                            arm_length: float = DEFAULT_ARM_LENGTH,
                            yaw_coeff: float = DEFAULT_YAW_COEFF
                            ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Mix to per-rotor → degrade → re-mix back to (T, tau).

        Returns (u_actual, motors_cmd, motors_actual) where:
          * u_actual is what the dynamics should integrate against
          * motors_cmd is what the mixer asked for
          * motors_actual is what the (possibly-failed) rotors deliver
        """
        cmd = thrust_torque_to_motors(u, arm_length, yaw_coeff)
        sev = self.motor_severities(t)
        if not sev:
            return u, cmd, cmd
        actual = cmd.copy()
        for rotor_idx, s in sev.items():
            if 0 <= rotor_idx < 4:
                actual[rotor_idx] = cmd[rotor_idx] * float(s)
        u_actual = motors_to_thrust_torque(actual, arm_length, yaw_coeff)
        return u_actual, cmd, actual
