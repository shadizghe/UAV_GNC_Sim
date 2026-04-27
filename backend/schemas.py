"""
Pydantic schemas — request/response contracts for the REST API.

These mirror the dicts the existing simulator + presets module already
emit, so we can serialise SimulationResult straight into a JSON response
without any glue layer.
"""

from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field


# ---------- Mission entities -------------------------------------------- #

class WaypointPayload(BaseModel):
    x: float
    y: float
    z: float


class ZonePayload(BaseModel):
    name: str
    cx: float
    cy: float
    r: float
    z_min: float = 0.0
    z_max: float = 6.0
    kind: Literal["no_fly", "threat"] = "no_fly"


class EnemyPayload(BaseModel):
    name: str
    x: float
    y: float
    z: float
    behavior: Literal["patrol", "loiter", "pursue"] = "patrol"
    speed: float = 1.5
    det_r: float = 3.0
    leth_r: float = 1.0
    orbit_cx: float = 0.0
    orbit_cy: float = 0.0
    orbit_r: float = 0.0


class FriendlyDronePayload(BaseModel):
    name: str = "WINGMAN"
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    route_mode: Literal["formation", "same"] = "formation"
    enabled: bool = True


class PresetSummary(BaseModel):
    label: str
    tag: str
    description: str
    duration_s: float
    n_waypoints: int
    n_zones: int
    n_enemies: int
    enable_threats: bool
    enable_geofence: bool


class PresetDetail(PresetSummary):
    waypoints: list[list[float]]   # [[x,y,z], ...]
    yaws_deg: list[float]
    zones: list[ZonePayload]
    enemies: list[EnemyPayload]


# ---------- Simulation request / response ------------------------------- #

class ControllerGains(BaseModel):
    kp_xy: float = 1.2
    ki_xy: float = 0.0
    kd_xy: float = 1.6
    kp_z:  float = 4.0
    ki_z:  float = 1.0
    kd_z:  float = 3.0
    kp_att: float = 6.0
    kd_att: float = 1.2
    kp_yaw: float = 4.0
    kd_yaw: float = 0.8
    max_tilt_deg: float = 35.0
    max_accel_xy: float = 8.0
    max_speed_xy: float = 7.5


class EnvParams(BaseModel):
    enable_wind: bool = True
    wind_x: float = 1.5
    wind_y: float = 0.5
    wind_z: float = 0.0
    gust_std: float = 0.6
    enable_noise: bool = True
    pos_std: float = 0.05
    att_std_deg: float = 0.3


class EstimatorParams(BaseModel):
    enable_ekf: bool = True
    kind: Literal["ins_gps", "position"] = "ins_gps"
    # Constant-velocity Kalman filter tuning (only used when kind="position").
    sigma_jerk: float = 3.0
    # 15-state INS/GPS EKF tuning (only used when kind="ins_gps").
    sigma_a: float = 0.20         # accel noise PSD [m/s^2]
    sigma_g_deg: float = 1.5      # gyro noise PSD  [deg/s]
    sigma_ba: float = 0.005       # accel bias walk [m/s^2 / sqrt(s)]
    sigma_bg_deg: float = 0.05    # gyro  bias walk [deg/s / sqrt(s)]
    sigma_gps: float = 0.05       # GPS position 1-sigma [m]
    gps_rate_hz: float = 10.0     # how often the EKF folds in a GPS fix


class InterceptorBatteryPayload(BaseModel):
    """Ground-launched PN interceptor battery."""

    name: str = "SAM"
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    launch_range: float = Field(10.0, gt=0.0)
    min_engage_alt: float = Field(1.0, ge=0.0)
    cooldown: float = Field(1.4, ge=0.0)
    max_active: int = Field(2, ge=1, le=8)
    max_total_shots: int = Field(2, ge=1, le=24)
    initial_speed: float = Field(5.0, gt=0.0)
    nav_constant: float = Field(4.0, gt=0.0)
    max_lateral_accel: float = Field(55.0, gt=0.0)
    boost_time: float = Field(0.75, ge=0.0)
    boost_accel: float = Field(32.0, ge=0.0)
    coast_drag: float = Field(0.045, ge=0.0)
    lethal_radius: float = Field(0.55, gt=0.0)
    arming_time: float = Field(0.65, ge=0.0)
    max_time: float = Field(8.0, gt=0.0)
    seeker_enabled: bool = True
    seeker_range: float = Field(14.0, gt=0.0)
    seeker_fov_deg: float = Field(70.0, ge=1.0, le=180.0)
    seeker_noise_std_deg: float = Field(0.25, ge=0.0)
    seeker_memory_time: float = Field(0.35, ge=0.0)


