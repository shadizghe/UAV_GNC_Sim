"""
Thin adapter that turns a SimRequest pydantic payload into a fully
configured `Simulator`, runs it, and packs the result back into a
SimResponse JSON-friendly dict.

All the heavy lifting lives in `src/` — this module only marshals types.
"""

from __future__ import annotations

from dataclasses import dataclass
import numpy as np

from src.dynamics import QuadrotorModel, QuadrotorParams
from src.control import AttitudeController, PositionController
from src.guidance import (
    RerouteEvent,
    StaticThreatZone,
    ThreatAwareReplanner,
    ThreatGridPlanner,
    WaypointManager,
)
from src.disturbances import WindModel, SensorNoise
from src.simulation import (
    Simulator, FaultInjector, MotorFault, IMUFault, GPSFault,
)
from src.threats import EnemyDrone, ThreatManager, InterceptorBattery, InterceptorManager
from src.estimation import PositionEKF, InsGpsEKF, InsGpsEKFConfig
from src.utils import compute_performance_metrics

from .schemas import SimRequest, SimResponse


@dataclass(frozen=True)
class _PreRouteCircle:
    name: str
    x: float
    y: float
    radius: float
    kind: str = "threat"


def _fault_injector_from_request(req: SimRequest) -> FaultInjector:
    fc = req.faults
    return FaultInjector.from_iterables(
        motors=[MotorFault(rotor=m.rotor, t_start=m.t_start, t_end=m.t_end,
                           severity=m.severity) for m in fc.motor],
        imus=[IMUFault(t_start=f.t_start, t_end=f.t_end) for f in fc.imu],
        gps=[GPSFault(t_start=f.t_start,  t_end=f.t_end) for f in fc.gps],
    )


def _interceptor_manager_from_request(req: SimRequest) -> InterceptorManager | None:
    cfg = req.anti_air
    if not cfg.enabled or not cfg.batteries:
        return None
    batteries = [
        InterceptorBattery(
            name=b.name,
            x=b.x,
            y=b.y,
            z=b.z,
            launch_range=b.launch_range,
            min_engage_alt=b.min_engage_alt,
            cooldown=b.cooldown,
            max_active=b.max_active,
            max_total_shots=b.max_total_shots,
            initial_speed=b.initial_speed,
            nav_constant=b.nav_constant,
            max_lateral_accel=b.max_lateral_accel,
            boost_time=b.boost_time,
            boost_accel=b.boost_accel,
            coast_drag=b.coast_drag,
            lethal_radius=b.lethal_radius,
            arming_time=b.arming_time,
            max_time=b.max_time,
            seeker_enabled=b.seeker_enabled,
            seeker_range=b.seeker_range,
            seeker_fov_deg=b.seeker_fov_deg,
            seeker_noise_std_deg=b.seeker_noise_std_deg,
            seeker_memory_time=b.seeker_memory_time,
        )
        for b in cfg.batteries
    ]
    return InterceptorManager(batteries, rng=np.random.default_rng(req.seed + 2))


def _jsonable_interceptor_event(event: dict) -> dict:
    out: dict = {}
    for key, value in event.items():
        if isinstance(value, np.generic):
            out[key] = value.item()
        elif isinstance(value, np.ndarray):
            out[key] = value.astype(float).tolist()
        elif isinstance(value, list):
            out[key] = [
                item.item() if isinstance(item, np.generic) else item
                for item in value
            ]
        else:
            out[key] = value
    return out


def _segment_circle_distance(
    a: np.ndarray,
    b: np.ndarray,
    center: np.ndarray,
) -> tuple[float, float]:
    ab = b - a
    denom = float(np.dot(ab, ab))
    if denom < 1e-9:
        return float(np.linalg.norm(a - center)), 0.0
    u = float(np.clip(np.dot(center - a, ab) / denom, 0.0, 1.0))
    closest = a + u * ab
    return float(np.linalg.norm(closest - center)), u


