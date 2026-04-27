"""
Quadrotor 6-DOF rigid-body dynamic model.

State vector (12):
    [x, y, z,           inertial position (ENU, m)
     vx, vy, vz,        inertial velocity (m/s)
     phi, theta, psi,   roll, pitch, yaw (rad, ZYX Euler)
     p, q, r]           body angular rates (rad/s)

Control input (4):
    [T, tau_phi, tau_theta, tau_psi]
    - T         : total collective thrust along +z_body (N)
    - tau_*     : body-axis torques (N.m)

Assumptions
-----------
- Rigid body, symmetric inertia tensor (diagonal Ixx, Iyy, Izz).
- Thrust and torques act instantaneously (no rotor/actuator dynamics).
- Small-body aerodynamic drag modeled as linear in inertial velocity.
- Flat, non-rotating Earth; constant gravity.
- Wind disturbance is an additive inertial-frame force (N).

These are standard simplifications for GNC controller development and are
sufficient to exercise attitude stabilization, altitude hold, and
outer-loop waypoint guidance.
"""

from dataclasses import dataclass, field
import numpy as np

from ..utils.rotations import euler_to_rotmat, body_rates_to_euler_rates


@dataclass
class QuadrotorParams:
    mass: float = 1.2                        # kg
    g: float = 9.81                          # m/s^2
    Ixx: float = 0.0123                      # kg.m^2
    Iyy: float = 0.0123                      # kg.m^2
    Izz: float = 0.0224                      # kg.m^2
    drag_coeff: np.ndarray = field(
        default_factory=lambda: np.array([0.10, 0.10, 0.15])
    )                                        # linear drag [N / (m/s)]
    thrust_min: float = 0.0                  # N
    thrust_max: float = 30.0                 # N
    tau_max: float = 2.0                     # N.m (per axis)

    @property
    def inertia(self) -> np.ndarray:
        return np.diag([self.Ixx, self.Iyy, self.Izz])

    @property
    def hover_thrust(self) -> float:
        return self.mass * self.g


class QuadrotorModel:
    """Continuous-time nonlinear dynamics: x_dot = f(x, u, d)."""

    STATE_DIM = 12
    INPUT_DIM = 4

    def __init__(self, params: QuadrotorParams | None = None):
        self.p = params if params is not None else QuadrotorParams()

    def saturate_input(self, u: np.ndarray) -> np.ndarray:
        """Clamp thrust and torques to physical actuator limits."""
        u_sat = np.array(u, dtype=float, copy=True)
        u_sat[0] = np.clip(u_sat[0], self.p.thrust_min, self.p.thrust_max)
        u_sat[1:] = np.clip(u_sat[1:], -self.p.tau_max, self.p.tau_max)
        return u_sat

    def dynamics(self, state: np.ndarray, u: np.ndarray,
                 wind_force: np.ndarray | None = None) -> np.ndarray:
        """
        Compute state derivative x_dot given state, input, and optional wind force.

        Parameters
        ----------
        state : (12,) ndarray
        u     : (4,)  ndarray  -> [T, tau_phi, tau_theta, tau_psi]
        wind_force : (3,) ndarray or None  -> inertial-frame disturbance [N]
        """
        p = self.p
        u = self.saturate_input(u)
        if wind_force is None:
            wind_force = np.zeros(3)

        # Unpack state
        vx, vy, vz = state[3], state[4], state[5]
        phi, theta, psi = state[6], state[7], state[8]
        om = state[9:12]  # body angular rates [p, q, r]

        T = u[0]
        tau = u[1:4]

        # --- Translational dynamics (inertial frame) ------------------------
        R = euler_to_rotmat(phi, theta, psi)
        thrust_inertial = R @ np.array([0.0, 0.0, T])
        gravity = np.array([0.0, 0.0, -p.mass * p.g])
        drag = -p.drag_coeff * np.array([vx, vy, vz])

        accel = (thrust_inertial + gravity + drag + wind_force) / p.mass

        # --- Rotational dynamics (body frame) -------------------------------
        # I*omega_dot + omega x (I*omega) = tau
        I = p.inertia
        omega_dot = np.linalg.solve(I, tau - np.cross(om, I @ om))

        # --- Kinematics -----------------------------------------------------
        euler_dot = body_rates_to_euler_rates(phi, theta, om[0], om[1], om[2])

        dx = np.zeros(self.STATE_DIM)
        dx[0:3]  = [vx, vy, vz]
        dx[3:6]  = accel
        dx[6:9]  = euler_dot
        dx[9:12] = omega_dot
        return dx

    def rk4_step(self, state: np.ndarray, u: np.ndarray, dt: float,
                 wind_force: np.ndarray | None = None) -> np.ndarray:
        """One classical Runge-Kutta 4 integration step."""
        k1 = self.dynamics(state, u, wind_force)
        k2 = self.dynamics(state + 0.5 * dt * k1, u, wind_force)
        k3 = self.dynamics(state + 0.5 * dt * k2, u, wind_force)
        k4 = self.dynamics(state + dt * k3, u, wind_force)
        return state + (dt / 6.0) * (k1 + 2 * k2 + 2 * k3 + k4)

    @staticmethod
    def initial_state(position=(0.0, 0.0, 0.0),
                      velocity=(0.0, 0.0, 0.0),
                      euler=(0.0, 0.0, 0.0),
                      body_rates=(0.0, 0.0, 0.0)) -> np.ndarray:
        s = np.zeros(QuadrotorModel.STATE_DIM)
        s[0:3]  = position
        s[3:6]  = velocity
        s[6:9]  = euler
        s[9:12] = body_rates
        return s
