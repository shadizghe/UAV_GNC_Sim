"""
Mission and controller configuration.

Edit this file to tune gains, change the waypoint plan, or toggle the
disturbance models. Everything is plain Python so the scenario is easy
to diff and version-control.
"""

import numpy as np

from src.dynamics import QuadrotorParams


# ---------------------------------------------------------------------- #
# Vehicle
# ---------------------------------------------------------------------- #
QUADROTOR = QuadrotorParams(
    mass=1.2,
    g=9.81,
    Ixx=0.0123,
    Iyy=0.0123,
    Izz=0.0224,
    drag_coeff=np.array([0.10, 0.10, 0.15]),
    thrust_min=0.0,
    thrust_max=30.0,
    tau_max=2.0,
)

# ---------------------------------------------------------------------- #
# Simulation
# ---------------------------------------------------------------------- #
DT       = 0.01       # integration step [s]
T_FINAL  = 40.0       # total simulation time [s]

INITIAL_POSITION = (0.0, 0.0, 0.0)
INITIAL_EULER    = (0.0, 0.0, 0.0)

# ---------------------------------------------------------------------- #
# Mission plan (inertial ENU, metres)
# ---------------------------------------------------------------------- #
WAYPOINTS = np.array([
    [0.0,  0.0,  2.5],   # take-off / climb
    [5.0,  0.0,  2.5],
    [5.0,  5.0,  3.5],
    [0.0,  5.0,  3.5],
    [0.0,  0.0,  3.0],   # return
    [0.0,  0.0,  0.2],   # land
])
YAW_SETPOINTS = np.zeros(len(WAYPOINTS))
ACCEPTANCE_RADIUS = 0.35  # [m]

# ---------------------------------------------------------------------- #
# Controller gains
# ---------------------------------------------------------------------- #
CONTROLLER = "pid"     # "pid" (cascaded PID) or "lqr" (CARE-based outer loop)

POSITION_XY_GAINS = (1.2, 0.0, 1.6)    # (kp, ki, kd)
POSITION_Z_GAINS  = (4.0, 1.0, 3.0)
MAX_TILT_DEG      = 25.0
MAX_ACCEL_XY      = 6.0

ROLL_GAINS  = (6.0, 0.1, 1.2)
PITCH_GAINS = (6.0, 0.1, 1.2)
YAW_GAINS   = (4.0, 0.05, 0.8)

# LQR weights — Bryson-rule sized for ~1 m position errors and ~25° tilt.
# The thrust penalty is set so the controller stays well below its 30 N
# saturation limit during typical waypoint chases.
LQR_Q_DIAG = (10.0, 10.0, 8.0, 3.0, 3.0, 4.0)    # [ex, ey, ez, vx, vy, vz]
LQR_R_DIAG = (10.0, 10.0, 0.5)                   # [theta, phi, dT]

# ---------------------------------------------------------------------- #
# Trajectory generation
# ---------------------------------------------------------------------- #
TRAJECTORY = "waypoint"     # "waypoint" (legacy hops) or "minsnap"
MINSNAP_SEGMENT_TIME = 4.0  # uniform per-segment duration when TRAJECTORY="minsnap"

# ---------------------------------------------------------------------- #
# Environment
# ---------------------------------------------------------------------- #
ENABLE_WIND         = True
MEAN_WIND           = (1.5, 0.5, 0.0)   # m/s, inertial frame
GUST_STD            = (0.6, 0.6, 0.2)   # m/s
GUST_TIME_CONSTANT  = 2.0               # s

ENABLE_SENSOR_NOISE = True
POSITION_STD        = 0.05              # m   (matches EKF sigma_gps)
VELOCITY_STD        = 0.05              # m/s
ATTITUDE_STD_DEG    = 0.3
RATE_STD_DEG        = 1.0

# ---------------------------------------------------------------------- #
# State estimation
# ---------------------------------------------------------------------- #
ENABLE_EKF          = True
EKF_SIGMA_A         = 0.20              # accel noise PSD     [m/s^2]
EKF_SIGMA_G_DEG     = 1.5               # gyro  noise PSD     [deg/s]
EKF_SIGMA_BA        = 0.005             # accel bias walk     [m/s^2 / sqrt(s)]
EKF_SIGMA_BG_DEG    = 0.05              # gyro  bias walk     [deg/s / sqrt(s)]
EKF_SIGMA_GPS       = 0.05              # GPS 1-sigma         [m]
EKF_GPS_RATE_HZ     = 10.0

RNG_SEED = 42