def _sam_preroute_plan(
    req: SimRequest,
) -> tuple[np.ndarray, np.ndarray, list[bool], list[RerouteEvent]]:
    waypoints = np.asarray(req.waypoints, dtype=float)
    yaws = np.deg2rad(np.asarray(req.yaws_deg, dtype=float))
    if yaws.size < len(waypoints):
        yaws = np.pad(yaws, (0, len(waypoints) - yaws.size), constant_values=0.0)
    elif yaws.size > len(waypoints):
        yaws = yaws[:len(waypoints)]

    if (
        not req.enable_replanning
        or not req.anti_air.enabled
        or not req.anti_air.batteries
        or len(waypoints) < 2
    ):
        return waypoints, yaws, [False for _ in range(len(waypoints))], []

    circles = [
        _PreRouteCircle(
            name=b.name,
            x=float(b.x),
            y=float(b.y),
            radius=float(b.launch_range) + 0.55,
            kind="threat",
        )
        for b in req.anti_air.batteries
    ]
    planner = ThreatGridPlanner(
        cell_size=0.45,
        boundary_padding=4.0,
        threat_buffer=1.8,
        max_inserted_waypoints=6,
    )

    planned: list[np.ndarray] = []
    planned_yaws: list[float] = []
    dynamic_flags: list[bool] = []
    events: list[RerouteEvent] = []
    current = np.asarray(req.initial_position, dtype=float)

    for wp_index, target in enumerate(waypoints):
        target = np.asarray(target, dtype=float)
        start_xy = current[:2]
        target_xy = target[:2]
        contested: list[tuple[_PreRouteCircle, float, float]] = []
        for circle in circles:
            center = np.array([circle.x, circle.y], dtype=float)
            distance, along = _segment_circle_distance(start_xy, target_xy, center)
            endpoint_inside = (
                float(np.linalg.norm(target_xy - center)) < circle.radius
                and float(np.linalg.norm(start_xy - center)) >= circle.radius
            )
            if (0.02 < along < 0.98 and distance <= circle.radius) or endpoint_inside:
                contested.append((circle, distance, along))

        yaw = float(yaws[min(wp_index, len(yaws) - 1)]) if len(yaws) else 0.0
        if contested:
            path = planner.plan(start_xy=start_xy, target_xy=target_xy, threats=circles)
            if path is not None and path.waypoints:
                altitude = max(float(current[2]), float(target[2]))
                inserted = [
                    np.array([float(point[0]), float(point[1]), altitude], dtype=float)
                    for point in path.waypoints
                ]
                planned.extend(inserted)
                planned_yaws.extend([yaw for _ in inserted])
                dynamic_flags.extend([True for _ in inserted])
                circle, distance, _along = min(contested, key=lambda item: item[1])
                events.append(RerouteEvent(
                    t=0.0,
                    frame=0,
                    threat_name=circle.name,
                    threat_kind="sam",
                    waypoint_index=int(wp_index),
                    original_target=[float(v) for v in target],
                    inserted_waypoint=[float(v) for v in inserted[0]],
                    inserted_waypoints=[
                        [float(v) for v in waypoint]
                        for waypoint in inserted
                    ],
                    envelope_radius=float(circle.radius),
                    clearance_score=float(path.clearance),
                    planner_cost=float(path.cost),
                    nodes_expanded=int(path.nodes_expanded),
                    cost_grid=path.cost_grid,
                    message="PREFLIGHT SAM AVOIDANCE",
                ))

        planned.append(target)
        planned_yaws.append(yaw)
        dynamic_flags.append(False)
        current = target

    return (
        np.asarray(planned, dtype=float),
        np.asarray(planned_yaws, dtype=float),
        dynamic_flags,
        events,
    )


