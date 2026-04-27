"""
Mission scenario presets.

Each preset bundles a complete mission setup — waypoints, yaws, geofence
zones, enemy drones — that the dashboard can load with a single click so
demos and reviewers can flip between operationally distinct scenarios
without manually rebuilding the scene.

Presets are returned as plain dicts with the same schema the Streamlit
session_state slots expect, so loading is a straight assignment.
"""

from __future__ import annotations

from typing import Callable
import numpy as np


def _free_flight() -> dict:
    return {
        "label": "Free Flight",
        "tag":   "Sandbox",
        "description": (
            "Starter rectangle pattern with a couple of permissive zones — "
            "good baseline for tuning."
        ),
        "waypoints": [
            [0.0, 0.0, 2.5], [5.0, 0.0, 2.5], [5.0, 5.0, 3.5],
            [0.0, 5.0, 3.5], [0.0, 0.0, 3.0], [0.0, 0.0, 0.2],
        ],
        "yaws_deg": [0.0, 0.0, 90.0, 180.0, 270.0, 0.0],
        "zones": [
            {"name": "RESTRICTED-1", "cx": 2.5, "cy": 2.5,
             "r": 1.2, "z_min": 0.0, "z_max": 6.0, "kind": "no_fly"},
            {"name": "THREAT-A", "cx": 4.5, "cy": 5.0,
             "r": 1.0, "z_min": 0.0, "z_max": 6.0, "kind": "threat"},
        ],
        "enemies": [
            {"name": "BANDIT-1", "x": 6.0, "y": 2.0, "z": 3.0,
             "behavior": "patrol", "speed": 1.6, "det_r": 3.5, "leth_r": 1.0,
             "orbit_cx": 5.0, "orbit_cy": 2.5, "orbit_r": 2.0},
            {"name": "BANDIT-2", "x": -2.0, "y": 5.0, "z": 3.0,
             "behavior": "pursue", "speed": 1.2, "det_r": 4.0, "leth_r": 1.0,
             "orbit_cx": 0.0, "orbit_cy": 0.0, "orbit_r": 0.0},
            {"name": "BANDIT-3", "x": 2.5, "y": 7.5, "z": 3.5,
             "behavior": "loiter", "speed": 1.1, "det_r": 3.0, "leth_r": 0.8,
             "orbit_cx": 0.0, "orbit_cy": 0.0, "orbit_r": 0.0},
        ],
        "duration_s": 40.0,
        "enable_threats": True,
        "enable_geofence": True,
    }


def _isr_sweep() -> dict:
    """Boustrophedon (lawn-mower) ISR search over a 12x10 m box."""
    rows_y = [-4.0, -2.0, 0.0, 2.0, 4.0]
    wps: list[list[float]] = [[-6.0, rows_y[0], 4.0]]
    yaws: list[float] = [0.0]
    for i, y in enumerate(rows_y):
        if i % 2 == 0:
            wps.append([6.0, y, 4.0]);  yaws.append(0.0)
            if i < len(rows_y) - 1:
                wps.append([6.0, rows_y[i + 1], 4.0]);  yaws.append(90.0)
        else:
            wps.append([-6.0, y, 4.0]); yaws.append(180.0)
            if i < len(rows_y) - 1:
                wps.append([-6.0, rows_y[i + 1], 4.0]); yaws.append(90.0)
    wps.append([0.0, 0.0, 0.5]);  yaws.append(0.0)
    return {
        "label": "ISR Sweep",
        "tag": "Search",
        "description": (
            "Lawn-mower coverage of a 12x10 m search box at 4 m AGL — "
            "no threats, geofence off."
        ),
        "waypoints": wps, "yaws_deg": yaws,
        "zones": [], "enemies": [],
        "duration_s": 60.0,
        "enable_threats": False, "enable_geofence": False,
    }


def _perimeter_patrol() -> dict:
    """Eight-vertex circular orbit around a notional base, two threats inside."""
    R = 6.0; n = 8
    th = np.linspace(0.0, 2 * np.pi, n, endpoint=False)
    wps = [[float(R * np.cos(a)), float(R * np.sin(a)), 3.0] for a in th]
    wps.append([0.0, 0.0, 0.5])
    yaws = [float(np.rad2deg(a + np.pi / 2)) for a in th] + [0.0]
    return {
        "label": "Perimeter Patrol",
        "tag": "Patrol",
        "description": (
            "Circular orbit at R=6 m around a defended asset at the origin. "
            "Two no-fly cores guard the centre."
        ),
        "waypoints": wps, "yaws_deg": yaws,
        "zones": [
            {"name": "ASSET-CORE", "cx": 0.0, "cy": 0.0,
             "r": 2.0, "z_min": 0.0, "z_max": 8.0, "kind": "no_fly"},
            {"name": "SAM-SITE", "cx": 3.5, "cy": -3.0,
             "r": 1.4, "z_min": 0.0, "z_max": 6.0, "kind": "threat"},
        ],
        "enemies": [
            {"name": "BANDIT-1", "x": 0.0, "y": 0.0, "z": 3.0,
             "behavior": "patrol", "speed": 1.4, "det_r": 3.0, "leth_r": 1.0,
             "orbit_cx": 0.0, "orbit_cy": 0.0, "orbit_r": 1.5},
        ],
        "duration_s": 70.0,
        "enable_threats": True, "enable_geofence": True,
    }


