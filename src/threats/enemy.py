"""
Enemy-drone threat model.

Each `EnemyDrone` is a constant-speed kinematic point with a heading and a
turn-rate cap. Supported behaviours:

* ``loiter``  — hold position.
* ``patrol``  — orbit a fixed centre at a fixed radius (tangential heading).
* ``pursue``  — steer toward the current ownship position.

A `ThreatManager` owns a list of enemies, steps them in lockstep with the
ownship, and produces an evasion offset that the guidance layer can add to
the active waypoint target so the ownship laterally deflects away from any
threat within its detection radius.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Iterable

import numpy as np


def _wrap_pi(a: float) -> float:
    return (a + math.pi) % (2.0 * math.pi) - math.pi


@dataclass
class EnemyDrone:
    """Kinematic enemy drone with a behaviour-driven guidance policy."""

    name: str
    x: float = 0.0
    y: float = 0.0
    z: float = 3.0
    heading: float = 0.0                     # rad, 0 = +x
    speed: float = 1.8                       # m/s
    turn_rate_max: float = math.radians(70)  # rad/s
    detection_radius: float = 4.0            # m
    lethal_radius: float = 1.2               # m
    behavior: str = "patrol"                 # patrol | loiter | pursue
    orbit_cx: float = 0.0
    orbit_cy: float = 0.0
    orbit_r: float = 3.0
    orbit_dir: int = 1                       # +1 CCW, -1 CW

    def step(self, dt: float, ownship_pos: np.ndarray) -> None:
        if self.behavior == "loiter":
            return

        if self.behavior == "pursue":
            tx, ty = float(ownship_pos[0]), float(ownship_pos[1])
        else:  # patrol: aim for a point slightly ahead along the orbit
            dx = self.x - self.orbit_cx
            dy = self.y - self.orbit_cy
            rho = math.hypot(dx, dy)
            ang = math.atan2(dy, dx) if rho > 1e-6 else 0.0
            lead = self.orbit_dir * 0.25  # rad of look-ahead around the circle
            tx = self.orbit_cx + self.orbit_r * math.cos(ang + lead)
            ty = self.orbit_cy + self.orbit_r * math.sin(ang + lead)

        desired = math.atan2(ty - self.y, tx - self.x)
        diff = _wrap_pi(desired - self.heading)
        max_step = self.turn_rate_max * dt
        if diff > max_step:
            diff = max_step
        elif diff < -max_step:
            diff = -max_step
        self.heading = _wrap_pi(self.heading + diff)

        self.x += self.speed * math.cos(self.heading) * dt
        self.y += self.speed * math.sin(self.heading) * dt

    def snapshot(self) -> tuple[float, float, float, float]:
        return (self.x, self.y, self.z, self.heading)


@dataclass
class ThreatReport:
    """Per-run aggregated threat-encounter statistics."""

    enemy_names: list[str]
    min_range_history: np.ndarray           # (N,)   min over all enemies per step
    per_step_min_range: np.ndarray          # (N, M) range to each enemy per step
    in_detection: np.ndarray                # (N, M) bool — within detection radius
    in_lethal:    np.ndarray                # (N, M) bool — within lethal radius
    intercept_events: list[tuple[int, float]] = field(default_factory=list)
    # (enemy_index, time_first_lethal_contact)

    @property
    def n_intercepts(self) -> int:
        return len(self.intercept_events)

    @property
    def min_range(self) -> float:
        if self.min_range_history.size == 0:
            return float("inf")
        return float(self.min_range_history.min())

    def time_in_detection(self, dt: float) -> float:
        if self.in_detection.size == 0:
            return 0.0
        any_det = self.in_detection.any(axis=1)
        return float(any_det.sum()) * dt

    def time_in_lethal(self, dt: float) -> float:
        if self.in_lethal.size == 0:
            return 0.0
        any_leth = self.in_lethal.any(axis=1)
        return float(any_leth.sum()) * dt


class ThreatManager:
    """Container + stepper for a list of `EnemyDrone` objects.

    Provides two hooks into the simulation loop:

    * :meth:`step` — advance all enemy states by ``dt``.
    * :meth:`evasion_offset` — XYZ delta to add to the ownship's active
      waypoint target so it deflects away from any threat currently inside
      the threat's detection radius. Saturates at ``evasion_max`` m laterally.
    """

    def __init__(self,
                 enemies: Iterable[EnemyDrone] | None = None,
                 evasion_gain: float = 3.0,
                 evasion_max:  float = 4.0,
                 evasion_alt_bump: float = 1.2,
                 react: bool = True):
        self.enemies: list[EnemyDrone] = list(enemies or [])
        self.evasion_gain = float(evasion_gain)
        self.evasion_max  = float(evasion_max)
        self.evasion_alt_bump = float(evasion_alt_bump)
        self.react = bool(react)

    def __len__(self) -> int:
        return len(self.enemies)

    def step(self, dt: float, ownship_pos: np.ndarray) -> None:
        for e in self.enemies:
            e.step(dt, ownship_pos)

    def snapshot(self) -> np.ndarray:
        """(M, 4) array of current [x, y, z, heading] for every enemy."""
        if not self.enemies:
            return np.zeros((0, 4))
        return np.array([e.snapshot() for e in self.enemies])

    def ranges_to(self, ownship_pos: np.ndarray) -> np.ndarray:
        """(M,) 3D ranges from ownship to each enemy."""
        if not self.enemies:
            return np.zeros(0)
        snap = self.snapshot()[:, :3]
        d = snap - ownship_pos[None, :]
        return np.linalg.norm(d, axis=1)

    def evasion_offset(self, ownship_pos: np.ndarray) -> np.ndarray:
        """Sum of repulsion vectors from enemies inside detection range."""
        off = np.zeros(3)
        if not self.enemies or not self.react:
            return off
        for e in self.enemies:
            dx = ownship_pos[0] - e.x
            dy = ownship_pos[1] - e.y
            dz = ownship_pos[2] - e.z
            d = math.sqrt(dx * dx + dy * dy + dz * dz) + 1e-6
            if d >= e.detection_radius:
                continue
            w = (e.detection_radius - d) / e.detection_radius  # 0..1
            # Lateral push away (horizontal unit vector from enemy → ownship)
            horiz = math.hypot(dx, dy) + 1e-6
            off[0] += self.evasion_gain * w * (dx / horiz)
            off[1] += self.evasion_gain * w * (dy / horiz)
            # Small altitude bump so the ownship pops up and over
            off[2] += self.evasion_alt_bump * w

        mag = math.hypot(off[0], off[1])
        if mag > self.evasion_max:
            scale = self.evasion_max / mag
            off[0] *= scale
            off[1] *= scale
        # cap altitude bump too
        if off[2] > self.evasion_alt_bump:
            off[2] = self.evasion_alt_bump
        return off
