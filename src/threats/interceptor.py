"""
Anti-air interceptor with proportional-navigation (PN) guidance.

The textbook missile-guidance law: a guided interceptor is launched from a
ground battery when the ownship enters the battery's launch envelope, and
steers itself to a collision course using line-of-sight rate.

3D ("true") proportional navigation:

    r       = p_target - p_missile
    v_rel   = v_target - v_missile
    omega   = (r × v_rel) / |r|²        line-of-sight angular velocity
    V_c     = -dot(v_rel, r) / |r|       closing speed (positive when closing)
    a_PN    = N · V_c · (omega × r̂)      acceleration command, perpendicular to LOS

The command is applied as a *lateral* acceleration (perpendicular to the
missile's velocity vector, magnitude-capped at ``max_lateral_accel``); a
boost-then-coast axial profile produces realistic flight dynamics:

    boost (t < t_boost):  axial accel = +boost_accel along v̂
    coast (t ≥ t_boost):  axial drag  = -coast_drag · |v|

Gravity acts on the body throughout. The interceptor self-destructs on
intercept (range < lethal_radius), miss (range_increasing past CPA), or
fuel-out (age > max_time).

This is standard, textbook missile-guidance material — published in every
guidance & control textbook (Zarchan, Siouris, Garnell, etc.).  It is the
single most-asked topic in defense-GNC interviews.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable
import numpy as np


# ----------------------------------------------------------------------- #
# Status codes carried in the per-step snapshot for the UI.
# ----------------------------------------------------------------------- #
STATUS_INACTIVE = 0          # slot is empty
STATUS_BOOST    = 1          # under thrust
STATUS_COAST    = 2          # coasting toward target
STATUS_HIT      = 3          # final frame on intercept
STATUS_MISS     = 4          # final frame on CPA / fuel-out

SEEKER_SEARCH   = 0          # no target in seeker gate
SEEKER_LOCKED   = 1          # tracking measured LOS
SEEKER_MEMORY   = 2          # coasting on short target memory


def _normalise(v: np.ndarray, eps: float = 1e-9) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > eps else np.zeros_like(v)


@dataclass
class Interceptor:
    """3-DOF point-mass missile under PN guidance.

    Coordinates and velocities are in the inertial ENU frame.
    """
    pos: np.ndarray
    vel: np.ndarray
    nav_constant: float    = 4.0      # dimensionless PN gain N
    max_lateral_accel: float = 40.0   # m/s² — saturates the PN command
    boost_time: float      = 0.6      # s
    boost_accel: float     = 25.0     # m/s² along body axis during boost
    coast_drag: float      = 0.05     # 1/s linear-drag time constant in coast
    lethal_radius: float   = 0.5      # m
    arming_time: float     = 0.65     # s before the proximity fuse is live
    max_time: float        = 6.0      # s (fuel-out / self-destruct)
    seeker_enabled: bool   = True
    seeker_range: float    = 14.0     # m
    seeker_fov_deg: float  = 70.0     # full-angle seeker field of view
    seeker_noise_std_deg: float = 0.25
    seeker_memory_time: float = 0.35  # s after lock break
    g: float               = 9.81
    rng: np.random.Generator | None = None

    # --- runtime state ------------------------------------------------- #
    age: float             = 0.0
    alive: bool            = True
    status: int            = STATUS_BOOST
    miss_distance: float   = float("inf")
    closest_approach_time: float = 0.0
    prev_range: float      = float("inf")
    battery_index: int     = 0
    launched_t: float      = 0.0
    seeker_status: int     = SEEKER_SEARCH
    has_lock: bool         = False
    last_seen_t: float     = -1e9
    last_seen_pos: np.ndarray = field(default_factory=lambda: np.zeros(3))
    last_seen_vel: np.ndarray = field(default_factory=lambda: np.zeros(3))
    seeker_target_pos: np.ndarray = field(default_factory=lambda: np.full(3, np.nan))

    def _seeker_measurement(self, target_pos: np.ndarray) -> np.ndarray:
        """Return a noisy apparent target position along measured LOS."""
        rel = target_pos - self.pos
        rng = float(np.linalg.norm(rel))
        los = _normalise(rel)
        sigma = np.deg2rad(max(0.0, self.seeker_noise_std_deg))
        if sigma <= 0.0 or rng <= 1e-6:
            return target_pos.copy()

        generator = self.rng if self.rng is not None else np.random.default_rng(0)
        jitter = generator.normal(0.0, sigma, size=3)
        jitter -= los * float(np.dot(jitter, los))
        measured_los = _normalise(los + jitter)
        return self.pos + measured_los * rng

    def _seeker_track(
        self,
        target_pos: np.ndarray,
        target_vel: np.ndarray,
        t_now: float,
    ) -> tuple[np.ndarray | None, np.ndarray | None, list[dict]]:
        if not self.seeker_enabled:
            self.seeker_status = SEEKER_LOCKED
            self.has_lock = True
            self.seeker_target_pos = target_pos.copy()
            return target_pos, target_vel, []

        events: list[dict] = []
        rel = target_pos - self.pos
        rng = float(np.linalg.norm(rel))
        los = _normalise(rel)
        v_hat = _normalise(self.vel)
        if np.linalg.norm(v_hat) <= 0.0:
            v_hat = los

        half_fov = np.deg2rad(max(1.0, self.seeker_fov_deg) * 0.5)
        cos_angle = float(np.dot(v_hat, los))
        fov_error_deg = float(np.rad2deg(np.arccos(np.clip(cos_angle, -1.0, 1.0))))
        in_fov = cos_angle >= np.cos(half_fov)
        in_range = rng <= self.seeker_range

        if in_range and in_fov:
            measured_pos = self._seeker_measurement(target_pos)
            was_locked = self.has_lock
            self.has_lock = True
            self.seeker_status = SEEKER_LOCKED
            self.last_seen_t = t_now
            self.last_seen_pos = measured_pos.copy()
            self.last_seen_vel = target_vel.copy()
            self.seeker_target_pos = measured_pos.copy()
            if not was_locked:
                events.append({
                    "type": "seeker_lock",
                    "t": t_now,
                    "battery": self.battery_index,
                    "range": rng,
                    "fov_error_deg": fov_error_deg,
                    "position": self.pos.tolist(),
                    "target": measured_pos.tolist(),
                })
            return measured_pos, target_vel, events

        if self.has_lock and (t_now - self.last_seen_t) <= self.seeker_memory_time:
            dt_mem = max(0.0, t_now - self.last_seen_t)
            memory_pos = self.last_seen_pos + self.last_seen_vel * dt_mem
            self.seeker_status = SEEKER_MEMORY
            self.seeker_target_pos = memory_pos.copy()
            return memory_pos, self.last_seen_vel, events

        if self.has_lock:
            events.append({
                "type": "seeker_lost",
                "t": t_now,
                "battery": self.battery_index,
                "range": rng,
                "fov_error_deg": fov_error_deg,
                "position": self.pos.tolist(),
            })
        self.has_lock = False
        self.seeker_status = SEEKER_SEARCH
        self.seeker_target_pos = np.full(3, np.nan)
        return None, None, events

    def step(self, dt: float, target_pos: np.ndarray, target_vel: np.ndarray,
             t_now: float) -> list[dict]:
        """Advance one step. Returns seeker and terminal events."""
        if not self.alive:
            return []

        target_pos = np.asarray(target_pos, dtype=float)
        target_vel = np.asarray(target_vel, dtype=float)
        events: list[dict] = []
        seeker_pos, seeker_vel, seeker_events = self._seeker_track(
            target_pos, target_vel, t_now,
        )
        events.extend(seeker_events)

        # --- relative geometry / PN command ---------------------------- #
        true_r = target_pos - self.pos
        rng = float(np.linalg.norm(true_r))
        if seeker_pos is not None and seeker_vel is not None:
            r = seeker_pos - self.pos
            v_rel = seeker_vel - self.vel
        else:
            r = true_r
            v_rel = target_vel - self.vel
        # closing speed (positive when range is decreasing)
        V_c = -float(np.dot(v_rel, r)) / max(float(np.linalg.norm(r)), 1e-6)
        # LOS angular velocity vector
        omega = np.cross(r, v_rel) / max(float(np.dot(r, r)), 1e-6)
        # PN lateral command is zero when the seeker has no usable track.
        if seeker_pos is not None:
            a_pn = self.nav_constant * V_c * np.cross(omega, _normalise(r))
        else:
            a_pn = np.zeros(3)

        # Saturate the lateral command at the airframe limit. We project
        # out any longitudinal component first so axial dynamics are owned
        # by the boost/coast model below.
        v_hat = _normalise(self.vel)
        if np.linalg.norm(v_hat) > 0:
            a_pn = a_pn - v_hat * float(np.dot(a_pn, v_hat))
        a_pn_mag = float(np.linalg.norm(a_pn))
        if a_pn_mag > self.max_lateral_accel:
            a_pn *= self.max_lateral_accel / a_pn_mag

        # --- axial dynamics: boost / coast ----------------------------- #
        if self.age < self.boost_time:
            self.status = STATUS_BOOST
            a_axial = self.boost_accel * v_hat
        else:
            self.status = STATUS_COAST
            # First-order linear drag in the coast phase.
            a_axial = -self.coast_drag * self.vel

        # --- gravity ---------------------------------------------------- #
        a_gravity = np.array([0.0, 0.0, -self.g])

        a_total = a_pn + a_axial + a_gravity

        # --- integrate (semi-implicit Euler) --------------------------- #
        self.vel = self.vel + a_total * dt
        self.pos = self.pos + self.vel * dt
        self.age += dt

        # --- terminal-condition checks --------------------------------- #
        # CPA (closest point of approach): track minimum range seen.
        if rng < self.miss_distance:
            self.miss_distance = rng
            self.closest_approach_time = t_now

        if self.age >= self.arming_time and rng <= self.lethal_radius:
            self.alive = False
            self.status = STATUS_HIT
            events.append({
                "type": "hit",
                "t": t_now,
                "battery": self.battery_index,
                "miss_distance": float(rng),
                "time_of_flight": float(t_now - self.launched_t),
                "position": self.pos.tolist(),
            })
            return events

        if self.age > self.max_time:
            self.alive = False
            self.status = STATUS_MISS
            events.append({
                "type": "miss",
                "t": t_now,
                "battery": self.battery_index,
                "miss_distance": float(self.miss_distance),
                "reason": "fuel_out",
                "time_of_flight": float(self.age),
                "position": self.pos.tolist(),
            })
            return events

        # Range increasing past CPA → terminal miss.
        if V_c < -1.0 and rng > self.prev_range + 0.05:
            self.alive = False
            self.status = STATUS_MISS
            events.append({
                "type": "miss",
                "t": t_now,
                "battery": self.battery_index,
                "miss_distance": float(self.miss_distance),
                "reason": "past_cpa",
                "time_of_flight": float(self.age),
                "position": self.pos.tolist(),
            })
            return events
        self.prev_range = rng
        return events

    def snapshot(self) -> tuple[float, float, float, float, float, float, int, int, float, float, float]:
        return (float(self.pos[0]), float(self.pos[1]), float(self.pos[2]),
                float(self.vel[0]), float(self.vel[1]), float(self.vel[2]),
                int(self.status), int(self.seeker_status),
                float(self.seeker_target_pos[0]), float(self.seeker_target_pos[1]),
                float(self.seeker_target_pos[2]))


@dataclass
class InterceptorBattery:
    """Static SAM site: launches missiles when the target enters its envelope."""
    name: str
    x: float
    y: float
    z: float = 0.0
    launch_range: float    = 8.0      # m — horizontal range trigger
    min_engage_alt: float  = 1.0      # m — don't fire at the launch pad
    cooldown: float        = 1.5      # s between launches
    max_active: int        = 2        # concurrent shots in flight
    max_total_shots: int   = 6
    initial_speed: float   = 4.0      # m/s — speed at launch (post-tube)
    nav_constant: float    = 4.0
    max_lateral_accel: float = 40.0
    boost_time: float      = 0.6
    boost_accel: float     = 25.0
    coast_drag: float      = 0.05
    lethal_radius: float   = 0.5
    arming_time: float     = 0.65
    max_time: float        = 6.0
    seeker_enabled: bool   = True
    seeker_range: float    = 14.0
    seeker_fov_deg: float  = 70.0
    seeker_noise_std_deg: float = 0.25
    seeker_memory_time: float = 0.35

    last_launch_t: float   = field(default=-1e9)
    n_launched: int        = 0

    def can_launch(self, t: float, target_pos: np.ndarray,
                   n_active_for_battery: int) -> bool:
        if self.n_launched >= self.max_total_shots:
            return False
        if n_active_for_battery >= self.max_active:
            return False
        if (t - self.last_launch_t) < self.cooldown:
            return False
        dx = float(target_pos[0]) - self.x
        dy = float(target_pos[1]) - self.y
        if (dx * dx + dy * dy) ** 0.5 > self.launch_range:
            return False
        if float(target_pos[2]) < self.min_engage_alt:
            return False
        return True

    def fire(self, t: float, target_pos: np.ndarray, battery_index: int,
             rng: np.random.Generator | None = None
             ) -> Interceptor:
        # Initial heading: lead-pursuit toward the target. Pure aim at the
        # current target position is fine — PN closes the rest of the gap.
        origin = np.array([self.x, self.y, self.z], dtype=float)
        aim = np.asarray(target_pos, dtype=float) - origin
        v0 = self.initial_speed * _normalise(aim)
        self.last_launch_t = t
        self.n_launched += 1
        return Interceptor(
            pos=origin.copy(),
            vel=v0,
            nav_constant=self.nav_constant,
            max_lateral_accel=self.max_lateral_accel,
            boost_time=self.boost_time,
            boost_accel=self.boost_accel,
            coast_drag=self.coast_drag,
            lethal_radius=self.lethal_radius,
            arming_time=self.arming_time,
            max_time=self.max_time,
            seeker_enabled=self.seeker_enabled,
            seeker_range=self.seeker_range,
            seeker_fov_deg=self.seeker_fov_deg,
            seeker_noise_std_deg=self.seeker_noise_std_deg,
            seeker_memory_time=self.seeker_memory_time,
            battery_index=battery_index,
            launched_t=t,
            rng=rng,
        )


class InterceptorManager:
    """Steps a fleet of batteries + active interceptors against the ownship."""

    def __init__(self, batteries: Iterable[InterceptorBattery] | None = None,
                 rng: np.random.Generator | None = None):
        self.batteries: list[InterceptorBattery] = list(batteries or [])
        self.active: list[Interceptor] = []
        self.events: list[dict] = []
        self.launch_events: list[dict] = []
        self._slot_capacity = sum(b.max_active for b in self.batteries)
        self.rng = rng if rng is not None else np.random.default_rng(2)

    @property
    def slot_capacity(self) -> int:
        return self._slot_capacity

    def __len__(self) -> int:
        return len(self.batteries)

    # ------------------------------------------------------------------ #
    # Per-step update
    # ------------------------------------------------------------------ #
    def step(self, dt: float, t: float,
             target_pos: np.ndarray, target_vel: np.ndarray) -> list[dict]:
        per_step_events: list[dict] = []

        # 1) Step existing interceptors.
        for itc in self.active:
            for ev in itc.step(dt, target_pos, target_vel, t):
                self.events.append(ev)
                per_step_events.append(ev)

        # 2) Launch from batteries that have a ready opportunity.
        for b_idx, b in enumerate(self.batteries):
            n_active = sum(1 for i in self.active
                           if i.alive and i.battery_index == b_idx)
            if b.can_launch(t, target_pos, n_active):
                itc = b.fire(t, target_pos, b_idx, self.rng)
                self.active.append(itc)
                launch_ev = {
                    "type": "launch",
                    "t": t,
                    "battery": b_idx,
                    "battery_name": b.name,
                    "origin": [b.x, b.y, b.z],
                    "target": list(map(float, target_pos)),
                }
                self.launch_events.append(launch_ev)
                self.events.append(launch_ev)
                per_step_events.append(launch_ev)

        return per_step_events

    # ------------------------------------------------------------------ #
    # Logging helpers
    # ------------------------------------------------------------------ #
    def snapshot(self) -> np.ndarray:
        """(slot_capacity, 7) array — [x, y, z, vx, vy, vz, status]."""
        out = np.zeros((self._slot_capacity, 11))
        # Fixed slot mapping: each battery owns max_active contiguous slots.
        slot_offsets: list[int] = []
        offset = 0
        for b in self.batteries:
            slot_offsets.append(offset)
            offset += b.max_active

        # Fill from the active list, distributing per-battery into slots.
        per_battery_index: list[int] = [0] * len(self.batteries)
        for itc in self.active:
            b = itc.battery_index
            local = per_battery_index[b]
            if local >= self.batteries[b].max_active:
                continue
            row = slot_offsets[b] + local
            per_battery_index[b] += 1
            out[row] = itc.snapshot()
        return out

    @property
    def hits(self) -> int:
        return sum(1 for e in self.events if e["type"] == "hit")

    @property
    def misses(self) -> int:
        return sum(1 for e in self.events if e["type"] == "miss")

    def summary(self) -> dict:
        n_launches = len(self.launch_events)
        miss_distances = [e["miss_distance"] for e in self.events
                          if e["type"] in ("hit", "miss")]
        return {
            "n_launches": n_launches,
            "n_hits":     self.hits,
            "n_misses":   self.misses,
            "n_seeker_locks": sum(1 for e in self.events
                                  if e["type"] == "seeker_lock"),
            "n_seeker_losses": sum(1 for e in self.events
                                   if e["type"] == "seeker_lost"),
            "min_miss_distance": (
                float(min(miss_distances)) if miss_distances else float("inf")
            ),
        }