def _strike_ingress() -> dict:
    """Straight-line dash through a hostile corridor onto a target waypoint."""
    return {
        "label": "Strike Ingress",
        "tag": "Strike",
        "description": (
            "Run-in along a hostile corridor between two SAM bubbles, hold "
            "above the target, then egress. Bandits are aggressive (pursue + patrol)."
        ),
        "waypoints": [
            [-7.0, 0.0, 4.0], [-3.0, 0.0, 4.0], [ 1.0, 0.0, 3.5],
            [ 5.0, 0.0, 2.5],   # target hold
            [ 5.0, 0.0, 4.0], [ 0.0, 4.0, 4.0], [-6.0, 4.0, 0.5],
        ],
        "yaws_deg": [0.0, 0.0, 0.0, 0.0, 90.0, 180.0, 180.0],
        "zones": [
            {"name": "SAM-NORTH", "cx": 0.0, "cy": 2.5,
             "r": 1.6, "z_min": 0.0, "z_max": 8.0, "kind": "threat"},
            {"name": "SAM-SOUTH", "cx": 0.0, "cy": -2.5,
             "r": 1.6, "z_min": 0.0, "z_max": 8.0, "kind": "threat"},
            {"name": "TARGET", "cx": 5.0, "cy": 0.0,
             "r": 0.8, "z_min": 0.0, "z_max": 5.0, "kind": "no_fly"},
        ],
        "enemies": [
            {"name": "MIG-1", "x": 6.0, "y": 3.0, "z": 4.0,
             "behavior": "pursue", "speed": 2.0, "det_r": 4.5, "leth_r": 1.2,
             "orbit_cx": 0.0, "orbit_cy": 0.0, "orbit_r": 0.0},
            {"name": "CAP-1", "x": -2.0, "y": -4.0, "z": 4.0,
             "behavior": "patrol", "speed": 1.8, "det_r": 4.0, "leth_r": 1.1,
             "orbit_cx": -2.0, "orbit_cy": -3.0, "orbit_r": 2.0},
        ],
        "duration_s": 50.0,
        "enable_threats": True, "enable_geofence": True,
    }


def _search_and_rescue() -> dict:
    """Dense expanding-square SAR pattern."""
    legs = [(2, 0), (0, 2), (-4, 0), (0, -4), (6, 0), (0, 6),
            (-8, 0), (0, -8)]
    cur = np.array([0.0, 0.0]); wps = [[0.0, 0.0, 3.0]]; yaws = [0.0]
    for dx, dy in legs:
        cur = cur + np.array([dx, dy])
        wps.append([float(cur[0]), float(cur[1]), 3.0])
        yaws.append(float(np.rad2deg(np.arctan2(dy, dx))))
    wps.append([0.0, 0.0, 0.5]); yaws.append(0.0)
    return {
        "label": "Search & Rescue",
        "tag": "SAR",
        "description": (
            "Expanding-square SAR pattern centred on the launch point. "
            "Threats off; geofence keeps the bird out of a debris exclusion zone."
        ),
        "waypoints": wps, "yaws_deg": yaws,
        "zones": [
            {"name": "DEBRIS", "cx": 4.0, "cy": -4.0,
             "r": 1.5, "z_min": 0.0, "z_max": 5.0, "kind": "no_fly"},
        ],
        "enemies": [],
        "duration_s": 75.0,
        "enable_threats": False, "enable_geofence": True,
    }


# Ordered registry: dropdown will preserve this order.
_REGISTRY: list[Callable[[], dict]] = [
    _free_flight,
    _isr_sweep,
    _perimeter_patrol,
    _strike_ingress,
    _search_and_rescue,
]


def list_presets() -> list[dict]:
    """Return all presets in display order. Each call rebuilds them so
    callers can safely mutate the returned dicts without bleed-through."""
    return [factory() for factory in _REGISTRY]


def get_preset(label: str) -> dict | None:
    for factory in _REGISTRY:
        p = factory()
        if p["label"] == label:
            return p
    return None
