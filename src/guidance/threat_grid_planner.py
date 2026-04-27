"""Deterministic threat-cost grid planner for tactical reroutes.

The planner runs a bounded 2D A* search in the local battlespace around the
current leg. No-fly zones are hard obstacles; bandits and threat zones are
soft-cost fields, so the planner can still produce a least-bad path if the
airspace gets tight.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import heapq
import math
from typing import Iterable, Protocol

import numpy as np


class ThreatObstacle(Protocol):
    name: str
    x: float
    y: float
    radius: float
    kind: str


GridNode = tuple[int, int]


@dataclass(frozen=True)
class PlannerPath:
    waypoints: list[np.ndarray]
    cost: float
    clearance: float
    nodes_expanded: int
    cost_grid: list[list[float]] = field(default_factory=list)


@dataclass
class ThreatGridPlanner:
    cell_size: float = 0.45
    boundary_padding: float = 3.0
    threat_buffer: float = 1.4
    max_nodes: int = 24000
    max_inserted_waypoints: int = 5

    def plan(
        self,
        *,
        start_xy: np.ndarray,
        target_xy: np.ndarray,
        threats: Iterable[ThreatObstacle],
    ) -> PlannerPath | None:
        circles = list(threats)
        if np.linalg.norm(target_xy - start_xy) < self.cell_size:
            return None

        origin, shape = self._bounds(start_xy, target_xy, circles)
        start = self._nearest_free(self._to_node(start_xy, origin, shape), origin, shape, circles)
        goal = self._nearest_free(self._to_node(target_xy, origin, shape), origin, shape, circles)
        if start is None or goal is None:
            return None

        raw_path, cost, expanded = self._a_star(start, goal, origin, shape, circles)
        if raw_path is None:
            return None

        points = [self._to_world(node, origin) for node in raw_path]
        points[0] = np.asarray(start_xy, dtype=float)
        points[-1] = np.asarray(target_xy, dtype=float)
        smoothed = self._smooth(points, circles)
        inserted = self._select_inserted_waypoints(smoothed, circles)
        if not inserted:
            return None

        clearance = self._path_clearance([np.asarray(start_xy), *inserted, np.asarray(target_xy)], circles)
        return PlannerPath(
            waypoints=inserted,
            cost=float(cost),
            clearance=float(clearance),
            nodes_expanded=int(expanded),
            cost_grid=self._sample_cost_grid(origin, shape, circles),
        )

    def _bounds(
        self,
        start_xy: np.ndarray,
        target_xy: np.ndarray,
        circles: list[ThreatObstacle],
    ) -> tuple[np.ndarray, tuple[int, int]]:
        xs = [float(start_xy[0]), float(target_xy[0])]
        ys = [float(start_xy[1]), float(target_xy[1])]
        for circle in circles:
            r = float(circle.radius) + self.boundary_padding + self.threat_buffer
            xs.extend([float(circle.x) - r, float(circle.x) + r])
            ys.extend([float(circle.y) - r, float(circle.y) + r])

        min_x = min(xs) - self.boundary_padding
        min_y = min(ys) - self.boundary_padding
        max_x = max(xs) + self.boundary_padding
        max_y = max(ys) + self.boundary_padding
        cols = max(3, int(math.ceil((max_x - min_x) / self.cell_size)) + 1)
        rows = max(3, int(math.ceil((max_y - min_y) / self.cell_size)) + 1)
        return np.array([min_x, min_y], dtype=float), (cols, rows)

    def _a_star(
        self,
        start: GridNode,
        goal: GridNode,
        origin: np.ndarray,
        shape: tuple[int, int],
        circles: list[ThreatObstacle],
    ) -> tuple[list[GridNode] | None, float, int]:
        open_heap: list[tuple[float, int, GridNode]] = []
        heapq.heappush(open_heap, (0.0, 0, start))
        came_from: dict[GridNode, GridNode] = {}
        g_score: dict[GridNode, float] = {start: 0.0}
        closed: set[GridNode] = set()
        tie = 1
        expanded = 0

        while open_heap and expanded < self.max_nodes:
            _, _, current = heapq.heappop(open_heap)
            if current in closed:
                continue
            if current == goal:
                return self._reconstruct(came_from, current), g_score[current], expanded

            closed.add(current)
            expanded += 1
            for neighbor, step_distance in self._neighbors(current, shape):
                if neighbor in closed:
                    continue
                point = self._to_world(neighbor, origin)
                risk = self._point_risk(point, circles)
                if math.isinf(risk):
                    continue
                tentative = g_score[current] + step_distance + risk
                if tentative >= g_score.get(neighbor, float("inf")):
                    continue
                came_from[neighbor] = current
                g_score[neighbor] = tentative
                priority = tentative + self._heuristic(neighbor, goal)
                heapq.heappush(open_heap, (priority, tie, neighbor))
                tie += 1

        return None, float("inf"), expanded

    def _neighbors(self, node: GridNode, shape: tuple[int, int]) -> Iterable[tuple[GridNode, float]]:
        cols, rows = shape
        x, y = node
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                nx, ny = x + dx, y + dy
                if 0 <= nx < cols and 0 <= ny < rows:
                    yield (nx, ny), math.hypot(dx, dy) * self.cell_size

    def _nearest_free(
        self,
        node: GridNode,
        origin: np.ndarray,
        shape: tuple[int, int],
        circles: list[ThreatObstacle],
    ) -> GridNode | None:
        cols, rows = shape
        sx, sy = node
        for radius in range(0, 8):
            candidates: list[GridNode] = []
            for dx in range(-radius, radius + 1):
                for dy in range(-radius, radius + 1):
                    if max(abs(dx), abs(dy)) != radius:
                        continue
                    nx, ny = sx + dx, sy + dy
                    if 0 <= nx < cols and 0 <= ny < rows:
                        candidates.append((nx, ny))
            candidates.sort(key=lambda item: (item[0] - sx) ** 2 + (item[1] - sy) ** 2)
            for candidate in candidates:
                if not math.isinf(self._point_risk(self._to_world(candidate, origin), circles)):
                    return candidate
        return None

    def _point_risk(self, point: np.ndarray, circles: list[ThreatObstacle]) -> float:
        risk = 0.0
        for circle in circles:
            center = np.array([float(circle.x), float(circle.y)], dtype=float)
            clearance = float(np.linalg.norm(point - center)) - float(circle.radius)
            kind = str(circle.kind)
            if kind == "no_fly" and clearance < 0.0:
                return float("inf")

            weight = 32.0 if kind == "threat" else 22.0
            if kind == "no_fly":
                weight = 60.0
            if clearance < 0.0:
                risk += weight * (4.0 + abs(clearance) * 3.0)
            elif clearance < self.threat_buffer:
                ratio = (self.threat_buffer - clearance) / self.threat_buffer
                risk += weight * ratio * ratio
        return risk

    def _smooth(self, points: list[np.ndarray], circles: list[ThreatObstacle]) -> list[np.ndarray]:
        if len(points) <= 2:
            return points
        smoothed = [points[0]]
        i = 0
        while i < len(points) - 1:
            j = len(points) - 1
            while j > i + 1:
                if self._segment_is_acceptable(points[i], points[j], circles):
                    break
                j -= 1
            smoothed.append(points[j])
            i = j
        return smoothed

    def _segment_is_acceptable(
        self,
        a: np.ndarray,
        b: np.ndarray,
        circles: list[ThreatObstacle],
    ) -> bool:
        for circle in circles:
            center = np.array([float(circle.x), float(circle.y)], dtype=float)
            clearance = _segment_circle_clearance(a, b, center, float(circle.radius))
            if str(circle.kind) == "no_fly" and clearance < 0.0:
                return False
            if str(circle.kind) != "no_fly" and clearance < 0.0:
                return False
        return True

    def _select_inserted_waypoints(
        self,
        points: list[np.ndarray],
        circles: list[ThreatObstacle],
    ) -> list[np.ndarray]:
        reduced = [np.asarray(point, dtype=float) for point in points]
        while len(reduced) - 2 > self.max_inserted_waypoints:
            best_index: int | None = None
            best_penalty = float("inf")
            for i in range(1, len(reduced) - 1):
                if not self._segment_is_acceptable(reduced[i - 1], reduced[i + 1], circles):
                    continue
                penalty = (
                    float(np.linalg.norm(reduced[i + 1] - reduced[i - 1]))
                    - float(np.linalg.norm(reduced[i] - reduced[i - 1]))
                    - float(np.linalg.norm(reduced[i + 1] - reduced[i]))
                )
                if penalty < best_penalty:
                    best_penalty = penalty
                    best_index = i
            if best_index is None:
                break
            del reduced[best_index]
        return reduced[1:-1]

    def _sample_cost_grid(
        self,
        origin: np.ndarray,
        shape: tuple[int, int],
        circles: list[ThreatObstacle],
    ) -> list[list[float]]:
        if not circles:
            return []

        cols, rows = shape
        stride = max(1, int(math.ceil(max(cols, rows) / 34)))
        cell_size = self.cell_size * stride
        samples: list[list[float]] = []
        for ix in range(0, cols, stride):
            for iy in range(0, rows, stride):
                point = self._to_world((ix, iy), origin)
                risk = self._point_risk(point, circles)
                blocked = 1.0 if math.isinf(risk) else 0.0
                samples.append([
                    float(point[0]),
                    float(point[1]),
                    120.0 if math.isinf(risk) else float(min(risk, 120.0)),
                    blocked,
                    float(cell_size),
                ])
        return samples

    def _path_clearance(self, points: list[np.ndarray], circles: list[ThreatObstacle]) -> float:
        if not circles:
            return float("inf")
        clearance = float("inf")
        for a, b in zip(points, points[1:]):
            for circle in circles:
                center = np.array([float(circle.x), float(circle.y)], dtype=float)
                clearance = min(
                    clearance,
                    _segment_circle_clearance(a, b, center, float(circle.radius)),
                )
        return clearance

    def _to_node(self, point: np.ndarray, origin: np.ndarray, shape: tuple[int, int]) -> GridNode:
        cols, rows = shape
        raw = np.rint((point - origin) / self.cell_size).astype(int)
        return (
            int(np.clip(raw[0], 0, cols - 1)),
            int(np.clip(raw[1], 0, rows - 1)),
        )

    def _to_world(self, node: GridNode, origin: np.ndarray) -> np.ndarray:
        return origin + np.array([node[0] * self.cell_size, node[1] * self.cell_size], dtype=float)

    def _heuristic(self, node: GridNode, goal: GridNode) -> float:
        return math.hypot(node[0] - goal[0], node[1] - goal[1]) * self.cell_size

    @staticmethod
    def _reconstruct(came_from: dict[GridNode, GridNode], current: GridNode) -> list[GridNode]:
        path = [current]
        while current in came_from:
            current = came_from[current]
            path.append(current)
        path.reverse()
        return path


def _segment_circle_clearance(
    a: np.ndarray,
    b: np.ndarray,
    center: np.ndarray,
    radius: float,
) -> float:
    ab = b - a
    denom = float(np.dot(ab, ab))
    if denom < 1e-9:
        return float(np.linalg.norm(a - center)) - radius
    u = float(np.clip(np.dot(center - a, ab) / denom, 0.0, 1.0))
    closest = a + u * ab
    return float(np.linalg.norm(closest - center)) - radius
