"""
Outer-loop position and altitude controller.

Implements the standard near-hover cascaded scheme:

    position error -> desired inertial acceleration (PID)
                   -> commanded roll, pitch (small-angle inversion of R)
                   -> commanded collective thrust (altitude channel)

Yaw setpoint is passed through directly (typically user-specified or
aligned with the velocity vector).
"""

import numpy as np
from .pid import PID


class PositionController:
    def __init__(self,
                 mass: float,
                 g: float = 9.81,
                 xy_gains=(1.2, 0.0, 1.5),
                 z_gains=(4.0, 1.0, 3.0),
                 max_tilt_deg: float = 25.0,
                 max_accel_xy: float = 6.0,
                 max_speed_xy: float | None = None,
                 thrust_limits: tuple[float, float] = (0.0, 30.0)):
        self.mass = mass
        self.g = g
        self.max_tilt = np.deg2rad(max_tilt_deg)
        self.max_accel_xy = max_accel_xy
        self.max_speed_xy = max_speed_xy
        self.thrust_limits = thrust_limits

        a_lim = (-max_accel_xy, max_accel_xy)
        self.x_pid = PID(*xy_gains, output_limits=a_lim, integral_limits=(-1.0, 1.0))
        self.y_pid = PID(*xy_gains, output_limits=a_lim, integral_limits=(-1.0, 1.0))
        self.z_pid = PID(*z_gains,  output_limits=(-8.0, 8.0),
                         integral_limits=(-3.0, 3.0))

    def reset(self) -> None:
        self.x_pid.reset()
        self.y_pid.reset()
        self.z_pid.reset()

    def update(self, pos_cmd: np.ndarray, pos_meas: np.ndarray,
               yaw_meas: float, yaw_cmd: float, dt: float,
               vel_meas: np.ndarray | None = None
               ) -> tuple[np.ndarray, float]:
        """
        Parameters
        ----------
        pos_cmd, pos_meas : (3,) ndarray  inertial [x, y, z]
        yaw_meas, yaw_cmd : float         rad
        dt                : float         s

        Returns
        -------
        euler_cmd : (3,) ndarray  [phi_cmd, theta_cmd, psi_cmd]
        thrust    : float          N
        """
        ax_des = self.x_pid.update(pos_cmd[0], pos_meas[0], dt)
        ay_des = self.y_pid.update(pos_cmd[1], pos_meas[1], dt)
        az_des = self.z_pid.update(pos_cmd[2], pos_meas[2], dt)

        if self.max_speed_xy is not None and self.max_speed_xy > 0 and vel_meas is not None:
            vel_xy = np.asarray(vel_meas[0:2], dtype=float)
            speed_xy = float(np.linalg.norm(vel_xy))
            if speed_xy >= self.max_speed_xy:
                vel_dir = vel_xy / max(speed_xy, 1e-6)
                accel_xy = np.array([ax_des, ay_des], dtype=float)
                accel_along_velocity = float(accel_xy @ vel_dir)
                if accel_along_velocity > 0:
                    accel_xy -= accel_along_velocity * vel_dir
                speed_error = speed_xy - self.max_speed_xy
                braking_accel = min(self.max_accel_xy, speed_error * 2.5)
                accel_xy -= braking_accel * vel_dir
                ax_des, ay_des = accel_xy

        # Collective thrust in body +z: required to produce (g + az_des) vertically.
        # Divide by cos(tilt) later; for near-hover, ignore tilt coupling first.
        thrust = self.mass * (self.g + az_des)
        thrust = float(np.clip(thrust, *self.thrust_limits))

        # Convert desired horizontal accelerations into tilt commands.
        # For small angles: ax = g * (theta*cos(psi) + phi*sin(psi))
        #                   ay = g * (theta*sin(psi) - phi*cos(psi))
        c, s = np.cos(yaw_meas), np.sin(yaw_meas)
        theta_cmd =  (ax_des * c + ay_des * s) / self.g
        phi_cmd   =  (ax_des * s - ay_des * c) / self.g

        theta_cmd = float(np.clip(theta_cmd, -self.max_tilt, self.max_tilt))
        phi_cmd   = float(np.clip(phi_cmd,   -self.max_tilt, self.max_tilt))

        euler_cmd = np.array([phi_cmd, theta_cmd, yaw_cmd])
        return euler_cmd, thrust
