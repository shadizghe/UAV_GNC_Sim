"""
Monte Carlo dispersion analysis.

Runs N closed-loop simulations with randomised wind, sensor-bias, mass,
and start-position perturbations and aggregates the trajectory cloud,
endpoint scatter, success rate, RMS distribution, and circular-error-
probable (CEP) estimates per waypoint.

The caller supplies a `factory` callable that builds a fresh `Simulator`
given a perturbed parameter dict. This keeps Monte Carlo agnostic to the
particular GUI / config layout in use.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Sequence

import numpy as np


@dataclass
class MonteCarloConfig:
    n_runs: int = 50
    seed_base: int = 0

    # +/- fractional perturbations applied per run
    wind_mean_jitter: float = 0.40    # +-40% on each axis
    wind_extra_gust:  float = 0.50    # +-50% scaling on gust std
    mass_jitter:      float = 0.05    # +-5% on vehicle mass
    start_xy_jitter:  float = 0.30    # +-0.3 m start position (xy)
    imu_bias_std_deg: float = 0.5     # constant attitude bias per run [deg]

    success_radius:   float = 1.0     # endpoint must be within this of last WP


@dataclass
class MonteCarloResult:
    config: MonteCarloConfig
    trajectories: list[np.ndarray] = field(default_factory=list)   # each (N,3)
    endpoints: np.ndarray = field(default_factory=lambda: np.zeros((0, 3)))
    final_errors: np.ndarray = field(default_factory=lambda: np.zeros(0))
    rms_errors: np.ndarray = field(default_factory=lambda: np.zeros(0))
    waypoints_reached: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=int))
    success_mask: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=bool))
    mission_times: np.ndarray = field(default_factory=lambda: np.zeros(0))
    waypoints: np.ndarray = field(default_factory=lambda: np.zeros((0, 3)))
    cep50_per_wp: np.ndarray = field(default_factory=lambda: np.zeros(0))
    cep95_per_wp: np.ndarray = field(default_factory=lambda: np.zeros(0))

    @property
    def success_rate(self) -> float:
        if len(self.success_mask) == 0:
            return 0.0
        return float(self.success_mask.mean())


def circular_error_probable(deltas: np.ndarray,
                             percentile: float = 50.0) -> float:
    """Radius (m) containing `percentile`% of horizontal endpoint deltas.

    `deltas` is an (N, 2) array of (dx, dy) miss vectors.
    """
    if deltas.size == 0:
        return 0.0
    radii = np.linalg.norm(deltas, axis=1)
    return float(np.percentile(radii, percentile))


def run_monte_carlo(factory: Callable[[dict], "Simulator"],
                    base_params: dict,
                    cfg: MonteCarloConfig,
                    progress_cb: Callable[[int, int], None] | None = None
                    ) -> MonteCarloResult:
    """Execute a Monte Carlo dispersion study.

    Parameters
    ----------
    factory : callable
        Takes a perturbed `params` dict and returns a configured Simulator.
    base_params : dict
        Nominal scenario, must include keys
        {"mean_wind", "gust_std", "mass", "x0", "y0", "z0", "seed"}.
    cfg : MonteCarloConfig
    progress_cb : optional callback(i, total) for UI progress bars.
    """
    rng = np.random.default_rng(cfg.seed_base)

    waypoints_ref: np.ndarray | None = None
    trajectories: list[np.ndarray] = []
    endpoints = np.zeros((cfg.n_runs, 3))
    finals    = np.zeros(cfg.n_runs)
    rmss      = np.zeros(cfg.n_runs)
    reached   = np.zeros(cfg.n_runs, dtype=int)
    times     = np.zeros(cfg.n_runs)

    final_wp_endpoints: list[np.ndarray] = [[] for _ in range(0)]
    per_wp_arrival: list[list[np.ndarray]] = []

    for i in range(cfg.n_runs):
        p = dict(base_params)

        # --- perturbations ----------------------------------------------
        wm = np.array(p["mean_wind"], dtype=float)
        wm = wm * (1.0 + cfg.wind_mean_jitter * rng.uniform(-1, 1, size=3))

        gs = np.array(p["gust_std"], dtype=float)
        gs = np.clip(gs * (1.0 + cfg.wind_extra_gust * rng.uniform(-1, 1, size=3)),
                     0.0, None)

        mass = float(p["mass"]) * (1.0 + cfg.mass_jitter * rng.uniform(-1, 1))

        x0 = float(p["x0"]) + cfg.start_xy_jitter * rng.uniform(-1, 1)
        y0 = float(p["y0"]) + cfg.start_xy_jitter * rng.uniform(-1, 1)
        z0 = float(p["z0"])

        att_bias_deg = cfg.imu_bias_std_deg * rng.standard_normal(3)

        p.update(dict(
            mean_wind=tuple(wm.tolist()),
            gust_std=tuple(gs.tolist()),
            mass=mass,
            x0=x0, y0=y0, z0=z0,
            seed=cfg.seed_base + i + 1,
            attitude_bias_deg=tuple(att_bias_deg.tolist()),
        ))

        sim = factory(p)
        result = sim.run()

        if waypoints_ref is None:
            waypoints_ref = result.waypoints.copy()
            per_wp_arrival = [[] for _ in waypoints_ref]

        traj = result.state[:, 0:3]
        trajectories.append(traj)

        endpoints[i] = traj[-1]
        finals[i] = float(np.linalg.norm(traj[-1] - waypoints_ref[-1]))

        err = result.waypoint - traj
        rmss[i] = float(np.sqrt(np.mean(np.sum(err * err, axis=1))))

        reached_set = {idx for idx, _ in result.reached_log}
        reached[i] = len(reached_set)

        if result.reached_log and result.reached_log[-1][0] == len(waypoints_ref) - 1:
            times[i] = float(result.reached_log[-1][1])
        else:
            times[i] = float(result.t[-1])

        # Per-waypoint arrival positions (for CEP rings).
        # For each waypoint that was reached, store the position at arrival.
        for wp_idx, t_reach in result.reached_log:
            k = int(np.searchsorted(result.t, t_reach))
            k = min(k, len(traj) - 1)
            per_wp_arrival[wp_idx].append(traj[k])

        if progress_cb is not None:
            progress_cb(i + 1, cfg.n_runs)

    success = finals <= cfg.success_radius

    # CEP per waypoint (XY only).
    if waypoints_ref is None:
        waypoints_ref = np.zeros((0, 3))
    n_wp = len(waypoints_ref)
    cep50 = np.zeros(n_wp)
    cep95 = np.zeros(n_wp)
    for i, wp in enumerate(waypoints_ref):
        arrivals = per_wp_arrival[i] if i < len(per_wp_arrival) else []
        if not arrivals:
            continue
        arr = np.asarray(arrivals)
        deltas = arr[:, :2] - wp[:2]
        cep50[i] = circular_error_probable(deltas, 50.0)
        cep95[i] = circular_error_probable(deltas, 95.0)

    return MonteCarloResult(
        config=cfg,
        trajectories=trajectories,
        endpoints=endpoints,
        final_errors=finals,
        rms_errors=rmss,
        waypoints_reached=reached,
        success_mask=success,
        mission_times=times,
        waypoints=waypoints_ref,
        cep50_per_wp=cep50,
        cep95_per_wp=cep95,
    )
