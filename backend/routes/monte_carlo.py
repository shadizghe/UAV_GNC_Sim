"""WebSocket-streamed Monte Carlo dispersion sweep."""

from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import numpy as np

from src.analysis import circular_error_probable

from ..schemas import MonteCarloSweepRequest
from ..sim_runner import build_simulator

router = APIRouter(prefix="/api/monte-carlo", tags=["monte-carlo"])


def _sample_trajectory(pos: np.ndarray, stride: int) -> list[list[float]]:
    sampled = pos[::stride]
    if len(pos) > 0 and not np.array_equal(sampled[-1], pos[-1]):
        sampled = np.vstack([sampled, pos[-1]])
    return sampled.tolist()


def _mean(values: np.ndarray) -> float:
    return float(np.mean(values)) if values.size else 0.0


def _std(values: np.ndarray) -> float:
    return float(np.std(values)) if values.size else 0.0


@router.websocket("/ws")
async def monte_carlo_ws(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        payload = await websocket.receive_json()
        req = MonteCarloSweepRequest.model_validate(payload)
        sim_req = req.sim
        cfg = req.config
        total = cfg.n_runs

        await websocket.send_json({
            "type": "started",
            "total": total,
            "config": cfg.model_dump(),
        })

        rng = np.random.default_rng(cfg.seed_base)
        base_mean_wind = np.asarray(
            (sim_req.env.wind_x, sim_req.env.wind_y, sim_req.env.wind_z),
            dtype=float,
        )
        base_gust_std = np.asarray(
            (sim_req.env.gust_std, sim_req.env.gust_std, sim_req.env.gust_std * 0.33),
            dtype=float,
        )
        base_start = np.asarray(sim_req.initial_position, dtype=float)

        trajectories: list[np.ndarray] = []
        endpoints = np.zeros((total, 3))
        final_errors = np.zeros(total)
        rms_errors = np.zeros(total)
        waypoints_reached = np.zeros(total, dtype=int)
        mission_times = np.zeros(total)
        success_mask = np.zeros(total, dtype=bool)
        sam_launched_mask = np.zeros(total, dtype=bool)
        sam_killed_mask = np.zeros(total, dtype=bool)
        survived_sam_mask = np.zeros(total, dtype=bool)
        min_miss_distances = np.full(total, np.nan)
        evasion_mask = np.zeros(total, dtype=bool)
        seeker_lock_counts = np.zeros(total)
        waypoints_ref = np.asarray(sim_req.waypoints, dtype=float)
        per_wp_arrival: list[list[np.ndarray]] = [[] for _ in waypoints_ref]

        for i in range(total):
            mean_wind = base_mean_wind * (
                1.0 + cfg.wind_mean_jitter * rng.uniform(-1, 1, size=3)
            )
            gust_std = np.clip(
                base_gust_std * (1.0 + cfg.wind_extra_gust * rng.uniform(-1, 1, size=3)),
                0.0,
                None,
            )
            mass = sim_req.mass * (1.0 + cfg.mass_jitter * rng.uniform(-1, 1))
            start = base_start.copy()
            start[0] += cfg.start_xy_jitter * rng.uniform(-1, 1)
            start[1] += cfg.start_xy_jitter * rng.uniform(-1, 1)
            attitude_bias_deg = tuple((cfg.imu_bias_std_deg * rng.standard_normal(3)).tolist())
            run_req = sim_req.model_copy(deep=True)
            for battery in run_req.anti_air.batteries:
                speed_scale = max(0.1, 1.0 + cfg.missile_speed_jitter * rng.uniform(-1, 1))
                noise_scale = max(0.0, 1.0 + cfg.seeker_noise_jitter * rng.uniform(-1, 1))
                battery.initial_speed *= speed_scale
                battery.boost_accel *= speed_scale
                battery.seeker_noise_std_deg *= noise_scale
            run_req.defensive_evasion.trigger_tgo = max(
                0.1,
                run_req.defensive_evasion.trigger_tgo
                + cfg.warning_delay_jitter * rng.uniform(-1, 1),
            )

            sim = build_simulator(
                run_req,
                seed=cfg.seed_base + i + 1,
                mass=float(mass),
                initial_position=start.tolist(),
                mean_wind=tuple(mean_wind.tolist()),
                gust_std=tuple(gust_std.tolist()),
                attitude_bias_deg=attitude_bias_deg,
            )
            result = sim.run()
            pos = result.state[:, 0:3]
            trajectories.append(pos)

            endpoints[i] = pos[-1]
            final_errors[i] = float(np.linalg.norm(pos[-1] - waypoints_ref[-1]))
            err = result.waypoint - pos
            rms_errors[i] = float(np.sqrt(np.mean(np.sum(err * err, axis=1))))

            reached_set = {idx for idx, _ in result.reached_log}
            waypoints_reached[i] = len(reached_set)
            if result.reached_log and result.reached_log[-1][0] == len(waypoints_ref) - 1:
                mission_times[i] = float(result.reached_log[-1][1])
            else:
                mission_times[i] = float(result.t[-1])

            for wp_idx, t_reach in result.reached_log:
                if wp_idx < 0 or wp_idx >= len(per_wp_arrival):
                    continue
                k = int(np.searchsorted(result.t, t_reach))
                per_wp_arrival[wp_idx].append(pos[min(k, len(pos) - 1)])

            nav_success = final_errors[i] <= cfg.success_radius
            interceptor_summary = result.interceptor_summary or {}
            defensive_summary = result.defensive_summary or {}
            n_launches = int(interceptor_summary.get("n_launches", 0) or 0)
            n_locks = int(interceptor_summary.get("n_seeker_locks", 0) or 0)
            min_miss = interceptor_summary.get("min_miss_distance")
            sam_launched_mask[i] = n_launches > 0
            sam_killed_mask[i] = bool(result.interceptor_killed)
            survived_sam_mask[i] = bool(sam_launched_mask[i] and not result.interceptor_killed)
            if min_miss is not None and np.isfinite(min_miss):
                min_miss_distances[i] = float(min_miss)
            evasion_mask[i] = int(defensive_summary.get("n_evasions", 0) or 0) > 0
            seeker_lock_counts[i] = n_locks
            success_mask[i] = bool(
                nav_success and (
                    not cfg.survival_mode
                    or not sam_launched_mask[i]
                    or survived_sam_mask[i]
                )
            )
            await websocket.send_json({
                "type": "run",
                "index": i + 1,
                "total": total,
                "trajectory": _sample_trajectory(pos, cfg.trajectory_stride),
                "endpoint": endpoints[i].tolist(),
                "final_error": float(final_errors[i]),
                "rms_error": float(rms_errors[i]),
                "waypoints_reached": int(waypoints_reached[i]),
                "mission_time": float(mission_times[i]),
                "success": bool(success_mask[i]),
                "sam_launched": bool(sam_launched_mask[i]),
                "sam_killed": bool(sam_killed_mask[i]),
                "survived_sam": bool(survived_sam_mask[i]),
                "min_miss_distance": (
                    float(min_miss_distances[i])
                    if np.isfinite(min_miss_distances[i])
                    else None
                ),
                "n_evasions": int(defensive_summary.get("n_evasions", 0) or 0),
                "n_seeker_locks": n_locks,
            })

        cep50 = np.zeros(len(waypoints_ref))
        cep95 = np.zeros(len(waypoints_ref))
        for i, wp in enumerate(waypoints_ref):
            arrivals = per_wp_arrival[i]
            if not arrivals:
                continue
            arr = np.asarray(arrivals)
            deltas = arr[:, :2] - wp[:2]
            cep50[i] = circular_error_probable(deltas, 50.0)
            cep95[i] = circular_error_probable(deltas, 95.0)

        await websocket.send_json({
            "type": "complete",
            "total": total,
            "success_rate": float(success_mask.mean()) if total else 0.0,
            "success_count": int(success_mask.sum()),
            "final_error_mean": _mean(final_errors),
            "final_error_std": _std(final_errors),
            "rms_error_mean": _mean(rms_errors),
            "mission_time_mean": _mean(mission_times),
            "endpoints": endpoints.tolist(),
            "final_errors": final_errors.tolist(),
            "rms_errors": rms_errors.tolist(),
            "success_mask": success_mask.tolist(),
            "waypoints_reached": waypoints_reached.tolist(),
            "mission_times": mission_times.tolist(),
            "waypoints": waypoints_ref.tolist(),
            "cep50_per_wp": cep50.tolist(),
            "cep95_per_wp": cep95.tolist(),
            "survival_rate": (
                float(survived_sam_mask[sam_launched_mask].mean())
                if sam_launched_mask.any()
                else 0.0
            ),
            "sam_kill_rate": (
                float(sam_killed_mask[sam_launched_mask].mean())
                if sam_launched_mask.any()
                else 0.0
            ),
            "sam_engagement_count": int(sam_launched_mask.sum()),
            "mean_min_miss_distance": (
                float(np.nanmean(min_miss_distances))
                if np.isfinite(min_miss_distances).any()
                else 0.0
            ),
            "min_miss_distances": [
                float(value) if np.isfinite(value) else None
                for value in min_miss_distances
            ],
            "evasion_rate": float(evasion_mask.mean()) if total else 0.0,
            "seeker_lock_mean": _mean(seeker_lock_counts),
        })
    except WebSocketDisconnect:
        return
    except Exception as exc:
        await websocket.send_json({"type": "error", "message": str(exc)})
    finally:
        await websocket.close()
