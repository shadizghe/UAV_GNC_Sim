"""
Environmental disturbance models.

WindModel
---------
Constant mean wind plus a first-order coloured-noise gust component. This
is a lightweight stand-in for the Dryden turbulence spectrum; it keeps
the physics interpretable while still exercising the controller against
time-correlated disturbances.

SensorNoise
-----------
Additive Gaussian white noise applied to the state vector before it is
handed to the controllers, emulating inertial sensor and GPS noise.
"""

import numpy as np


def _small_angle_rotmat(eul: np.ndarray) -> np.ndarray:
    """ZYX rotation for small misalignment angles (rad)."""
    phi, theta, psi = float(eul[0]), float(eul[1]), float(eul[2])
    cph, sph = np.cos(phi), np.sin(phi)
    cth, sth = np.cos(theta), np.sin(theta)
    cps, sps = np.cos(psi), np.sin(psi)
    return np.array([
        [cth * cps, sph * sth * cps - cph * sps, cph * sth * cps + sph * sps],
        [cth * sps, sph * sth * sps + cph * cps, cph * sth * sps - sph * cps],
        [-sth,      sph * cth,                    cph * cth],
    ])


class WindModel:
    def __init__(self,
                 mean_wind: tuple[float, float, float] = (0.0, 0.0, 0.0),
                 gust_std: tuple[float, float, float] = (0.5, 0.5, 0.2),
                 gust_time_constant: float = 2.0,
                 drag_area: float = 0.1,      # effective drag area (m^2)
                 air_density: float = 1.225,  # kg/m^3
                 rng: np.random.Generator | None = None):
        self.mean_wind = np.asarray(mean_wind, dtype=float)
        self.gust_std = np.asarray(gust_std, dtype=float)
        self.tau = gust_time_constant
        self.k_drag = 0.5 * air_density * drag_area
        self.gust = np.zeros(3)
        self.rng = rng if rng is not None else np.random.default_rng(0)

    def step(self, dt: float, body_velocity_inertial: np.ndarray) -> np.ndarray:
        """
        Advance the gust state and return the inertial-frame force [N]
        acting on the vehicle.

        Wind force is computed from the relative airspeed squared so a
        stationary drone in a steady wind sees a non-zero push.
        """
        # First-order Gauss-Markov gust: tau * dg/dt = -g + sigma * sqrt(2/tau) * w
        noise = self.rng.standard_normal(3) * self.gust_std * np.sqrt(2.0 / self.tau)
        self.gust += (-self.gust / self.tau + noise) * dt

        wind_vel = self.mean_wind + self.gust
        rel_vel = wind_vel - body_velocity_inertial
        speed = np.linalg.norm(rel_vel)
        force = self.k_drag * speed * rel_vel  # quadratic-in-speed drag model
        return force


