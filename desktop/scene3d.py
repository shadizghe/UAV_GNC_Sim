"""
3D trajectory viewport built on pyqtgraph's OpenGL widget.

Shows the ground grid, planned mission path, waypoints as pillars, the
flown trajectory, and an animated drone body (arms + rotor tips).
"""

from __future__ import annotations

import numpy as np
import pyqtgraph.opengl as gl
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget, QVBoxLayout

from src.utils.rotations import euler_to_rotmat
from .theme import PALETTE


def _hex_to_rgba(hex_str: str, alpha: float = 1.0) -> tuple:
    c = QColor(hex_str)
    return (c.redF(), c.greenF(), c.blueF(), alpha)


class Scene3D(QWidget):
    """Embeddable 3D viewport. Use set_trajectory() + set_drone_pose()."""

    ARM_LEN = 0.45
    ROTOR_R = 0.08

    def __init__(self, parent=None):
        super().__init__(parent)

        self.view = gl.GLViewWidget()
        self.view.setBackgroundColor(PALETTE["bg"])
        self.view.setCameraPosition(distance=18, elevation=22, azimuth=-55)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.view)

        self._grid_item: gl.GLGridItem | None = None
        self._planned_item: gl.GLLinePlotItem | None = None
        self._pillars_item: gl.GLLinePlotItem | None = None
        self._waypoints_item: gl.GLScatterPlotItem | None = None
        self._flown_item: gl.GLLinePlotItem | None = None
        self._drone_body: gl.GLLinePlotItem | None = None
        self._rotor_items: list[gl.GLScatterPlotItem] = []
        self._shadow_item: gl.GLLinePlotItem | None = None

        self._install_grid()
        self._install_drone()

    # ------------------------------------------------------------------ #
    # Static scenery
    # ------------------------------------------------------------------ #
    def _install_grid(self) -> None:
        grid = gl.GLGridItem()
        grid.setSize(x=30, y=30)
        grid.setSpacing(x=1, y=1)
        grid.setColor(_hex_to_rgba(PALETTE["grid"], 0.6))
        self.view.addItem(grid)
        self._grid_item = grid

        # axes (X red, Y green, Z blue) at origin for orientation
        axis_len = 2.0
        axes = np.array([
            [0, 0, 0], [axis_len, 0, 0],
            [0, 0, 0], [0, axis_len, 0],
            [0, 0, 0], [0, 0, axis_len],
        ])
        axis_colors = np.array([
            [1, 0.3, 0.3, 1], [1, 0.3, 0.3, 1],
            [0.3, 1, 0.3, 1], [0.3, 1, 0.3, 1],
            [0.3, 0.5, 1, 1], [0.3, 0.5, 1, 1],
        ])
        ax = gl.GLLinePlotItem(pos=axes, color=axis_colors, width=2,
                               mode="lines", antialias=True)
        self.view.addItem(ax)

    # ------------------------------------------------------------------ #
    # Mission
    # ------------------------------------------------------------------ #
    def set_mission(self, waypoints: np.ndarray) -> None:
        wps = np.asarray(waypoints, dtype=float)

        # planned path
        if self._planned_item is not None:
            self.view.removeItem(self._planned_item)
        self._planned_item = gl.GLLinePlotItem(
            pos=wps, color=_hex_to_rgba(PALETTE["amber"], 0.85),
            width=2.5, mode="line_strip", antialias=True,
        )
        self.view.addItem(self._planned_item)

        # waypoint pillars (dotted lines from ground up to waypoint)
        if self._pillars_item is not None:
            self.view.removeItem(self._pillars_item)
        pillar_pts = []
        for w in wps:
            pillar_pts.append([w[0], w[1], 0.0])
            pillar_pts.append([w[0], w[1], w[2]])
        self._pillars_item = gl.GLLinePlotItem(
            pos=np.array(pillar_pts),
            color=_hex_to_rgba(PALETTE["amber"], 0.35),
            width=1.0, mode="lines", antialias=True,
        )
        self.view.addItem(self._pillars_item)

        # waypoint markers
        if self._waypoints_item is not None:
            self.view.removeItem(self._waypoints_item)
        self._waypoints_item = gl.GLScatterPlotItem(
            pos=wps, size=14,
            color=np.tile(np.array(_hex_to_rgba(PALETTE["amber"], 1.0)),
                          (len(wps), 1)),
            pxMode=True,
        )
        self.view.addItem(self._waypoints_item)

    # ------------------------------------------------------------------ #
    # Flown trajectory (progressive)
    # ------------------------------------------------------------------ #
    def set_trajectory(self, xyz: np.ndarray) -> None:
        if len(xyz) < 2:
            return
        if self._flown_item is None:
            self._flown_item = gl.GLLinePlotItem(
                pos=xyz, color=_hex_to_rgba(PALETTE["cyan"], 0.95),
                width=2.5, mode="line_strip", antialias=True,
            )
            self.view.addItem(self._flown_item)
        else:
            self._flown_item.setData(pos=xyz)

        # ground shadow trail
        shadow = xyz.copy()
        shadow[:, 2] = 0.0
        if self._shadow_item is None:
            self._shadow_item = gl.GLLinePlotItem(
                pos=shadow, color=_hex_to_rgba("#000000", 0.45),
                width=1.5, mode="line_strip", antialias=True,
            )
            self.view.addItem(self._shadow_item)
        else:
            self._shadow_item.setData(pos=shadow)

    def clear_trajectory(self) -> None:
        for item_name in ("_flown_item", "_shadow_item"):
            item = getattr(self, item_name)
            if item is not None:
                self.view.removeItem(item)
                setattr(self, item_name, None)

    # ------------------------------------------------------------------ #
    # Drone mesh
    # ------------------------------------------------------------------ #
    def _install_drone(self) -> None:
        self._drone_body = gl.GLLinePlotItem(
            pos=np.zeros((4, 3)),
            color=_hex_to_rgba(PALETTE["cyan"], 1.0),
            width=3.0, mode="lines", antialias=True,
        )
        self.view.addItem(self._drone_body)

        rotor_colors = [PALETTE["cyan"], PALETTE["cyan"],
                        PALETTE["pink"], PALETTE["pink"]]
        for c in rotor_colors:
            item = gl.GLScatterPlotItem(
                pos=np.zeros((1, 3)), size=14,
                color=np.array([_hex_to_rgba(c, 1.0)]),
                pxMode=True,
            )
            self.view.addItem(item)
            self._rotor_items.append(item)

    def set_drone_pose(self, pos: np.ndarray, euler: np.ndarray) -> None:
        R = euler_to_rotmat(float(euler[0]), float(euler[1]), float(euler[2]))
        # body-frame arm tips (X-config)
        arms_body = np.array([
            [ self.ARM_LEN,  self.ARM_LEN, 0.0],
            [-self.ARM_LEN, -self.ARM_LEN, 0.0],
            [ self.ARM_LEN, -self.ARM_LEN, 0.0],
            [-self.ARM_LEN,  self.ARM_LEN, 0.0],
        ])
        tips = (R @ arms_body.T).T + pos

        # two line segments: tip0-tip1 and tip2-tip3
        body_pts = np.array([tips[0], tips[1], tips[2], tips[3]])
        self._drone_body.setData(pos=body_pts)

        for i, tip in enumerate(tips):
            self._rotor_items[i].setData(pos=tip.reshape(1, 3))

    def reset_drone(self) -> None:
        self.set_drone_pose(np.zeros(3), np.zeros(3))
