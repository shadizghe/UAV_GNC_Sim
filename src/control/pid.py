"""
Discrete PID controller with integral anti-windup and output saturation.
"""

import numpy as np


class PID:
    def __init__(self, kp: float, ki: float, kd: float,
                 output_limits: tuple[float, float] = (-np.inf, np.inf),
                 integral_limits: tuple[float, float] = (-np.inf, np.inf),
                 derivative_on_measurement: bool = True):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.output_limits = output_limits
        self.integral_limits = integral_limits
        self.derivative_on_measurement = derivative_on_measurement

        self.integral = 0.0
        self.prev_measurement: float | None = None
        self.prev_error: float | None = None

    def reset(self) -> None:
        self.integral = 0.0
        self.prev_measurement = None
        self.prev_error = None

    def update(self, setpoint: float, measurement: float, dt: float) -> float:
        error = setpoint - measurement

        # Integral with clamping anti-windup
        self.integral += error * dt
        self.integral = float(np.clip(self.integral, *self.integral_limits))

        # Derivative term (on measurement avoids derivative kick)
        if self.derivative_on_measurement:
            if self.prev_measurement is None:
                derivative = 0.0
            else:
                derivative = -(measurement - self.prev_measurement) / dt
        else:
            if self.prev_error is None:
                derivative = 0.0
            else:
                derivative = (error - self.prev_error) / dt

        self.prev_measurement = measurement
        self.prev_error = error

        output = self.kp * error + self.ki * self.integral + self.kd * derivative
        output_clipped = float(np.clip(output, *self.output_limits))

        # Back-calculation anti-windup: undo integration that only fed saturation.
        if output != output_clipped and self.ki != 0.0:
            self.integral -= (output - output_clipped) / self.ki

        return output_clipped
