"""
Editable waypoint table. Emits `waypoints_changed` whenever rows change.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QHeaderView,
)

from .theme import PALETTE


COLS = ("X [m]", "Y [m]", "Z [m]", "Yaw [deg]")


class MissionTable(QWidget):
    waypoints_changed = Signal(object, object)   # (waypoints Nx3, yaws N)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.verticalHeader().setDefaultSectionSize(26)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setAlternatingRowColors(True)
        self.table.itemChanged.connect(self._on_item_changed)
        self._suppress_signals = False

        self.btn_add = QPushButton("+ Add")
        self.btn_dup = QPushButton("Duplicate")
        self.btn_del = QPushButton("Delete")
        self.btn_del.setObjectName("DangerButton")
        self.btn_reset = QPushButton("Reset")

        self.btn_add.clicked.connect(self._add_row)
        self.btn_dup.clicked.connect(self._dup_row)
        self.btn_del.clicked.connect(self._del_row)
        self.btn_reset.clicked.connect(self._reset)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        for b in (self.btn_add, self.btn_dup, self.btn_del):
            btn_row.addWidget(b)
        btn_row.addStretch(1)
        btn_row.addWidget(self.btn_reset)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addLayout(btn_row)
        lay.addWidget(self.table, 1)

        self._initial: tuple[np.ndarray, np.ndarray] | None = None

    # ------------------------------------------------------------------ #
    def set_waypoints(self, waypoints: np.ndarray, yaws: np.ndarray) -> None:
        self._suppress_signals = True
        try:
            self.table.setRowCount(0)
            for i, w in enumerate(waypoints):
                self.table.insertRow(i)
                vals = (float(w[0]), float(w[1]), float(w[2]),
                        float(np.degrees(yaws[i])))
                for c, v in enumerate(vals):
                    item = QTableWidgetItem(f"{v:.2f}")
                    item.setTextAlignment(Qt.AlignCenter)
                    self.table.setItem(i, c, item)
        finally:
            self._suppress_signals = False
        if self._initial is None:
            self._initial = (waypoints.copy(), yaws.copy())
        self._emit()

    def get_waypoints(self) -> tuple[np.ndarray, np.ndarray]:
        n = self.table.rowCount()
        wps = np.zeros((n, 3))
        yaws = np.zeros(n)
        for r in range(n):
            try:
                wps[r, 0] = float(self.table.item(r, 0).text())
                wps[r, 1] = float(self.table.item(r, 1).text())
                wps[r, 2] = float(self.table.item(r, 2).text())
                yaws[r]   = np.radians(float(self.table.item(r, 3).text()))
            except (AttributeError, ValueError):
                pass
        return wps, yaws

    # ------------------------------------------------------------------ #
    def _on_item_changed(self, _item) -> None:
        if self._suppress_signals:
            return
        self._emit()

    def _emit(self) -> None:
        wps, yaws = self.get_waypoints()
        self.waypoints_changed.emit(wps, yaws)

    def _add_row(self) -> None:
        r = self.table.rowCount()
        self._suppress_signals = True
        self.table.insertRow(r)
        defaults = ("0.00", "0.00", "2.00", "0.00")
        for c, v in enumerate(defaults):
            it = QTableWidgetItem(v)
            it.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(r, c, it)
        self._suppress_signals = False
        self._emit()

    def _dup_row(self) -> None:
        r = self.table.currentRow()
        if r < 0:
            return
        self._suppress_signals = True
        self.table.insertRow(r + 1)
        for c in range(self.table.columnCount()):
            src = self.table.item(r, c)
            it = QTableWidgetItem(src.text() if src else "0.00")
            it.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(r + 1, c, it)
        self._suppress_signals = False
        self._emit()

    def _del_row(self) -> None:
        r = self.table.currentRow()
        if r < 0 or self.table.rowCount() <= 1:
            return
        self.table.removeRow(r)
        self._emit()

    def _reset(self) -> None:
        if self._initial is None:
            return
        self.set_waypoints(self._initial[0].copy(), self._initial[1].copy())
