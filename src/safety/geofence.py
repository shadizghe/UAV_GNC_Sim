"""
Cylindrical geofence / threat-zone primitives and violation checker.

A zone is a vertical cylinder defined in the inertial ENU frame:
    (cx, cy, radius, z_min, z_max, kind)

`kind` is informational ("no_fly" or "threat") so the visualisation can
colour them differently. The checker runs a trajectory through every
zone and reports per-step intrusion, total time-in-zone, the first
violation timestamp, and which zones were ever entered.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import numpy as np


@dataclass
class CylinderZone:
    name: str
    cx: float
    cy: float
    radius: float
    z_min: float = 0.0
    z_max: float = 50.0
    kind: str = "no_fly"     # "no_fly" or "threat"

    def contains(self, pos: np.ndarray) -> np.ndarray:
        """Vectorised point-in-cylinder test. `pos` is (..., 3)."""
        dx = pos[..., 0] - self.cx
        dy = pos[..., 1] - self.cy
        in_disk = (dx * dx + dy * dy) <= (self.radius ** 2)
        in_band = (pos[..., 2] >= self.z_min) & (pos[..., 2] <= self.z_max)
        return in_disk & in_band


@dataclass
class GeofenceReport:
    n_violation_steps: int
    total_time_in_zone: float
    first_violation_t: float | None
    zones_entered: list[str]
    per_step_inside: np.ndarray   # (N,) bool — any zone hit at step k


def check_geofence(t: np.ndarray,
                   trajectory: np.ndarray,
                   zones: Sequence[CylinderZone]) -> GeofenceReport:
    """Check a flown trajectory against a list of zones.

    Parameters
    ----------
    t : (N,) array of times.
    trajectory : (N, 3) inertial positions.
    zones : iterable of CylinderZone.
    """
    if not zones or trajectory.size == 0:
        return GeofenceReport(0, 0.0, None, [],
                              np.zeros(len(t), dtype=bool))

    pos = np.asarray(trajectory, dtype=float)
    inside_any = np.zeros(len(t), dtype=bool)
    zones_hit: list[str] = []

    for z in zones:
        mask = z.contains(pos)
        if mask.any():
            zones_hit.append(z.name)
        inside_any |= mask

    n_steps = int(inside_any.sum())
    if n_steps == 0:
        return GeofenceReport(0, 0.0, None, [], inside_any)

    dt = float(np.median(np.diff(t))) if len(t) > 1 else 0.0
    first_idx = int(np.argmax(inside_any))   # first True
    first_t = float(t[first_idx])

    return GeofenceReport(
        n_violation_steps=n_steps,
        total_time_in_zone=n_steps * dt,
        first_violation_t=first_t,
        zones_entered=zones_hit,
        per_step_inside=inside_any,
    )