def _default_interceptor_batteries() -> list[InterceptorBatteryPayload]:
    return [
        InterceptorBatteryPayload(name="SAM-NORTH", x=0.0, y=2.7, launch_range=10.5),
        InterceptorBatteryPayload(name="SAM-SOUTH", x=0.0, y=-2.7, launch_range=10.5),
    ]


class AntiAirConfig(BaseModel):
    enabled: bool = True
    batteries: list[InterceptorBatteryPayload] = Field(
        default_factory=_default_interceptor_batteries,
    )


class DefensiveEvasionConfig(BaseModel):
    enabled: bool = True
    mode: Literal["beam", "corridor"] = "corridor"
    detect_range: float = Field(14.0, gt=0.0)
    trigger_tgo: float = Field(5.0, gt=0.0)
    hold_time: float = Field(2.0, gt=0.0)
    escape_distance: float = Field(6.8, gt=0.0)
    altitude_delta: float = 1.1
    emergency_max_tilt_deg: float = Field(60.0, ge=1.0, le=80.0)
    emergency_max_accel_xy: float = Field(16.0, gt=0.0)
    emergency_max_speed_xy: float = Field(12.0, gt=0.0)


# ---------- Fault injection -------------------------------------------- #

class MotorFaultPayload(BaseModel):
    rotor: int = Field(..., ge=0, le=3)
    t_start: float = Field(..., ge=0.0)
    t_end:   float = Field(..., gt=0.0)
    severity: float = Field(0.0, ge=0.0, le=1.0)


class WindowFaultPayload(BaseModel):
    """Generic time-window fault used by both IMU dropout and GPS denial."""
    t_start: float = Field(..., ge=0.0)
    t_end:   float = Field(..., gt=0.0)


class FaultConfig(BaseModel):
    motor: list[MotorFaultPayload] = []
    imu:   list[WindowFaultPayload] = []
    gps:   list[WindowFaultPayload] = []


class SimRequest(BaseModel):
    waypoints: list[list[float]] = Field(..., min_length=2)
    yaws_deg: list[float]
    zones:    list[ZonePayload] = []
    enemies:  list[EnemyPayload] = []
    friendlies: list[FriendlyDronePayload] = []
    duration_s: float = 40.0
    dt: float = 0.01
    seed: int = 42
    initial_position: list[float] = [0.0, 0.0, 0.0]
    mass: float = 1.2
    accept_radius: float = 0.35
    enable_threats: bool = True
    react_threats: bool = True
    enable_replanning: bool = True
    enable_geofence: bool = True
    gains: ControllerGains = ControllerGains()
    env: EnvParams = EnvParams()
    estimator: EstimatorParams = EstimatorParams()
    anti_air: AntiAirConfig = Field(default_factory=AntiAirConfig)
    defensive_evasion: DefensiveEvasionConfig = Field(default_factory=DefensiveEvasionConfig)
    faults: FaultConfig = FaultConfig()


