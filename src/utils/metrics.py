"""
Performance metrics for waypoint tracking.

Computes the figures of merit typically expected in a GNC report:
    - RMS and max 3D position error w.r.t. the active setpoint
    - Final position error at end of mission
    - Time-to-first-waypoint and total mission time
    - Per-axis settling time (2% band) around the last waypoint
    - Overshoot in altitude on the final leg
"""

from dataclasses import dataclass, asdict
import numpy as np


@dataclass
class PerformanceMetrics:
    rms_position_error: float
    max_position_error: float
    final_position_error: float
    waypoints_reached: int
    waypoints_total: int
    time_to_first_wp: float | None
    total_mission_time: float | None
    settle_time_z: float | None
    overshoot_z: float

    def summary(self) -> str:
        lines = [
            "=" * 60,
            "             FLIGHT PERFORMANCE SUMMARY",
            "=" * 60,
            f"  Waypoints reached      : {self.waypoints_reached} / {self.waypoints_total}",
            f"  Time to first waypoint : "
            + (f"{self.time_to_first_wp:6.2f} s" if self.time_to_first_wp is not None else "   n/a"),
            f"  Total mission time     : "
            + (f"{self.total_mission_time:6.2f} s" if self.total_mission_time is not None else "   n/a"),
            f"  RMS tracking error     : {self.rms_position_error:6.3f} m",
            f"  Max tracking error     : {self.max_position_error:6.3f} m",
            f"  Final position error   : {self.final_position_error:6.3f} m",
            f"  Altitude settle time   : "
            + (f"{self.settle_time_z:6.2f} s" if self.settle_time_z is not None else "   n/a"),
            f"  Altitude overshoot     : {self.overshoot_z * 100:6.2f} %",
            "=" * 60,
        ]
        return "\n".join(lines)


def compute_performance_metrics(result) -> PerformanceMetrics:
    t        = result.t
    state    = result.state
    pos      = state[:, 0:3]
    wp_track = result.waypoint
    waypoints = result.waypoints

    err = pos - wp_track
    err_norm = np.linalg.norm(err, axis=1)

    rms = float(np.sqrt(np.mean(err_norm ** 2)))
    mx  = float(np.max(err_norm))
    final_err = float(np.linalg.norm(pos[-1] - waypoints[-1]))

    reached = result.reached_log
    waypoints_reached = len({i for i, _ in reached})
    time_first = reached[0][1] if reached else None
    time_total = reached[-1][1] if reached and reached[-1][0] == len(waypoints) - 1 else None

    # Altitude settle-time and overshoot on the final leg.
    z_cmd_final = waypoints[-1, 2]
    z = pos[:, 2]
    # Consider the time after the last waypoint became active.
    last_active = np.where(np.all(wp_track == waypoints[-1], axis=1))[0]
    settle_time_z = None
    overshoot_z = 0.0
    if last_active.size > 0:
        k0 = last_active[0]
        seg_t = t[k0:]
        seg_z = z[k0:]
        # Settle-time band: max(2% of commanded altitude, 10 cm absolute).
        band = max(0.02 * abs(z_cmd_final), 0.10)
        out_of_band = np.where(np.abs(seg_z - z_cmd_final) > band)[0]
        if out_of_band.size == 0:
            settle_time_z = 0.0
        elif out_of_band[-1] < len(seg_t) - 1:
            settle_time_z = float(seg_t[out_of_band[-1] + 1] - seg_t[0])
        # Overshoot relative to the step from the prior commanded altitude.
        if len(waypoints) >= 2:
            z_prev = waypoints[-2, 2]
        else:
            z_prev = pos[0, 2]
        step = z_cmd_final - z_prev
        if abs(step) > 1e-6:
            # Excess travel past the target in the direction of the step.
            excess = float(np.max(np.sign(step) * (seg_z - z_cmd_final)))
            overshoot_z = max(0.0, excess / abs(step))

    return PerformanceMetrics(
        rms_position_error=rms,
        max_position_error=mx,
        final_position_error=final_err,
        waypoints_reached=waypoints_reached,
        waypoints_total=len(waypoints),
        time_to_first_wp=time_first,
        total_mission_time=time_total,
        settle_time_z=settle_time_z,
        overshoot_z=overshoot_z,
    )
