"""
Waypoint sequencer.

Consumes the current inertial position and returns the active 3D waypoint.
Advances to the next waypoint when the drone enters a user-defined
acceptance radius. Once all waypoints are consumed the last waypoint is
held so the drone finishes on station.
"""

import numpy as np


class WaypointManager:
    def __init__(self, waypoints: np.ndarray,
                 acceptance_radius: float = 0.4,
                 yaw_setpoints: np.ndarray | None = None):
        self.waypoints = np.asarray(waypoints, dtype=float)
        if self.waypoints.ndim != 2 or self.waypoints.shape[1] != 3:
            raise ValueError("waypoints must have shape (N, 3)")

        self.acceptance_radius = acceptance_radius
        self.index = 0
        self.reached_log: list[tuple[int, float]] = []  # (index, time)
        self.dynamic_waypoint_flags = [False for _ in range(len(self.waypoints))]

        if yaw_setpoints is None:
            self.yaw_setpoints = np.zeros(len(self.waypoints))
        else:
            self.yaw_setpoints = np.asarray(yaw_setpoints, dtype=float)

    @property
    def done(self) -> bool:
        return self.index >= len(self.waypoints) - 1

    @property
    def current_waypoint(self) -> np.ndarray:
        return self.waypoints[self.index]

    @property
    def current_yaw(self) -> float:
        return float(self.yaw_setpoints[self.index])

    @property
    def current_is_dynamic(self) -> bool:
        if not self.dynamic_waypoint_flags:
            return False
        return bool(self.dynamic_waypoint_flags[self.index])

    def insert_current_waypoint(self, waypoint: np.ndarray, yaw: float | None = None) -> None:
        """Insert a temporary waypoint immediately before the active target."""
        self.insert_current_waypoints([waypoint], yaw=yaw)

    def insert_current_waypoints(
        self,
        waypoints: list[np.ndarray] | np.ndarray,
        yaw: float | None = None,
    ) -> None:
        """Insert temporary waypoints immediately before the active target."""
        if len(waypoints) == 0:
            return
        arr = np.asarray(waypoints, dtype=float)
        if arr.ndim == 1:
            arr = arr.reshape(1, 3)
        if arr.ndim != 2 or arr.shape[1] != 3:
            raise ValueError("inserted waypoints must have shape (N, 3)")
        yaw_value = self.current_yaw if yaw is None else float(yaw)
        self.waypoints = np.insert(self.waypoints, self.index, arr, axis=0)
        self.yaw_setpoints = np.insert(
            self.yaw_setpoints,
            self.index,
            np.full(arr.shape[0], yaw_value),
        )
        for offset in range(arr.shape[0]):
            self.dynamic_waypoint_flags.insert(self.index + offset, True)

    def update(self, position: np.ndarray, t: float) -> np.ndarray:
        """Advance the active waypoint if within acceptance radius; return it."""
        wp = self.waypoints[self.index]
        if np.linalg.norm(position - wp) < self.acceptance_radius:
            self.reached_log.append((self.index, t))
            if self.index < len(self.waypoints) - 1:
                self.index += 1
        return self.waypoints[self.index]
