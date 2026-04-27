"""
Top-level simulation engine.

Wires the plant (QuadrotorModel), the cascaded controllers
(PositionController -> AttitudeController), the guidance layer
(WaypointManager), and the disturbance models (WindModel, SensorNoise)
together and runs a fixed-step RK4 integration over the configured
horizon. All time histories are stored in a SimulationResult container
for downstream metrics and plotting.
"""

from dataclasses import dataclass, field
import numpy as np

from ..dynamics import QuadrotorModel, QuadrotorParams
from ..control import AttitudeController, PositionController, LQRController
from ..guidance import (
    MinSnapTrajectory, RerouteEvent, ThreatAwareReplanner, WaypointManager,
)
from ..disturbances import WindModel, SensorNoise
from ..threats import ThreatManager, ThreatReport, InterceptorManager
from ..estimation import PositionEKF, InsGpsEKF
from ..utils.quaternion import euler_to_quat, quat_to_rotmat
from .fault_injection import (
    FaultInjector, thrust_torque_to_motors,
    DEFAULT_ARM_LENGTH, DEFAULT_YAW_COEFF,
)


@dataclass
class DefensiveEvasionConfig:
    enabled: bool = True
    mode: str = "corridor"          # corridor | beam
    detect_range: float = 12.0
    trigger_tgo: float = 4.0
    hold_time: float = 2.0
    escape_distance: float = 5.5
    altitude_delta: float = 0.8
    emergency_max_tilt_deg: float = 45.0
    emergency_max_accel_xy: float = 11.0
    emergency_max_speed_xy: float = 9.0


@dataclass
class SimulationResult:
    t: np.ndarray
    state: np.ndarray                 # (N, 12)
    control: np.ndarray               # (N, 4)
    waypoint: np.ndarray              # (N, 3) active waypoint at step k
    euler_cmd: np.ndarray             # (N, 3)
    wind_force: np.ndarray            # (N, 3)
    waypoints: np.ndarray             # (M, 3) full plan
    reached_log: list = field(default_factory=list)
    # Threats (optional; empty arrays if no ThreatManager was supplied)
    enemy_hist: np.ndarray = field(default_factory=lambda: np.zeros((0, 0, 4)))
    threat_report: ThreatReport | None = None
    # Estimator outputs (always populated; equal raw meas when no EKF used)
    meas_pos: np.ndarray = field(default_factory=lambda: np.zeros((0, 3)))
    state_est: np.ndarray = field(default_factory=lambda: np.zeros((0, 6)))
    pos_cov_trace: np.ndarray = field(default_factory=lambda: np.zeros(0))
    estimator_used: bool = False
    # 15-state INS/GPS EKF extras (zeros / NaN when not used)
    estimator_kind: str = "none"
    pos_cov_diag: np.ndarray = field(default_factory=lambda: np.zeros((0, 3)))
    est_euler:    np.ndarray = field(default_factory=lambda: np.zeros((0, 3)))
    accel_bias_est: np.ndarray = field(default_factory=lambda: np.zeros((0, 3)))
    gyro_bias_est:  np.ndarray = field(default_factory=lambda: np.zeros((0, 3)))
    nees: np.ndarray = field(default_factory=lambda: np.zeros(0))
    nis:  np.ndarray = field(default_factory=lambda: np.zeros(0))   # NaN where no GPS fix
    # Per-rotor command + actual delivered thrust (after fault injection).
    motor_cmd:    np.ndarray = field(default_factory=lambda: np.zeros((0, 4)))
    motor_actual: np.ndarray = field(default_factory=lambda: np.zeros((0, 4)))
    # Boolean fault status flags per step
    imu_dropout: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=bool))
    gps_denied:  np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=bool))
    # Threat-aware replanning telemetry.
    reroute_active: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=bool))
    reroute_events: list[RerouteEvent] = field(default_factory=list)
    # Anti-air interceptor (SAM) telemetry.
    interceptor_hist: np.ndarray = field(default_factory=lambda: np.zeros((0, 0, 11)))
    interceptor_events: list[dict] = field(default_factory=list)
    interceptor_summary: dict = field(default_factory=dict)
    interceptor_killed: bool = False
    interceptor_kill_frame: int = -1
    # Defensive autonomy telemetry.
    defensive_hist: np.ndarray = field(default_factory=lambda: np.zeros((0, 8)))
    defensive_events: list[dict] = field(default_factory=list)
    defensive_summary: dict = field(default_factory=dict)