class SensorNoise:
    """GPS / Euler noise (legacy) plus a strapdown-IMU output channel.

    The original ``corrupt`` API still produces a noisy 12-state copy used
    by the legacy controllers and by the constant-velocity Kalman filter.
    The new ``imu`` API returns body-frame accelerometer + gyroscope
    measurements with constant biases and white noise — what the 15-state
    INS/GPS EKF consumes.

    GPS is modelled as a position fix arriving at ``gps_rate_hz``; the
    Simulator decides at each step whether the EKF should consume the
    fix based on this cadence.
    """
    def __init__(self,
                 position_std: float = 0.02,
                 velocity_std: float = 0.05,
                 attitude_std_deg: float = 0.3,
                 rate_std_deg: float = 1.0,
                 attitude_bias_deg: tuple[float, float, float] = (0.0, 0.0, 0.0),
                 # IMU model (body-frame strapdown sensor)
                 accel_std: float = 0.10,                              # m/s^2 white noise
                 gyro_std_deg: float = 0.50,                           # deg/s white noise
                 accel_bias: tuple[float, float, float] = (0.04, -0.03, 0.05),
                 gyro_bias_deg: tuple[float, float, float] = (0.40, -0.30, 0.25),
                 # Optional realism extensions — defaults preserve legacy behavior
                 accel_bias_walk: float = 0.0,                         # m/s^2 / sqrt(s)
                 gyro_bias_walk_deg: float = 0.0,                      # deg/s / sqrt(s)
                 accel_scale_factor: tuple[float, float, float] = (1.0, 1.0, 1.0),
                 gyro_scale_factor:  tuple[float, float, float] = (1.0, 1.0, 1.0),
                 accel_misalignment_deg: tuple[float, float, float] = (0.0, 0.0, 0.0),
                 gyro_misalignment_deg:  tuple[float, float, float] = (0.0, 0.0, 0.0),
                 gps_rate_hz: float = 10.0,
                 rng: np.random.Generator | None = None):
        self.pos_std = position_std
        self.vel_std = velocity_std
        self.att_std = np.deg2rad(attitude_std_deg)
        self.rate_std = np.deg2rad(rate_std_deg)
        self.att_bias = np.deg2rad(np.asarray(attitude_bias_deg, dtype=float))

        self.accel_std = float(accel_std)
        self.gyro_std = np.deg2rad(gyro_std_deg)
        self.accel_bias = np.asarray(accel_bias, dtype=float).copy()
        self.gyro_bias = np.deg2rad(np.asarray(gyro_bias_deg, dtype=float))
        self.gps_rate_hz = float(gps_rate_hz)

        # Bias random walks (zero by default → constant biases, legacy).
        self.accel_bias_walk = float(accel_bias_walk)
        self.gyro_bias_walk  = np.deg2rad(gyro_bias_walk_deg)

        # Scale-factor and misalignment.
        self.accel_scale = np.asarray(accel_scale_factor, dtype=float)
        self.gyro_scale  = np.asarray(gyro_scale_factor,  dtype=float)
        self._M_accel = _small_angle_rotmat(np.deg2rad(accel_misalignment_deg))
        self._M_gyro  = _small_angle_rotmat(np.deg2rad(gyro_misalignment_deg))

        self.rng = rng if rng is not None else np.random.default_rng(1)

    def corrupt(self, state: np.ndarray) -> np.ndarray:
        n = self.rng.standard_normal(12)
        noisy = state.copy()
        noisy[0:3]  += n[0:3]  * self.pos_std
        noisy[3:6]  += n[3:6]  * self.vel_std
        noisy[6:9]  += n[6:9]  * self.att_std + self.att_bias
        noisy[9:12] += n[9:12] * self.rate_std
        return noisy

    def imu(self, accel_body_true: np.ndarray, gyro_body_true: np.ndarray
            ) -> tuple[np.ndarray, np.ndarray]:
        """Return (accel_meas, gyro_meas) in body frame.

        Full strapdown error model:
            accel_meas = M_a (S_a ⊙ f_body) + b_a + n_a
            gyro_meas  = M_g (S_g ⊙ omega_body) + b_g + n_g
        Misalignment matrices ``M_*`` and scale-factor diagonals ``S_*``
        default to identity and unity, so legacy callers see the original
        constant-bias + white-noise model.
        """
        n = self.rng.standard_normal(6)
        a_true = np.asarray(accel_body_true, dtype=float)
        w_true = np.asarray(gyro_body_true,  dtype=float)
        a_meas = self._M_accel @ (self.accel_scale * a_true) + self.accel_bias + n[0:3] * self.accel_std
        w_meas = self._M_gyro  @ (self.gyro_scale  * w_true) + self.gyro_bias  + n[3:6] * self.gyro_std
        return a_meas, w_meas

    def step_biases(self, dt: float) -> None:
        """Advance accelerometer/gyro biases as random walks of strength
        ``accel_bias_walk`` and ``gyro_bias_walk``. No-op when both are zero."""
        if self.accel_bias_walk > 0.0:
            self.accel_bias += self.rng.standard_normal(3) * self.accel_bias_walk * np.sqrt(dt)
        if self.gyro_bias_walk > 0.0:
            self.gyro_bias  += self.rng.standard_normal(3) * self.gyro_bias_walk  * np.sqrt(dt)