def build_simulator(
    req: SimRequest,
    *,
    seed: int | None = None,
    mass: float | None = None,
    initial_position: tuple[float, float, float] | list[float] | None = None,
    mean_wind: tuple[float, float, float] | None = None,
    gust_std: tuple[float, float, float] | None = None,
    attitude_bias_deg: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> Simulator:
    run_seed = req.seed if seed is None else seed
    run_mass = req.mass if mass is None else mass
    start_position = req.initial_position if initial_position is None else initial_position


    qp = QuadrotorParams(mass=run_mass)
    model = QuadrotorModel(qp)

    g = req.gains
    pos_ctrl = PositionController(
        mass=qp.mass, g=qp.g,
        xy_gains=(g.kp_xy, g.ki_xy, g.kd_xy),
        z_gains=(g.kp_z, g.ki_z, g.kd_z),
        max_tilt_deg=g.max_tilt_deg,
        max_accel_xy=g.max_accel_xy,
        max_speed_xy=g.max_speed_xy,
        thrust_limits=(qp.thrust_min, qp.thrust_max),
    )
    att_ctrl = AttitudeController(
        roll_gains=(g.kp_att, 0.1, g.kd_att),
        pitch_gains=(g.kp_att, 0.1, g.kd_att),
        yaw_gains=(g.kp_yaw, 0.05, g.kd_yaw),
        tau_limit=qp.tau_max,
    )

    waypoints_arr, yaws_rad, dynamic_flags, initial_reroute_events = _sam_preroute_plan(req)
    wp_mgr = WaypointManager(waypoints_arr,
                             acceptance_radius=req.accept_radius,
                             yaw_setpoints=yaws_rad)
    if len(dynamic_flags) == len(wp_mgr.dynamic_waypoint_flags):
        wp_mgr.dynamic_waypoint_flags = dynamic_flags

    e = req.env
    base_mean_wind = mean_wind if mean_wind is not None else (e.wind_x, e.wind_y, e.wind_z)
    base_gust_std = gust_std if gust_std is not None else (e.gust_std, e.gust_std, e.gust_std * 0.33)
    wind = WindModel(
        mean_wind=base_mean_wind,
        gust_std=base_gust_std,
        rng=np.random.default_rng(run_seed),
    ) if e.enable_wind else None

    noise = SensorNoise(
        position_std=e.pos_std,
        attitude_std_deg=e.att_std_deg,
        attitude_bias_deg=attitude_bias_deg,
        rng=np.random.default_rng(run_seed + 1),
    ) if e.enable_noise else None

    enemies = [
        EnemyDrone(
            name=en.name, x=en.x, y=en.y, z=en.z,
            speed=en.speed,
            detection_radius=en.det_r, lethal_radius=en.leth_r,
            behavior=en.behavior,
            orbit_cx=en.orbit_cx, orbit_cy=en.orbit_cy, orbit_r=en.orbit_r,
        )
        for en in req.enemies
    ] if req.enable_threats else []
    threats = ThreatManager(enemies, react=req.react_threats) if enemies else None
    static_threat_zones = [
        StaticThreatZone(name=z.name, cx=z.cx, cy=z.cy, r=z.r, kind=z.kind)
        for z in req.zones
        if req.enable_geofence and z.kind in ("no_fly", "threat")
    ]
    replanner = (
        ThreatAwareReplanner(static_zones=static_threat_zones)
        if req.enable_replanning and (enemies or static_threat_zones)
        else None
    )

    if req.estimator.enable_ekf:
        if req.estimator.kind == "ins_gps":
            estimator = InsGpsEKF(InsGpsEKFConfig(
                sigma_a=req.estimator.sigma_a,
                sigma_g_deg=req.estimator.sigma_g_deg,
                sigma_ba=req.estimator.sigma_ba,
                sigma_bg_deg=req.estimator.sigma_bg_deg,
                sigma_gps=max(e.pos_std, req.estimator.sigma_gps),
            ))
            if noise is not None:
                noise.gps_rate_hz = req.estimator.gps_rate_hz
        else:
            estimator = PositionEKF(
                sigma_pos=max(e.pos_std, 1e-3),
                sigma_jerk=req.estimator.sigma_jerk,
            )
    else:
        estimator = None

    state0 = QuadrotorModel.initial_state(position=tuple(start_position))

    faults = _fault_injector_from_request(req)
    interceptors = _interceptor_manager_from_request(req)

    return Simulator(
        model, pos_ctrl, att_ctrl, wp_mgr,
        wind=wind, sensor_noise=noise, threats=threats, replanner=replanner,
        estimator=estimator,
        interceptors=interceptors,
        defensive_evasion=req.defensive_evasion.model_dump(),
        initial_reroute_events=initial_reroute_events,
        faults=faults,
        dt=req.dt, t_final=req.duration_s, initial_state=state0,
    )


def _friendly_tracks_from_request(req: SimRequest) -> list[dict]:
    tracks: list[dict] = []
    if not req.friendlies:
        return tracks

    base_start = np.asarray(req.initial_position, dtype=float)
    base_waypoints = np.asarray(req.waypoints, dtype=float)
    base_yaws = list(req.yaws_deg)
    fallback_len = len(base_waypoints)

    for index, friendly in enumerate(req.friendlies):
        if not friendly.enabled:
            continue

        start = np.asarray([friendly.x, friendly.y, friendly.z], dtype=float)
        if friendly.route_mode == "formation":
            waypoints = (base_waypoints + (start - base_start)).tolist()
        else:
            waypoints = base_waypoints.tolist()

        friend_req = req.model_copy(
            deep=True,
            update={
                "initial_position": start.tolist(),
                "waypoints": waypoints,
                "yaws_deg": base_yaws[:fallback_len],
                "friendlies": [],
                "seed": req.seed + 101 + index,
            },
        )
        result = build_simulator(
            friend_req,
            seed=req.seed + 101 + index,
            initial_position=start.tolist(),
        ).run()
        metrics = compute_performance_metrics(result)
        tracks.append({
            "name": friendly.name,
            "initial_position": start.tolist(),
            "route_mode": friendly.route_mode,
            "pos": result.state[:, 0:3].tolist(),
            "vel": result.state[:, 3:6].tolist(),
            "euler": result.state[:, 6:9].tolist(),
            "waypoints_reached": int(metrics.waypoints_reached),
            "interceptor_killed": bool(result.interceptor_killed),
            "interceptor_summary": result.interceptor_summary,
        })

    return tracks


def run_simulation(req: SimRequest) -> SimResponse:
    sim = build_simulator(req)
    result = sim.run()
    metrics = compute_performance_metrics(result)

    pos = result.state[:, 0:3]
    raw_resid = result.meas_pos - pos
    est_resid = result.state_est[:, 0:3] - pos
    raw_rms = float(np.sqrt(np.mean(raw_resid ** 2))) if raw_resid.size else 0.0
    est_rms = float(np.sqrt(np.mean(est_resid ** 2))) if est_resid.size else 0.0

    # Chi-squared 95% intervals — drawn as bands on the consistency plots.
    # NEES uses 9 DoF (pos+vel+attitude), NIS uses 3 (GPS position).
    from scipy import stats as _stats
    nees_lo, nees_hi = _stats.chi2.interval(0.95, df=9)
    nis_lo,  nis_hi  = _stats.chi2.interval(0.95, df=3)
    # JSON can't carry NaN — replace with None for the sparse NIS series.
    nis_clean = [None if not np.isfinite(v) else float(v) for v in result.nis.tolist()]

    return SimResponse(
        t=result.t.tolist(),
        pos=pos.tolist(),
        euler=result.state[:, 6:9].tolist(),
        vel=result.state[:, 3:6].tolist(),
        waypoint_active=result.waypoint.tolist(),
        thrust=result.control[:, 0].tolist(),
        meas_pos=result.meas_pos.tolist(),
        state_est=result.state_est.tolist(),
        enemy_hist=result.enemy_hist.tolist() if result.enemy_hist.size else [],
        motor_cmd=result.motor_cmd.tolist() if result.motor_cmd.size else [],
        motor_actual=result.motor_actual.tolist() if result.motor_actual.size else [],
        imu_dropout=result.imu_dropout.tolist() if result.imu_dropout.size else [],
        gps_denied=result.gps_denied.tolist() if result.gps_denied.size else [],
        reroute_active=result.reroute_active.tolist() if result.reroute_active.size else [],
        reroute_events=[
            {
                "t": event.t,
                "frame": event.frame,
                "threat_name": event.threat_name,
                "threat_kind": event.threat_kind,
                "waypoint_index": event.waypoint_index,
                "original_target": event.original_target,
                "inserted_waypoint": event.inserted_waypoint,
                "inserted_waypoints": event.inserted_waypoints,
                "envelope_radius": event.envelope_radius,
                "clearance_score": event.clearance_score,
                "planner_cost": event.planner_cost,
                "nodes_expanded": event.nodes_expanded,
                "cost_grid": event.cost_grid,
                "message": event.message,
            }
            for event in result.reroute_events
        ],
        replanned_waypoints=result.waypoints.tolist(),
        waypoints_total=metrics.waypoints_total,
        waypoints_reached=metrics.waypoints_reached,
        rms_position_error=float(metrics.rms_position_error),
        final_position_error=float(metrics.final_position_error),
        estimator_used=result.estimator_used,
        raw_pos_rms=raw_rms,
        ekf_pos_rms=est_rms,
        estimator_kind=result.estimator_kind,
        pos_cov_diag=result.pos_cov_diag.tolist(),
        est_euler=result.est_euler.tolist(),
        accel_bias_est=result.accel_bias_est.tolist(),
        gyro_bias_est=result.gyro_bias_est.tolist(),
        nees=result.nees.tolist(),
        nis=nis_clean,
        nees_chi2_lo=float(nees_lo),
        nees_chi2_hi=float(nees_hi),
        nis_chi2_lo=float(nis_lo),
        nis_chi2_hi=float(nis_hi),
        interceptor_hist=(
            result.interceptor_hist.tolist()
            if result.interceptor_hist.size else []
        ),
        interceptor_events=[
            _jsonable_interceptor_event(event)
            for event in result.interceptor_events
        ],
        interceptor_summary=result.interceptor_summary,
        interceptor_batteries=(
            req.anti_air.batteries if req.anti_air.enabled else []
        ),
        interceptor_killed=result.interceptor_killed,
        interceptor_kill_frame=result.interceptor_kill_frame,
        defensive_hist=(
            result.defensive_hist.tolist()
            if result.defensive_hist.size else []
        ),
        defensive_events=[
            _jsonable_interceptor_event(event)
            for event in result.defensive_events
        ],
        defensive_summary=result.defensive_summary,
        friendly_tracks=_friendly_tracks_from_request(req),
    )