class Simulator:
    def __init__(self,
                 model: QuadrotorModel,
                 position_ctrl: PositionController | LQRController,
                 attitude_ctrl: AttitudeController,
                 waypoint_mgr: WaypointManager,
                 wind: WindModel | None = None,
                 sensor_noise: SensorNoise | None = None,
                 threats: ThreatManager | None = None,
                 replanner: ThreatAwareReplanner | None = None,
                 estimator: PositionEKF | InsGpsEKF | None = None,
                 interceptors: InterceptorManager | None = None,
                 defensive_evasion: DefensiveEvasionConfig | dict | None = None,
                 initial_reroute_events: list[RerouteEvent] | None = None,
                 faults: FaultInjector | None = None,
                 trajectory: MinSnapTrajectory | None = None,
                 dt: float = 0.01,
                 t_final: float = 30.0,
                 initial_state: np.ndarray | None = None):
        self.model = model
        self.pos_ctrl = position_ctrl
        self.att_ctrl = attitude_ctrl
        self.wp_mgr = waypoint_mgr
        self.wind = wind
        self.sensor_noise = sensor_noise
        self.threats = threats
        self.replanner = replanner
        self.estimator = estimator
        self.interceptors = interceptors
        if isinstance(defensive_evasion, DefensiveEvasionConfig):
            self.defensive_evasion = defensive_evasion
        elif isinstance(defensive_evasion, dict):
            self.defensive_evasion = DefensiveEvasionConfig(**defensive_evasion)
        else:
            self.defensive_evasion = DefensiveEvasionConfig(enabled=False)
        self.initial_reroute_events = list(initial_reroute_events or [])
        self.faults = faults if faults is not None else FaultInjector()
        self.trajectory = trajectory
        self.dt = dt
        self.t_final = t_final

        if initial_state is None:
            self.state0 = QuadrotorModel.initial_state()
        else:
            self.state0 = np.asarray(initial_state, dtype=float).copy()

    def _find_missile_threat(self, own_pos: np.ndarray, own_vel: np.ndarray) -> dict | None:
        cfg = self.defensive_evasion
        if not cfg.enabled or self.interceptors is None:
            return None

        best: dict | None = None
        for slot, missile in enumerate(self.interceptors.active):
            if not missile.alive:
                continue
            rel = own_pos - missile.pos
            rng = float(np.linalg.norm(rel))
            if rng > cfg.detect_range:
                continue
            v_rel = own_vel - missile.vel
            closing = -float(np.dot(v_rel, rel)) / max(rng, 1e-6)
            if closing <= 0.05:
                continue
            tgo = rng / max(closing, 0.1)
            if tgo > cfg.trigger_tgo and rng > cfg.detect_range * 0.65:
                continue
            candidate = {
                "slot": slot,
                "missile": missile,
                "range": rng,
                "closing": closing,
                "tgo": tgo,
            }
            if best is None or candidate["tgo"] < best["tgo"]:
                best = candidate
        return best

    def _escape_target(self, own_pos: np.ndarray, threat: dict, base_wp: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        cfg = self.defensive_evasion
        missile = threat["missile"]
        los_xy = own_pos[0:2] - missile.pos[0:2]
        los_norm = float(np.linalg.norm(los_xy))
        if los_norm < 1e-6:
            los_xy = np.array([1.0, 0.0])
            los_norm = 1.0
        los_hat = los_xy / los_norm
        perp = np.array([-los_hat[1], los_hat[0]])

        candidates = [perp, -perp]
        if cfg.mode == "corridor" and self.interceptors is not None and self.interceptors.batteries:
            centers = np.array([[b.x, b.y] for b in self.interceptors.batteries], dtype=float)
            centroid = centers.mean(axis=0)
            scores = []
            for direction in candidates:
                candidate_xy = own_pos[0:2] + direction * cfg.escape_distance
                centroid_score = float(np.linalg.norm(candidate_xy - centroid))
                nearest_battery = float(np.min(np.linalg.norm(centers - candidate_xy[None, :], axis=1)))
                missile_score = float(np.linalg.norm(candidate_xy - missile.pos[0:2]))
                scores.append(centroid_score + 0.7 * nearest_battery + 0.35 * missile_score)
            direction = candidates[int(np.argmax(scores))]
        else:
            vel_xy = own_pos[0:2] * 0.0
            # Pick the side that is least opposite the current commanded route.
            route = base_wp[0:2] - own_pos[0:2]
            if float(np.linalg.norm(route)) > 1e-6:
                route = route / max(float(np.linalg.norm(route)), 1e-6)
                direction = candidates[0] if float(np.dot(candidates[0], route)) >= float(np.dot(candidates[1], route)) else candidates[1]
            else:
                direction = candidates[0]

        target = own_pos.copy()
        target[0:2] = own_pos[0:2] + direction * cfg.escape_distance
        target[2] = max(0.4, own_pos[2] + cfg.altitude_delta, base_wp[2])
        return target, direction

    def _set_position_limits(self, max_tilt_deg: float, max_accel_xy: float, max_speed_xy: float | None) -> None:
        # Always update tilt — both PID and LQR honour it.
        self.pos_ctrl.max_tilt = np.deg2rad(max_tilt_deg)
        # The remaining settings only exist on the PID position controller.
        if hasattr(self.pos_ctrl, "max_accel_xy"):
            self.pos_ctrl.max_accel_xy = max_accel_xy
        if hasattr(self.pos_ctrl, "max_speed_xy"):
            self.pos_ctrl.max_speed_xy = max_speed_xy
        if hasattr(self.pos_ctrl, "x_pid"):
            limits = (-max_accel_xy, max_accel_xy)
            self.pos_ctrl.x_pid.output_limits = limits
            self.pos_ctrl.y_pid.output_limits = limits

    def run(self) -> SimulationResult:
        N = int(round(self.t_final / self.dt)) + 1
        t = np.linspace(0.0, self.t_final, N)

        state_hist    = np.zeros((N, 12))
        control_hist  = np.zeros((N, 4))
        waypoint_hist = np.zeros((N, 3))
        euler_cmd_hist = np.zeros((N, 3))
        wind_hist     = np.zeros((N, 3))

        M = len(self.threats) if self.threats is not None else 0
        enemy_hist     = np.zeros((N, M, 4))
        enemy_range    = np.zeros((N, M))
        in_detection   = np.zeros((N, M), dtype=bool)
        in_lethal      = np.zeros((N, M), dtype=bool)

        meas_pos_hist  = np.zeros((N, 3))
        state_est_hist = np.zeros((N, 6))
        pos_cov_hist   = np.zeros(N)
        pos_cov_diag_hist = np.zeros((N, 3))
        est_euler_hist    = np.zeros((N, 3))
        accel_bias_hist   = np.zeros((N, 3))
        gyro_bias_hist    = np.zeros((N, 3))
        nees_hist         = np.zeros(N)
        nis_hist          = np.full(N, np.nan)

        motor_cmd_hist    = np.zeros((N, 4))
        motor_actual_hist = np.zeros((N, 4))
        imu_dropout_hist  = np.zeros(N, dtype=bool)
        gps_denied_hist   = np.zeros(N, dtype=bool)
        reroute_active_hist = np.zeros(N, dtype=bool)
        reroute_events: list[RerouteEvent] = list(self.initial_reroute_events)

        # Interceptor logging buffers (slot_capacity is fixed across steps).
        slot_cap = self.interceptors.slot_capacity if self.interceptors else 0
        interceptor_hist = np.zeros((N, slot_cap, 11))
        interceptor_events: list[dict] = []
        interceptor_killed = False
        interceptor_kill_frame = -1
        defensive_hist = np.zeros((N, 8))
        defensive_events: list[dict] = []
        defense_active_until = -1e9
        defense_was_active = False
        defense_target = np.zeros(3)

        # Last-known sensor reading (frozen during IMU/GPS dropouts).
        last_attitude = np.zeros(3)
        last_rates    = np.zeros(3)
        last_pos_meas = self.state0[0:3].copy()

        state = self.state0.copy()

        self.pos_ctrl.reset()
        self.att_ctrl.reset()
        nominal_accel = getattr(self.pos_ctrl, "max_accel_xy", 6.0)
        nominal_speed = getattr(self.pos_ctrl, "max_speed_xy", None)
        nominal_limits = {
            "tilt_deg": float(np.rad2deg(self.pos_ctrl.max_tilt)),
            "accel_xy": float(nominal_accel),
            "speed_xy": None if nominal_speed is None else float(nominal_speed),
        }
        if isinstance(self.estimator, PositionEKF):
            # Seed the constant-velocity filter from truth so it starts
            # converged rather than spending a few seconds catching up.
            self.estimator.x[0:3] = state[0:3]
            self.estimator.x[3:6] = state[3:6]
        elif isinstance(self.estimator, InsGpsEKF):
            self.estimator.seed_from_truth(state[0:3], state[3:6], state[6:9])

        # GPS update cadence — only the INS/GPS filter cares; the legacy
        # constant-velocity filter still updates every step to match its
        # original behaviour.
        gps_rate_hz = (self.sensor_noise.gps_rate_hz
                       if self.sensor_noise is not None else 1.0 / self.dt)
        gps_stride = max(1, int(round(1.0 / (self.dt * gps_rate_hz))))

        # Carry the previously applied control + wind so the IMU at step k
        # sees the proper acceleration produced over [t_{k-1}, t_k].
        u_prev = np.array([self.model.p.mass * self.model.p.g, 0.0, 0.0, 0.0])
        wind_prev = np.zeros(3)
        g_n = np.array([0.0, 0.0, -self.model.p.g])
        # Last-known IMU sample (used during IMU dropouts). Lazy-initialised
        # at the first non-dropped step to avoid feeding zero specific force
        # while at hover (which would imply free-fall).
        self._last_imu = (np.array([0.0, 0.0, self.model.p.g]), np.zeros(3))

        for k in range(N):
            tk = t[k]

            # --- Guidance --------------------------------------------------
            wp = self.wp_mgr.update(state[0:3], tk)
            yaw_cmd = self.wp_mgr.current_yaw

            # --- Threats: step + evasion offset ----------------------------
            if self.threats is not None and M > 0:
                self.threats.step(self.dt, state[0:3])
                enemy_hist[k] = self.threats.snapshot()
                rng = self.threats.ranges_to(state[0:3])
                enemy_range[k] = rng
                for j, e in enumerate(self.threats.enemies):
                    if rng[j] < e.detection_radius:
                        in_detection[k, j] = True
                    if rng[j] < e.lethal_radius:
                        in_lethal[k, j] = True
                if self.replanner is not None:
                    decision = self.replanner.maybe_replan(
                        t=tk,
                        frame=k,
                        position=state[0:3],
                        target=wp,
                        waypoint_index=self.wp_mgr.index,
                        moving_threats=self.threats.enemies,
                    )
                    if decision is not None:
                        self.wp_mgr.insert_current_waypoints(
                            decision.waypoints,
                            yaw=yaw_cmd,
                        )
                        reroute_events.append(decision.event)
                        wp = self.wp_mgr.current_waypoint
                evade = self.threats.evasion_offset(state[0:3])
                wp_eff = wp + evade
            else:
                if self.replanner is not None:
                    decision = self.replanner.maybe_replan(
                        t=tk,
                        frame=k,
                        position=state[0:3],
                        target=wp,
                        waypoint_index=self.wp_mgr.index,
                        moving_threats=[],
                    )
                    if decision is not None:
                        self.wp_mgr.insert_current_waypoints(
                            decision.waypoints,
                            yaw=yaw_cmd,
                        )
                        reroute_events.append(decision.event)
                        wp = self.wp_mgr.current_waypoint
                wp_eff = wp
            reroute_active_hist[k] = self.wp_mgr.current_is_dynamic

            # --- Anti-air interceptors (SAM batteries) -------------------
            if self.interceptors is not None:
                step_events = self.interceptors.step(
                    self.dt, tk, state[0:3], state[3:6],
                )
                for ev in step_events:
                    ev_with_frame = {**ev, "frame": k}
                    interceptor_events.append(ev_with_frame)
                    if ev["type"] == "hit" and not interceptor_killed:
                        interceptor_killed = True
                        interceptor_kill_frame = k
                interceptor_hist[k] = self.interceptors.snapshot()

            # --- Defensive autonomy: missile warning + beaming escape ----
            defense_active = False
            defense_threat = self._find_missile_threat(state[0:3], state[3:6])
            if defense_threat is not None:
                defense_target, defense_dir = self._escape_target(
                    state[0:3],
                    defense_threat,
                    wp_eff,
                )
                defense_active_until = tk + self.defensive_evasion.hold_time
                defense_active = True
                if not defense_was_active:
                    defensive_events.append({
                        "type": "missile_evasion",
                        "t": float(tk),
                        "frame": k,
                        "mode": self.defensive_evasion.mode,
                        "message": "MISSILE WARNING - BEAM MANEUVER",
                        "threat_slot": int(defense_threat["slot"]),
                        "missile_range": float(defense_threat["range"]),
                        "closing_speed": float(defense_threat["closing"]),
                        "time_to_go": float(defense_threat["tgo"]),
                        "escape_target": defense_target.tolist(),
                        "missile_position": defense_threat["missile"].pos.tolist(),
                    })
            elif tk <= defense_active_until:
                defense_active = True

            if defense_active:
                wp_eff = defense_target.copy()
                yaw_cmd = float(np.arctan2(wp_eff[1] - state[1], wp_eff[0] - state[0]))
                defensive_hist[k] = np.array([
                    1.0,
                    wp_eff[0],
                    wp_eff[1],
                    wp_eff[2],
                    float(defense_threat["range"]) if defense_threat is not None else np.nan,
                    float(defense_threat["tgo"]) if defense_threat is not None else np.nan,
                    float(defense_threat["missile"].pos[0]) if defense_threat is not None else np.nan,
                    float(defense_threat["missile"].pos[1]) if defense_threat is not None else np.nan,
                ])
            defense_was_active = defense_active

            # --- Sensing ---------------------------------------------------
            meas = (self.sensor_noise.corrupt(state)
                    if self.sensor_noise is not None else state.copy())

            # IMU dropout — freeze attitude/rate readings to last good value.
            imu_down = self.faults.imu_dropped(tk)
            imu_dropout_hist[k] = imu_down
            if imu_down:
                meas[6:9]  = last_attitude
                meas[9:12] = last_rates
            else:
                last_attitude = meas[6:9].copy()
                last_rates    = meas[9:12].copy()

            # GPS denied — freeze position measurement; estimator skips update.
            gps_down = self.faults.gps_denied(tk)
            gps_denied_hist[k] = gps_down
            if gps_down:
                meas[0:3] = last_pos_meas
            else:
                last_pos_meas = meas[0:3].copy()
            meas_pos_hist[k] = meas[0:3]

            # --- State estimation (EKF) ------------------------------------
            if isinstance(self.estimator, InsGpsEKF):
                # Truth specific force in body frame: f_b = R^T (a_n - g_n).
                # We use the previously applied control + wind so the IMU
                # at t_k reflects the acceleration produced over the just-
                # completed step (consistent with ZOH inputs).
                R_true = quat_to_rotmat(euler_to_quat(*state[6:9]))
                v_dot_n = self.model.dynamics(state, u_prev, wind_prev)[3:6]
                f_body_true = R_true.T @ (v_dot_n - g_n)
                w_body_true = state[9:12]

                if self.sensor_noise is not None:
                    a_meas, w_meas = self.sensor_noise.imu(f_body_true, w_body_true)
                else:
                    a_meas, w_meas = f_body_true, w_body_true

                # IMU dropout: hold the last-good IMU sample.
                if imu_down:
                    a_meas, w_meas = self._last_imu
                else:
                    self._last_imu = (a_meas.copy(), w_meas.copy())

                self.estimator.predict(a_meas, w_meas, self.dt)

                gps_due = (k % gps_stride == 0)
                nis_hist[k] = np.nan
                if gps_due and not gps_down:
                    self.estimator.update_position(meas[0:3])
                    nis_hist[k] = self.estimator.last_nis

                pos_for_ctrl = self.estimator.pos
                vel_for_ctrl = self.estimator.vel
                state_est_hist[k, 0:3] = self.estimator.pos
                state_est_hist[k, 3:6] = self.estimator.vel
                pos_cov_hist[k]        = self.estimator.pos_cov_trace
                pos_cov_diag_hist[k]   = np.diag(self.estimator.pos_cov)
                est_euler_hist[k]      = self.estimator.euler
                accel_bias_hist[k]     = self.estimator.accel_bias
                gyro_bias_hist[k]      = self.estimator.gyro_bias
                # 9-dim navigation NEES against truth.
                q_true = euler_to_quat(*state[6:9])
                nees_hist[k] = self.estimator.nees_nav(
                    state[0:3], state[3:6], q_true,
                )
            elif isinstance(self.estimator, PositionEKF):
                self.estimator.predict(self.dt)
                if not gps_down:
                    self.estimator.update_position(meas[0:3])
                pos_for_ctrl = self.estimator.pos
                vel_for_ctrl = self.estimator.vel
                state_est_hist[k, 0:3] = self.estimator.pos
                state_est_hist[k, 3:6] = self.estimator.vel
                pos_cov_hist[k]        = self.estimator.pos_cov_trace
                pos_cov_diag_hist[k]   = np.diag(self.estimator.P[0:3, 0:3])
                est_euler_hist[k]      = meas[6:9]
            else:
                pos_for_ctrl = meas[0:3]
                vel_for_ctrl = meas[3:6]
                state_est_hist[k, 0:3] = meas[0:3]
                state_est_hist[k, 3:6] = meas[3:6]
                pos_cov_hist[k] = 0.0
                est_euler_hist[k] = meas[6:9]

            # --- Outer loop (position -> attitude cmd + thrust) -----------
            if defense_active:
                self._set_position_limits(
                    self.defensive_evasion.emergency_max_tilt_deg,
                    self.defensive_evasion.emergency_max_accel_xy,
                    self.defensive_evasion.emergency_max_speed_xy,
                )
            else:
                self._set_position_limits(
                    nominal_limits["tilt_deg"],
                    nominal_limits["accel_xy"],
                    nominal_limits["speed_xy"],
                )
            # Optional reference-trajectory feedforward: when a MinSnap (or
            # similar) trajectory is supplied the position setpoint is the
            # smooth polynomial value at t_k, and — for LQR — we also pass
            # the trajectory velocity as a feedforward so the regulator
            # tracks the moving reference instead of lagging it. The
            # waypoint manager still sequences for telemetry (reroute
            # logging, defensive evasion).
            traj_vel: np.ndarray | None = None
            traj_acc: np.ndarray | None = None
            if self.trajectory is not None and not defense_active:
                p_ref, v_ref, a_ref = self.trajectory(tk, max_deriv=2)
                wp_eff = p_ref
                traj_vel = v_ref
                traj_acc = a_ref

            update_kwargs = dict(
                pos_cmd=wp_eff,
                pos_meas=pos_for_ctrl,
                yaw_meas=meas[8],
                yaw_cmd=yaw_cmd,
                dt=self.dt,
                vel_meas=vel_for_ctrl,
            )
            if isinstance(self.pos_ctrl, LQRController) and traj_vel is not None:
                update_kwargs["vel_cmd"] = traj_vel
                update_kwargs["accel_cmd"] = traj_acc
            euler_cmd, thrust = self.pos_ctrl.update(**update_kwargs)

            # --- Inner loop (attitude -> torques) --------------------------
            tau = self.att_ctrl.update(
                euler_cmd=euler_cmd,
                euler_meas=meas[6:9],
                dt=self.dt,
            )

            u = np.concatenate(([thrust], tau))

            # --- Motor failure injection ----------------------------------
            u_actual, motors_cmd, motors_actual = self.faults.apply_motor_failure(
                u, tk,
            )
            motor_cmd_hist[k]    = motors_cmd
            motor_actual_hist[k] = motors_actual

            # --- Disturbance ----------------------------------------------
            wind_force = (self.wind.step(self.dt, state[3:6])
                          if self.wind is not None else np.zeros(3))

            # --- Log -------------------------------------------------------
            state_hist[k]    = state
            control_hist[k]  = u_actual
            waypoint_hist[k] = wp
            euler_cmd_hist[k] = euler_cmd
            wind_hist[k]     = wind_force

            # --- Propagate -------------------------------------------------
            if k < N - 1:
                state = self.model.rk4_step(state, u_actual, self.dt, wind_force)
            u_prev = u_actual
            wind_prev = wind_force

        threat_report: ThreatReport | None = None
        if self.threats is not None and M > 0:
            min_range = enemy_range.min(axis=1) if M > 0 else np.zeros(N)
            # first-lethal-contact per enemy
            intercepts: list[tuple[int, float]] = []
            for j in range(M):
                lethal_col = in_lethal[:, j]
                if lethal_col.any():
                    k_first = int(np.argmax(lethal_col))
                    intercepts.append((j, float(t[k_first])))
            threat_report = ThreatReport(
                enemy_names=[e.name for e in self.threats.enemies],
                min_range_history=min_range,
                per_step_min_range=enemy_range,
                in_detection=in_detection,
                in_lethal=in_lethal,
                intercept_events=intercepts,
            )

        return SimulationResult(
            t=t,
            state=state_hist,
            control=control_hist,
            waypoint=waypoint_hist,
            euler_cmd=euler_cmd_hist,
            wind_force=wind_hist,
            waypoints=self.wp_mgr.waypoints.copy(),
            reached_log=list(self.wp_mgr.reached_log),
            enemy_hist=enemy_hist,
            threat_report=threat_report,
            meas_pos=meas_pos_hist,
            state_est=state_est_hist,
            pos_cov_trace=pos_cov_hist,
            estimator_used=self.estimator is not None,
            estimator_kind=(
                "ins_gps" if isinstance(self.estimator, InsGpsEKF)
                else "position" if isinstance(self.estimator, PositionEKF)
                else "none"
            ),
            pos_cov_diag=pos_cov_diag_hist,
            est_euler=est_euler_hist,
            accel_bias_est=accel_bias_hist,
            gyro_bias_est=gyro_bias_hist,
            nees=nees_hist,
            nis=nis_hist,
            motor_cmd=motor_cmd_hist,
            motor_actual=motor_actual_hist,
            imu_dropout=imu_dropout_hist,
            gps_denied=gps_denied_hist,
            reroute_active=reroute_active_hist,
            reroute_events=reroute_events,
            interceptor_hist=interceptor_hist,
            interceptor_events=interceptor_events,
            interceptor_summary=(self.interceptors.summary()
                                  if self.interceptors is not None else {}),
            interceptor_killed=interceptor_killed,
            interceptor_kill_frame=interceptor_kill_frame,
            defensive_hist=defensive_hist,
            defensive_events=defensive_events,
            defensive_summary={
                "n_evasions": len(defensive_events),
                "time_evasive": float(defensive_hist[:, 0].sum() * self.dt),
                "escaped": bool(
                    self.interceptors is not None
                    and len(self.interceptors.launch_events) > 0
                    and not interceptor_killed
                ),
                "mode": self.defensive_evasion.mode,
            },
        )
