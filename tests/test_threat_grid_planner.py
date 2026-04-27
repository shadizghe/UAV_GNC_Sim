from dataclasses import dataclass
import math
import unittest

import numpy as np

from src.guidance import StaticThreatZone, ThreatAwareReplanner, ThreatGridPlanner


@dataclass
class MovingBandit:
    name: str = "Bandit-1"
    x: float = 0.0
    y: float = 0.0
    z: float = 2.0
    heading: float = 0.0
    speed: float = 0.0
    detection_radius: float = 1.8


def segment_clearance(a: np.ndarray, b: np.ndarray, center: np.ndarray, radius: float) -> float:
    ab = b - a
    u = float(np.clip(np.dot(center - a, ab) / np.dot(ab, ab), 0.0, 1.0))
    closest = a + u * ab
    return float(np.linalg.norm(closest - center)) - radius


class ThreatGridPlannerTests(unittest.TestCase):
    def test_planner_routes_around_soft_bandit_envelope(self) -> None:
        bandit = MovingBandit()
        replanner = ThreatAwareReplanner()

        decision = replanner.maybe_replan(
            t=0.0,
            frame=0,
            position=np.array([-5.0, 0.0, 2.0]),
            target=np.array([5.0, 0.0, 2.0]),
            waypoint_index=0,
            moving_threats=[bandit],
        )

        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertGreaterEqual(len(decision.waypoints), 1)
        self.assertGreater(decision.event.clearance_score, 0.0)
        self.assertGreater(decision.event.planner_cost, 0.0)
        self.assertGreater(decision.event.nodes_expanded, 0)
        self.assertGreater(len(decision.event.cost_grid), 0)
        self.assertTrue(all(len(cell) == 5 for cell in decision.event.cost_grid))

        route = [
            np.array([-5.0, 0.0]),
            *[wp[:2] for wp in decision.waypoints],
            np.array([5.0, 0.0]),
        ]
        projected_radius = bandit.detection_radius + replanner.safety_margin
        min_clearance = min(
            segment_clearance(a, b, np.array([bandit.x, bandit.y]), projected_radius)
            for a, b in zip(route, route[1:])
        )
        self.assertGreaterEqual(min_clearance, -1e-6)

    def test_no_fly_zone_is_a_hard_obstacle(self) -> None:
        zone = StaticThreatZone(name="NFZ", cx=0.0, cy=0.0, r=1.6, kind="no_fly")
        replanner = ThreatAwareReplanner(static_zones=[zone])

        decision = replanner.maybe_replan(
            t=0.0,
            frame=0,
            position=np.array([-5.0, 0.0, 2.0]),
            target=np.array([5.0, 0.0, 2.0]),
            waypoint_index=0,
            moving_threats=[],
        )

        self.assertIsNotNone(decision)
        assert decision is not None
        route = [
            np.array([-5.0, 0.0]),
            *[wp[:2] for wp in decision.waypoints],
            np.array([5.0, 0.0]),
        ]
        blocked_radius = zone.r + replanner.safety_margin
        for a, b in zip(route, route[1:]):
            self.assertGreaterEqual(
                segment_clearance(a, b, np.array([zone.cx, zone.cy]), blocked_radius),
                -1e-6,
            )

    def test_clear_leg_does_not_replan(self) -> None:
        replanner = ThreatAwareReplanner(static_zones=[
            StaticThreatZone(name="Far", cx=0.0, cy=8.0, r=1.0, kind="threat"),
        ])

        decision = replanner.maybe_replan(
            t=0.0,
            frame=0,
            position=np.array([-5.0, 0.0, 2.0]),
            target=np.array([5.0, 0.0, 2.0]),
            waypoint_index=0,
            moving_threats=[],
        )

        self.assertIsNone(decision)

    def test_grid_planner_returns_bounded_inserted_waypoints(self) -> None:
        planner = ThreatGridPlanner(max_inserted_waypoints=3)
        replanner = ThreatAwareReplanner(
            planner=planner,
            static_zones=[
                StaticThreatZone(name="A", cx=-1.0, cy=0.0, r=1.2, kind="threat"),
                StaticThreatZone(name="B", cx=1.0, cy=1.2, r=1.2, kind="threat"),
            ],
        )

        decision = replanner.maybe_replan(
            t=0.0,
            frame=0,
            position=np.array([-5.0, 0.0, 2.0]),
            target=np.array([5.0, 0.0, 2.0]),
            waypoint_index=0,
            moving_threats=[],
        )

        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertLessEqual(len(decision.waypoints), 3)
        self.assertEqual(len(decision.event.inserted_waypoints), len(decision.waypoints))
        self.assertTrue(math.isfinite(decision.event.planner_cost))
        self.assertTrue(any(cell[2] > 0 for cell in decision.event.cost_grid))


if __name__ == "__main__":
    unittest.main()