class SimResponse(BaseModel):
    """Time-series outputs from one closed-loop run."""

    t: list[float]                  # (N,)   sim time in seconds
    pos: list[list[float]]          # (N, 3) true ENU position
    euler: list[list[float]]        # (N, 3) roll/pitch/yaw radians
    vel: list[list[float]]          # (N, 3) inertial velocity
    waypoint_active: list[list[float]]  # (N, 3) commanded waypoint per step
    thrust: list[float]             # (N,)
    meas_pos: list[list[float]]     # (N, 3) raw measured position (or true if noise off)
    state_est: list[list[float]]    # (N, 6) [pos, vel] from EKF (or pass-through)
    enemy_hist: list[list[list[float]]] = Field(default_factory=list)
    # ^ (N, M, 4) [x,y,z,heading] per enemy per step

    # Per-rotor commanded vs delivered thrust (after fault injection)
    motor_cmd:    list[list[float]] = Field(default_factory=list)   # (N, 4)
    motor_actual: list[list[float]] = Field(default_factory=list)   # (N, 4)
    imu_dropout:  list[bool] = Field(default_factory=list)          # (N,)
    gps_denied:   list[bool] = Field(default_factory=list)          # (N,)
    reroute_active: list[bool] = Field(default_factory=list)         # (N,)
    reroute_events: list[dict] = Field(default_factory=list)
    replanned_waypoints: list[list[float]] = Field(default_factory=list)

    # Aggregate metrics for the header strip
    waypoints_total: int
    waypoints_reached: int
    rms_position_error: float
    final_position_error: float
    estimator_used: bool
    raw_pos_rms: float
    ekf_pos_rms: float

    # 15-state INS/GPS EKF telemetry (empty / pass-through when not used)
    estimator_kind: str = "none"
    pos_cov_diag: list[list[float]] = Field(default_factory=list)        # (N, 3) per-axis variance
    est_euler:    list[list[float]] = Field(default_factory=list)        # (N, 3) filter attitude
    accel_bias_est: list[list[float]] = Field(default_factory=list)      # (N, 3)
    gyro_bias_est:  list[list[float]] = Field(default_factory=list)      # (N, 3)
    nees: list[float]                = Field(default_factory=list)       # (N,) navigation NEES
    nis:  list[float | None]         = Field(default_factory=list)       # (N,) sparse — None on no-update steps
    nees_chi2_lo: float = 0.0
    nees_chi2_hi: float = 0.0
    nis_chi2_lo:  float = 0.0
    nis_chi2_hi:  float = 0.0

    # Anti-air interceptor telemetry.
    interceptor_hist: list[list[list[float]]] = Field(default_factory=list)
    # ^ (N, slots, 11) [x,y,z,vx,vy,vz,status,seeker,target_x,target_y,target_z]
    interceptor_events: list[dict] = Field(default_factory=list)
    interceptor_summary: dict = Field(default_factory=dict)
    interceptor_batteries: list[InterceptorBatteryPayload] = Field(default_factory=list)
    interceptor_killed: bool = False
    interceptor_kill_frame: int = -1

    # Defensive autonomy telemetry.
    defensive_hist: list[list[float]] = Field(default_factory=list)
    # ^ (N, 8) [active,x,y,z,missile_range,tgo,missile_x,missile_y]
    defensive_events: list[dict] = Field(default_factory=list)
    defensive_summary: dict = Field(default_factory=dict)
    friendly_tracks: list[dict] = Field(default_factory=list)


# ---------- Monte Carlo request ----------------------------------------- #

class MonteCarloSweepConfig(BaseModel):
    n_runs: int = Field(30, ge=1, le=200)
    seed_base: int = 42
    wind_mean_jitter: float = Field(0.40, ge=0.0, le=2.0)
    wind_extra_gust: float = Field(0.50, ge=0.0, le=2.0)
    mass_jitter: float = Field(0.05, ge=0.0, le=0.5)
    start_xy_jitter: float = Field(0.30, ge=0.0, le=10.0)
    imu_bias_std_deg: float = Field(0.5, ge=0.0, le=10.0)
    success_radius: float = Field(1.0, gt=0.0, le=20.0)
    trajectory_stride: int = Field(35, ge=1, le=500)
    survival_mode: bool = True
    missile_speed_jitter: float = Field(0.12, ge=0.0, le=1.0)
    seeker_noise_jitter: float = Field(0.35, ge=0.0, le=2.0)
    warning_delay_jitter: float = Field(0.20, ge=0.0, le=2.0)


class MonteCarloSweepRequest(BaseModel):
    sim: SimRequest
    config: MonteCarloSweepConfig = MonteCarloSweepConfig()
