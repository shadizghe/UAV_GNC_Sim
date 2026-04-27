"""Threat-aware waypoint replanning.

This is intentionally lightweight enough to run inside the fixed-step
simulator loop. It watches the active leg, projects moving bandit detection
envelopes a short time into the future, and inserts a temporary waypoint when
the current leg becomes contested.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Iterable, Protocol

import numpy as np

from .threat_grid_planner import ThreatGridPlanner


class MovingThreat(Protocol):
    name: str
    x: float
    y: float
    z: float
    heading: float
    speed: float
    detection_radius: float


@dataclass(frozen=True)
class StaticThreatZone:
    name: str
    cx: float
    cy: float
    r: float
    kind: str = "threat"


@dataclass
class ThreatCircle:
    name: str
    x: float
    y: float
    radius: float
    kind: str
    source_index: int = -1


@dataclass
class RerouteEvent:
    t: float
    frame: int
    threat_name: str
    threat_kind: str
    waypoint_index: int
    original_target: list[float]
    inserted_waypoint: list[float]
    envelope_radius: float
    clearance_score: float
    inserted_waypoints: list[list[float]] = field(default_factory=list)
    planner_cost: float = 0.0
    nodes_expanded: int = 0
    cost_grid: list[list[float]] = field(default_factory=list)
    message: str = "CONTACT - REROUTING"


@dataclass
class ReplanDecision:
    waypoints: list[np.ndarray]
    event: RerouteEvent

    @property
    def waypoint(self) -> np.ndarray:
        return self.waypoints[0]


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


@dataclass
class ThreatAwareReplanner:
    static_zones: Iterable[StaticThreatZone] = field(default_factory=list)
    planner: ThreatGridPlanner = field(default_factory=ThreatGridPlanner)
    safety_margin: float = 0.55
    projection_time_s: float = 2.5
    min_leg_length: float = 0.75
    min_replan_interval_s: float = 1.2
    max_events: int = 10

    def __post_init__(self) -> None:
        self.static_zones = list(self.static_zones)
        self._last_replan_t = -float("inf")
        self._contested_keys: set[tuple[str, str, int, int]] = set()
        self._event_count = 0

    def maybe_replan(
        self,
        *,
        t: float,
        frame: int,
        position: np.ndarray,
        target: np.ndarray,
        waypoint_index: int,
        moving_threats: Iterable[MovingThreat],
    ) -> ReplanDecision | None:
        if self._event_count >= self.max_events:
            return None
        if t - self._last_replan_t < self.min_replan_interval_s:
            return None

        start_xy = np.asarray(position[:2], dtype=float)
        target_xy = np.asarray(target[:2], dtype=float)
        leg = target_xy - start_xy
        leg_len = float(np.linalg.norm(leg))
        if leg_len < self.min_leg_length:
            return None

        circles = self._project_threats(moving_threats)
        contested: list[tuple[ThreatCircle, float, float]] = []
        for circle in circles:
            center = np.array([circle.x, circle.y], dtype=float)
            distance, along = _segment_circle_distance(start_xy, target_xy, center)
            if 0.02 < along < 0.98 and distance <= circle.radius:
                contested.append((circle, distance, along))

        if not contested:
            return None

        circle, distance, _along = min(contested, key=lambda item: item[1])
        key = (
            circle.kind,
            circle.name,
            int(round(float(target[0]) * 10.0)),
            int(round(float(target[1]) * 10.0)),
        )
        if key in self._contested_keys:
            return None

        path = self.planner.plan(
            start_xy=start_xy,
            target_xy=target_xy,
            threats=circles,
        )
        if path is None:
            return None

        altitude = max(float(position[2]), float(target[2]))
        inserted_waypoints = [
            np.array([float(point[0]), float(point[1]), altitude], dtype=float)
            for point in path.waypoints
        ]
        if not inserted_waypoints:
            return None
        if np.linalg.norm(inserted_waypoints[0][:2] - start_xy) < self.min_leg_length:
            return None

        self._contested_keys.add(key)
        self._last_replan_t = t
        self._event_count += 1

        event = RerouteEvent(
            t=float(t),
            frame=int(frame),
            threat_name=circle.name,
            threat_kind=circle.kind,
            waypoint_index=int(waypoint_index),
            original_target=[float(v) for v in target],
            inserted_waypoint=[float(v) for v in inserted_waypoints[0]],
            inserted_waypoints=[
                [float(v) for v in waypoint]
                for waypoint in inserted_waypoints
            ],
            envelope_radius=float(circle.radius),
            clearance_score=float(path.clearance),
            planner_cost=float(path.cost),
            nodes_expanded=int(path.nodes_expanded),
            cost_grid=path.cost_grid,
        )
        return ReplanDecision(waypoints=inserted_waypoints, event=event)

    def _project_threats(
        self,
        moving_threats: Iterable[MovingThreat],
    ) -> list[ThreatCircle]:
        circles: list[ThreatCircle] = []
        for index, threat in enumerate(moving_threats):
            lookahead = max(0.0, float(threat.speed)) * self.projection_time_s
            circles.append(
                ThreatCircle(
                    name=str(threat.name),
                    x=float(threat.x) + math.cos(float(threat.heading)) * lookahead,
                    y=float(threat.y) + math.sin(float(threat.heading)) * lookahead,
                    radius=max(0.1, float(threat.detection_radius) + self.safety_margin),
                    kind="bandit",
                    source_index=index,
                )
            )
        for zone in self.static_zones:
            circles.append(
                ThreatCircle(
                    name=zone.name,
                    x=float(zone.cx),
                    y=float(zone.cy),
                    radius=max(0.1, float(zone.r) + self.safety_margin),
                    kind=zone.kind,
                )
            )
        return circles

    @staticmethod
    def _clearance_score(
        start_xy: np.ndarray,
        detour_xy: np.ndarray,
        target_xy: np.ndarray,
        circles: list[ThreatCircle],
    ) -> float:
        score = float("inf")
        for circle in circles:
            center = np.array([circle.x, circle.y], dtype=float)
            d1, _ = _segment_circle_distance(start_xy, detour_xy, center)
            d2, _ = _segment_circle_distance(detour_xy, target_xy, center)
            score = min(score, d1 - circle.radius, d2 - circle.radius)
        return score
