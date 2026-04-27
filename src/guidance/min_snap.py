"""
Minimum-snap polynomial trajectory generator (Mellinger & Kumar 2011).

Given a sequence of N+1 spatial waypoints and N segment durations, fits
a 7th-order polynomial per axis per segment that:

  - passes through every waypoint,
  - has zero velocity, acceleration, and jerk at the start and end,
  - is C^6 continuous at every internal junction (vel, accel, jerk, snap,
    crackle, pop all match across segments),
  - minimises the time integral of squared snap (4th derivative) over the
    full trajectory.

Each segment polynomial is solved in a normalised local coordinate s ∈ [0, 1]
to keep the KKT system well-conditioned for long segment durations
(otherwise the j-th derivative row scales as T^j and the system goes
numerically singular for T ≳ 3 s on a 6th-derivative continuity row).
Physical-time derivatives are recovered via the chain rule:
``p^(k)(t) = (1/T_i^k) * p^(k)(s)``.

Usage
-----
    traj = MinSnapTrajectory(waypoints, segment_times)
    pos, vel, acc = traj(t)            # at any time t in [0, T_total]
    pos, vel, acc, jerk, snap = traj(t, max_deriv=4)
"""

from __future__ import annotations

import math
import numpy as np

POLY_ORDER = 7         # 7th-order polynomial -> 8 coefficients per segment
N_COEFFS = POLY_ORDER + 1


def _deriv_basis(s: float, k: int) -> np.ndarray:
    """Row vector b such that p^{(k)}(s) = b @ c, with c = [c_0..c_7] and
    p(s) = sum_n c_n s^n. Differentiation is in the *normalised* coordinate s."""
    out = np.zeros(N_COEFFS)
    for n in range(k, N_COEFFS):
        out[n] = math.factorial(n) // math.factorial(n - k) * (s ** (n - k))
    return out


def _snap_cost_unit() -> np.ndarray:
    """∫_0^1 (d^4 p / ds^4)^2 ds for one unit-length segment."""
    Q = np.zeros((N_COEFFS, N_COEFFS))
    for i in range(4, N_COEFFS):
        ci = math.factorial(i) // math.factorial(i - 4)
        for j in range(4, N_COEFFS):
            cj = math.factorial(j) // math.factorial(j - 4)
            power = i + j - 7
            Q[i, j] = ci * cj / power
    return Q


_Q_UNIT = _snap_cost_unit()


class MinSnapTrajectory:

    def __init__(self, waypoints: np.ndarray, segment_times: np.ndarray):
        wps = np.asarray(waypoints, dtype=float)
        Ts = np.asarray(segment_times, dtype=float)
        if wps.ndim != 2 or wps.shape[1] != 3:
            raise ValueError("waypoints must have shape (N+1, 3)")
        if Ts.ndim != 1 or Ts.shape[0] != wps.shape[0] - 1:
            raise ValueError("segment_times must have shape (N,) where N = len(waypoints) - 1")
        if np.any(Ts <= 0):
            raise ValueError("segment durations must be positive")

        self.waypoints = wps
        self.segment_times = Ts
        self.N = Ts.shape[0]
        self.t_breaks = np.concatenate([[0.0], np.cumsum(Ts)])
        self.total_time = float(self.t_breaks[-1])

        self._coeffs = np.stack(
            [self._solve_axis(wps[:, axis]) for axis in range(3)],
            axis=-1,
        )  # shape (N, 8, 3)

    # ---------------- QP solve per axis -------------------------------------
    def _solve_axis(self, wps_axis: np.ndarray) -> np.ndarray:
        N = self.N
        Ts = self.segment_times
        n_unknowns = N * N_COEFFS

        # Per-segment cost: ∫_0^T (d^4p/dt^4)^2 dt = Q_unit / T^7  (chain rule).
        Q = np.zeros((n_unknowns, n_unknowns))
        for i in range(N):
            Q[i * N_COEFFS:(i + 1) * N_COEFFS,
              i * N_COEFFS:(i + 1) * N_COEFFS] = _Q_UNIT / (Ts[i] ** 7)

        rows, b = [], []

        def emit(seg_idx: int, basis: np.ndarray, value: float):
            row = np.zeros(n_unknowns)
            row[seg_idx * N_COEFFS:(seg_idx + 1) * N_COEFFS] = basis
            rows.append(row)
            b.append(value)

        # Position at each segment start.
        for i in range(N):
            emit(i, _deriv_basis(0.0, 0), wps_axis[i])
        # Final waypoint at end of last segment.
        emit(N - 1, _deriv_basis(1.0, 0), wps_axis[N])

        # Boundary derivatives (vel, accel, jerk = 0 in physical time).
        # Physical k-th deriv at s = (1/T^k) * p^(k)(s); demanding zero means
        # the s-domain row is sufficient on its own (T^k just scales it).
        for k in (1, 2, 3):
            emit(0, _deriv_basis(0.0, k), 0.0)
            emit(N - 1, _deriv_basis(1.0, k), 0.0)

        # Internal C^6 continuity in *physical* time:
        #     (1/T_i^k) * p_i^(k)(s=1) = (1/T_{i+1}^k) * p_{i+1}^(k)(s=0)
        for i in range(N - 1):
            for k in range(1, 7):
                row = np.zeros(n_unknowns)
                row[i       * N_COEFFS:(i + 1) * N_COEFFS] =  _deriv_basis(1.0, k) / (Ts[i]     ** k)
                row[(i + 1) * N_COEFFS:(i + 2) * N_COEFFS] = -_deriv_basis(0.0, k) / (Ts[i + 1] ** k)
                rows.append(row)
                b.append(0.0)

        A = np.asarray(rows)
        b = np.asarray(b)

        m = A.shape[0]
        kkt = np.block([[Q, A.T              ],
                        [A, np.zeros((m, m))]])
        rhs = np.concatenate([np.zeros(n_unknowns), b])
        sol = np.linalg.solve(kkt, rhs)
        return sol[:n_unknowns].reshape(N, N_COEFFS)

    # ---------------- Evaluation --------------------------------------------
    def _segment_index(self, t: float) -> tuple[int, float, float]:
        t = max(0.0, min(t, self.total_time))
        idx = int(np.searchsorted(self.t_breaks, t, side="right") - 1)
        idx = min(max(idx, 0), self.N - 1)
        T_i = self.segment_times[idx]
        s = (t - self.t_breaks[idx]) / T_i
        return idx, s, T_i

    def __call__(self, t: float, max_deriv: int = 2):
        """Return (pos, vel, accel, ...) up to ``max_deriv`` (capped at snap)."""
        max_deriv = max(0, min(max_deriv, 4))
        idx, s, T_i = self._segment_index(float(t))
        coeffs_seg = self._coeffs[idx]  # (8, 3)

        outputs = []
        for k in range(max_deriv + 1):
            basis = _deriv_basis(s, k)
            scale = 1.0 / (T_i ** k) if k > 0 else 1.0
            outputs.append(scale * (basis @ coeffs_seg))  # (3,)
        return tuple(outputs)

    def sample(self, t_grid: np.ndarray, max_deriv: int = 2) -> tuple[np.ndarray, ...]:
        """Vectorised evaluation over a time grid."""
        t_grid = np.asarray(t_grid, dtype=float)
        out = [np.zeros((t_grid.size, 3)) for _ in range(max_deriv + 1)]
        for i, t in enumerate(t_grid):
            vals = self.__call__(t, max_deriv=max_deriv)
            for k, v in enumerate(vals):
                out[k][i] = v
        return tuple(out)
