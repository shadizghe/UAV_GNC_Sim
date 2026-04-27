"""
Streamlit dashboard for the quadrotor flight-control simulator.

Launch from the project root:

    streamlit run app.py

Sidebar: tune gains, edit waypoints, configure wind / noise, re-run.
Main:    live metrics, interactive 3D trajectory with replay slider,
         and time-series plots for altitude, tracking error, attitude,
         control effort, and disturbance.
"""

from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from src.dynamics import QuadrotorModel, QuadrotorParams
from src.control import AttitudeController, PositionController
from src.guidance import WaypointManager
from src.disturbances import WindModel, SensorNoise
from src.simulation import Simulator
from src.utils import compute_performance_metrics, euler_to_rotmat
from src.safety import CylinderZone, check_geofence
from src.analysis import MonteCarloConfig, run_monte_carlo, circular_error_probable
from src.threats import EnemyDrone, ThreatManager
from src.estimation import PositionEKF
from src.guidance import list_presets, get_preset

import plotly.io as pio


# ---------------------------------------------------------------------- #
# Draggable 3D waypoint editor (vanilla Three.js custom component)
# ---------------------------------------------------------------------- #
_FRONTEND_DIR = (Path(__file__).parent / "frontend").resolve()
_waypoint_editor_3d = components.declare_component(
    "waypoint_editor_3d",
    path=str(_FRONTEND_DIR),
)

_TACTICAL_DIR = (Path(__file__).parent / "frontend_tactical").resolve()
_tactical_map = components.declare_component(
    "tactical_map",
    path=str(_TACTICAL_DIR),
)


def waypoint_editor_3d(waypoints: list[list[float]], key: str = "wp3d"):
    """Render the Three.js-based draggable waypoint editor.

    Parameters
    ----------
    waypoints : list[[x, y, z]]
        Initial waypoint positions in the sim ENU frame.
    key : str
        Streamlit widget key.

    Returns
    -------
    list[[x, y, z]] | None
        Updated waypoints after user interaction, or None on first render.
    """
    return _waypoint_editor_3d(
        waypoints=waypoints,
        key=key,
        default=None,
    )


def tactical_map(waypoints, flown, zones, vehicle, enemies=None,
                 timeline=None, vehicle_track=None, key: str = "tac"):
    """Canvas tactical map with playback + draggable entities.

    Parameters
    ----------
    waypoints : list[[x, y, z]]
    flown     : list[[x, y, z]]   subsampled ownship trajectory
    zones     : list[dict]        no-fly / threat cylinders
    vehicle   : dict              {x, y, z, yaw} — final pose
    enemies   : list[dict]        each may include "track" of [x,y,heading]
    timeline  : list[float]       subsampled time (seconds) matching flown
    vehicle_track : list[dict]    [{x,y,z,yaw}, ...] matching timeline
    key       : Streamlit widget key.

    Returns
    -------
    dict | None
        ``{"waypoints": [...], "enemies": [...], "zones": [...]}`` after the
        user dragged/added/removed any entity, or None on first render.
    """
    return _tactical_map(
        waypoints=waypoints,
        flown=flown,
        zones=zones,
        vehicle=vehicle,
        enemies=enemies or [],
        timeline=timeline or [],
        vehicle_track=vehicle_track or [],
        key=key,
        default=None,
    )


# ====================================================================== #
# Theme palette (single source of truth for all colours)
# ====================================================================== #
PALETTE = {
    "bg":         "#0a0e1a",
    "panel":      "#141a2e",
    "panel_soft": "#1b2238",
    "grid":       "rgba(120, 160, 200, 0.12)",
    "axis":       "rgba(140, 180, 220, 0.35)",
    "text":       "#e1e8f0",
    "muted":      "#8aa0b8",
    "cyan":       "#00d4ff",
    "pink":       "#ff4081",
    "amber":      "#ffc107",
    "green":      "#2ecc71",
    "violet":     "#b388ff",
    "red":        "#ff5252",
    "shadow":     "rgba(0, 0, 0, 0.55)",
}

# Custom plotly template -- applied to every figure below.
pio.templates["gnc"] = go.layout.Template(
    layout=go.Layout(
        paper_bgcolor=PALETTE["bg"],
        plot_bgcolor=PALETTE["panel"],
        font=dict(family="Inter, Segoe UI, Helvetica, Arial",
                  size=13, color=PALETTE["text"]),
        colorway=[PALETTE["cyan"], PALETTE["pink"], PALETTE["amber"],
                  PALETTE["green"], PALETTE["violet"], PALETTE["red"]],
        xaxis=dict(gridcolor=PALETTE["grid"], zerolinecolor=PALETTE["axis"],
                   linecolor=PALETTE["axis"]),
        yaxis=dict(gridcolor=PALETTE["grid"], zerolinecolor=PALETTE["axis"],
                   linecolor=PALETTE["axis"]),
        legend=dict(bgcolor="rgba(0,0,0,0)", bordercolor="rgba(0,0,0,0)"),
        scene=dict(
            xaxis=dict(backgroundcolor=PALETTE["bg"],
                       gridcolor=PALETTE["grid"], color=PALETTE["muted"]),
            yaxis=dict(backgroundcolor=PALETTE["bg"],
                       gridcolor=PALETTE["grid"], color=PALETTE["muted"]),
            zaxis=dict(backgroundcolor=PALETTE["bg"],
                       gridcolor=PALETTE["grid"], color=PALETTE["muted"]),
        ),
    )
)
pio.templates.default = "plotly_dark+gnc"


# ====================================================================== #
# Geofence rendering helpers (used by both 2D map and 3D scene)
# ====================================================================== #
def zone_color(z: CylinderZone, alpha: float = 0.35) -> str:
    """Map zone kind to fill colour."""
    base = PALETTE["red"] if z.kind == "no_fly" else PALETTE["amber"]
    rgb = tuple(int(base[i:i + 2], 16) for i in (1, 3, 5))
    return f"rgba({rgb[0]},{rgb[1]},{rgb[2]},{alpha})"


def cylinder_mesh3d(z: CylinderZone, n_theta: int = 32):
    """Side surface of a vertical cylinder as a Plotly Mesh3d."""
    theta = np.linspace(0.0, 2 * np.pi, n_theta, endpoint=False)
    cos_t, sin_t = np.cos(theta), np.sin(theta)
    bot = np.column_stack([z.cx + z.radius * cos_t,
                           z.cy + z.radius * sin_t,
                           np.full_like(cos_t, z.z_min)])
    top = np.column_stack([z.cx + z.radius * cos_t,
                           z.cy + z.radius * sin_t,
                           np.full_like(cos_t, z.z_max)])
    verts = np.vstack([bot, top])
    i_idx, j_idx, k_idx = [], [], []
    n = n_theta
    for k_ in range(n):
        kp = (k_ + 1) % n
        i_idx += [k_,      k_]
        j_idx += [kp,      n + kp]
        k_idx += [n + kp,  n + k_]
    return go.Mesh3d(
        x=verts[:, 0], y=verts[:, 1], z=verts[:, 2],
        i=i_idx, j=j_idx, k=k_idx,
        color=PALETTE["red"] if z.kind == "no_fly" else PALETTE["amber"],
        opacity=0.18,
        flatshading=True,
        name=z.name, showlegend=False, hoverinfo="text",
        text=[f"{z.name} ({z.kind})"] * len(verts),
    )


def cylinder_top_ring(z: CylinderZone, n_theta: int = 64):
    theta = np.linspace(0.0, 2 * np.pi, n_theta)
    return go.Scatter3d(
        x=z.cx + z.radius * np.cos(theta),
        y=z.cy + z.radius * np.sin(theta),
        z=np.full_like(theta, z.z_max),
        mode="lines",
        line=dict(color=PALETTE["red"] if z.kind == "no_fly" else PALETTE["amber"],
                  width=3),
        name=z.name, showlegend=False, hoverinfo="skip",
    )


# ====================================================================== #
# Page config + typography polish
# ====================================================================== #
st.set_page_config(
    page_title="Quadrotor GNC Dashboard",
    page_icon=":helicopter:",
    layout="wide",
)

st.markdown(
    f"""
    <style>
    .main .block-container {{padding-top: 1.8rem; padding-bottom: 3rem;}}
    h1, h2, h3 {{letter-spacing: -0.01em;}}
    h1 {{font-weight: 700;}}
    .stMetric {{
        background: {PALETTE['panel']};
        border: 1px solid rgba(0, 212, 255, 0.15);
        border-radius: 10px;
        padding: 12px 14px;
    }}
    [data-testid="stMetricValue"] {{color: {PALETTE['cyan']}; font-weight: 600;}}
    [data-testid="stMetricLabel"] {{color: {PALETTE['muted']}; font-size: 0.85rem;}}
    .stSlider > div > div > div > div {{background-color: {PALETTE['cyan']};}}
    .hero-subtitle {{
        color: {PALETTE['muted']};
        font-size: 0.98rem;
        margin-top: -0.4rem;
        margin-bottom: 0.8rem;
    }}
    hr {{border-color: rgba(120,160,200,0.15);}}

    /* Sidebar polish */
    section[data-testid="stSidebar"] {{
        background: linear-gradient(180deg, {PALETTE['bg']} 0%, #0c1530 100%);
        border-right: 1px solid rgba(0, 212, 255, 0.10);
    }}
    section[data-testid="stSidebar"] .stExpander {{
        background: {PALETTE['panel']};
        border: 1px solid rgba(0, 212, 255, 0.12);
        border-radius: 8px;
        margin-bottom: 6px;
    }}
    section[data-testid="stSidebar"] summary {{
        font-weight: 600;
        letter-spacing: 0.4px;
        color: {PALETTE['text']};
    }}
    section[data-testid="stSidebar"] .stExpander summary:hover {{
        color: {PALETTE['cyan']};
    }}

    /* Mission preset card on the main page */
    .preset-card {{
        background: linear-gradient(135deg, {PALETTE['panel']} 0%, {PALETTE['panel_soft']} 100%);
        border: 1px solid rgba(0, 212, 255, 0.18);
        border-radius: 10px;
        padding: 14px 16px;
        margin-bottom: 8px;
    }}
    .preset-tag {{
        display: inline-block;
        background: rgba(0, 212, 255, 0.18);
        color: {PALETTE['cyan']};
        padding: 2px 9px;
        border-radius: 12px;
        font-size: 0.72rem;
        letter-spacing: 1.2px;
        font-weight: 600;
        margin-right: 8px;
    }}
    .preset-name {{
        font-size: 1.05rem; font-weight: 600; color: {PALETTE['text']};
    }}
    .preset-desc {{
        color: {PALETTE['muted']};
        font-size: 0.88rem;
        margin-top: 4px;
        line-height: 1.45;
    }}

    /* Data editor table styling */
    [data-testid="stDataFrame"] {{
        border: 1px solid rgba(0, 212, 255, 0.10);
        border-radius: 8px;
    }}
    [data-testid="stDataFrameResizable"] thead tr th {{
        background: {PALETTE['panel_soft']} !important;
        color: {PALETTE['cyan']} !important;
        font-weight: 600 !important;
        letter-spacing: 0.3px;
    }}
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    f"<h1 style='color:{PALETTE['text']};'>"
    "Quadrotor Flight Control &amp; Waypoint Navigation</h1>",
    unsafe_allow_html=True,
)
st.markdown(
    "<div class='hero-subtitle'>"
    "Interactive GNC simulation — tune the cascaded PID, fly a custom "
    "mission plan, and observe closed-loop performance under wind gusts "
    "and sensor noise."
    "</div>",
    unsafe_allow_html=True,
)
st.divider()


# ====================================================================== #
# Default state seeding (presets + tables)
# ====================================================================== #
_PRESETS = list_presets()
_PRESET_LABELS = [p["label"] for p in _PRESETS]
_DEFAULT_PRESET = _PRESETS[0]


def _seed_geofence_df():
    return pd.DataFrame(_DEFAULT_PRESET["zones"])


def _seed_enemy_df():
    return pd.DataFrame(_DEFAULT_PRESET["enemies"])


if "geofence_df" not in st.session_state:
    st.session_state.geofence_df = _seed_geofence_df()
if "enemy_df" not in st.session_state:
    st.session_state.enemy_df = _seed_enemy_df()
if "waypoints" not in st.session_state:
    st.session_state.waypoints = [list(w) for w in _DEFAULT_PRESET["waypoints"]]
if "yaws" not in st.session_state:
    st.session_state.yaws = list(_DEFAULT_PRESET["yaws_deg"])
if "current_preset" not in st.session_state:
    st.session_state.current_preset = _DEFAULT_PRESET["label"]
if "preset_duration" not in st.session_state:
    st.session_state.preset_duration = float(_DEFAULT_PRESET["duration_s"])
if "enable_threats" not in st.session_state:
    st.session_state.enable_threats = bool(_DEFAULT_PRESET.get("enable_threats", True))
if "enable_geofence" not in st.session_state:
    st.session_state.enable_geofence = bool(_DEFAULT_PRESET.get("enable_geofence", True))


def _apply_preset(label: str) -> None:
    """Push a preset's content into session_state for the next rerun."""
    p = get_preset(label)
    if p is None:
        return
    st.session_state.waypoints = [list(w) for w in p["waypoints"]]
    st.session_state.yaws = list(p["yaws_deg"])
    st.session_state.geofence_df = pd.DataFrame(p["zones"]) if p["zones"] else \
        pd.DataFrame(columns=["name", "cx", "cy", "r", "z_min", "z_max", "kind"])
    st.session_state.enemy_df = pd.DataFrame(p["enemies"]) if p["enemies"] else \
        pd.DataFrame(columns=["name", "x", "y", "z", "behavior", "speed",
                              "det_r", "leth_r", "orbit_cx", "orbit_cy", "orbit_r"])
    st.session_state.preset_duration = float(p["duration_s"])
    st.session_state.enable_threats = bool(p.get("enable_threats", True))
    st.session_state.enable_geofence = bool(p.get("enable_geofence", True))
    st.session_state.current_preset = label
    # Force a fresh sim run on the new geometry.
    st.session_state.pop("last_result", None)


# ====================================================================== #
# Sidebar controls
# ====================================================================== #
with st.sidebar:
    st.markdown(
        f"<div style='font-size:0.78rem;letter-spacing:1.5px;color:{PALETTE['cyan']};"
        "font-weight:600;margin-bottom:6px;'>FLIGHT CONFIGURATION</div>",
        unsafe_allow_html=True,
    )

    # ---- Mission preset --------------------------------------------------
    with st.expander("Mission Scenario", expanded=True):
        sel = st.selectbox(
            "Preset", _PRESET_LABELS,
            index=_PRESET_LABELS.index(st.session_state.current_preset)
                  if st.session_state.current_preset in _PRESET_LABELS else 0,
            label_visibility="collapsed",
            key="preset_selector",
        )
        cur = next((p for p in _PRESETS if p["label"] == sel), _DEFAULT_PRESET)
        st.markdown(
            f"<div style='font-size:0.82rem;color:{PALETTE['muted']};margin-top:-4px'>"
            f"<b style='color:{PALETTE['cyan']};letter-spacing:1px;'>{cur['tag'].upper()}</b>"
            f" &nbsp;·&nbsp; {len(cur['waypoints'])} wpt · {len(cur['zones'])} zone · "
            f"{len(cur['enemies'])} enemy</div>"
            f"<div style='font-size:0.78rem;color:{PALETTE['muted']};margin-top:6px;"
            f"line-height:1.4;'>{cur['description']}</div>",
            unsafe_allow_html=True,
        )
        if st.button("Load scenario", type="primary", width="stretch",
                     disabled=(sel == st.session_state.current_preset)):
            _apply_preset(sel)
            st.rerun()
        if sel == st.session_state.current_preset:
            st.caption(f":material/check_circle: Active — *{sel}*")

    # ---- Simulation ------------------------------------------------------
    with st.expander("Simulation", expanded=False):
        dt      = st.number_input("Timestep dt [s]", 0.001, 0.05, 0.01, 0.001,
                                  format="%.3f",
                                  help="Integration step. Smaller = more accurate, slower.")
        t_final = st.slider("Duration [s]", 10.0, 120.0,
                            float(st.session_state.preset_duration), 1.0)
        seed    = st.number_input("RNG seed", 0, 10_000, 42, 1,
                                  help="Drives wind gusts + sensor noise.")
        st.markdown("**Initial state**")
        ic1, ic2, ic3 = st.columns(3)
        x0 = ic1.number_input("x₀ [m]", -10.0, 10.0, 0.0, 0.5,
                              label_visibility="visible")
        y0 = ic2.number_input("y₀ [m]", -10.0, 10.0, 0.0, 0.5)
        z0 = ic3.number_input("z₀ [m]",   0.0, 10.0, 0.0, 0.5)

    # ---- Vehicle + Controllers ------------------------------------------
    with st.expander("Vehicle & Controllers", expanded=False):
        mass = st.slider("Mass [kg]", 0.3, 5.0, 1.2, 0.1)
        st.markdown("**Position PID (x/y)**")
        kp_xy = st.slider("kp", 0.0, 5.0, 1.2, 0.05, key="kp_xy")
        ki_xy = st.slider("ki", 0.0, 1.0, 0.0, 0.01, key="ki_xy")
        kd_xy = st.slider("kd", 0.0, 5.0, 1.6, 0.05, key="kd_xy")
        tilt_deg = st.slider("Max tilt [deg]", 5.0, 40.0, 25.0, 1.0)
        st.markdown("**Altitude PID (z)**")
        kp_z = st.slider("kp ", 0.0, 10.0, 4.0, 0.1, key="kp_z")
        ki_z = st.slider("ki ", 0.0, 5.0, 1.0, 0.1, key="ki_z")
        kd_z = st.slider("kd ", 0.0, 10.0, 3.0, 0.1, key="kd_z")
        st.markdown("**Attitude PID**")
        kp_att = st.slider("kp roll/pitch", 0.5, 15.0, 6.0, 0.1)
        kd_att = st.slider("kd roll/pitch", 0.0,  5.0, 1.2, 0.05)
        kp_yaw = st.slider("kp yaw", 0.5, 10.0, 4.0, 0.1)
        kd_yaw = st.slider("kd yaw", 0.0,  5.0, 0.8, 0.05)

    # ---- Environment ----------------------------------------------------
    with st.expander("Environment", expanded=False):
        enable_wind  = st.checkbox("Wind disturbance", True,
                                   help="Constant mean wind plus first-order gusts.")
        wc1, wc2, wc3 = st.columns(3)
        wx = wc1.number_input("wx [m/s]", -5.0, 5.0, 1.5, 0.1)
        wy = wc2.number_input("wy [m/s]", -5.0, 5.0, 0.5, 0.1)
        wz = wc3.number_input("wz [m/s]", -2.0, 2.0, 0.0, 0.1)
        gust = st.slider("Gust σ [m/s]", 0.0, 3.0, 0.6, 0.1)

        st.markdown("**Sensor noise**")
        enable_noise = st.checkbox("Enable sensor noise", True)
        pos_std      = st.slider("Position σ [m]",   0.0, 0.2, 0.05, 0.005)
        att_std_deg  = st.slider("Attitude σ [deg]", 0.0, 2.0, 0.3,  0.05)

    # ---- Estimator -------------------------------------------------------
    with st.expander("State Estimation (EKF)", expanded=False):
        enable_ekf = st.checkbox(
            "Enable EKF (6-state CV)", True,
            help="Constant-velocity Kalman filter fuses noisy GPS-style "
                 "position fixes; the controller uses the smoothed estimate."
        )
        ekf_jerk = st.slider(
            "Process noise σ_jerk", 0.5, 10.0, 3.0, 0.1,
            help="Higher = filter trusts measurements more; lower = trusts model.",
            disabled=not enable_ekf,
        )
        st.caption(
            ":material/info: With the EKF on, the position controller "
            "consumes the *estimated* state. With it off, raw noisy "
            "measurements are fed directly into the controller — useful "
            "for visualising the noise penalty."
        )

    # ---- Geofence --------------------------------------------------------
    with st.expander("Geofence Zones", expanded=False):
        enable_geofence = st.checkbox(
            "Enable geofence checking",
            key="enable_geofence",
        )
        st.caption("Cylindrical no-fly + threat volumes. "
                   "Drag the centre or ring on the tactical map to reposition.")
        gz_df = st.data_editor(
            st.session_state.geofence_df,
            num_rows="dynamic",
            width="stretch",
            key="geofence_editor",
            column_config={
                "name":  st.column_config.TextColumn("Name",
                                                    help="Zone identifier"),
                "kind":  st.column_config.SelectboxColumn(
                    "Type", options=["no_fly", "threat"], required=True,
                    help="no_fly = hard restriction, threat = soft (warning)"),
                "cx":    st.column_config.NumberColumn("cx [m]", format="%.2f"),
                "cy":    st.column_config.NumberColumn("cy [m]", format="%.2f"),
                "r":     st.column_config.NumberColumn("Radius [m]", format="%.2f",
                                                       min_value=0.1),
                "z_min": st.column_config.NumberColumn("z_min [m]", format="%.2f"),
                "z_max": st.column_config.NumberColumn("z_max [m]", format="%.2f"),
            },
            column_order=["name", "kind", "cx", "cy", "r", "z_min", "z_max"],
            hide_index=True,
        )
        st.session_state.geofence_df = gz_df

    # ---- Enemy drones ----------------------------------------------------
    with st.expander("Enemy Drones", expanded=False):
        enable_threats = st.checkbox(
            "Enable enemy drones",
            key="enable_threats",
        )
        react_threats  = st.checkbox(
            "Ownship reacts (evasion)", True,
            help="When on, the flight controller deflects around any threat "
                 "inside its detection radius.")
        st.caption("Up to 3 kinematic threats — patrol (orbit), loiter (hover), "
                   "or pursue (chase ownship).")
        en_df = st.data_editor(
            st.session_state.enemy_df,
            num_rows="dynamic",
            width="stretch",
            key="enemy_editor",
            column_config={
                "name":     st.column_config.TextColumn("Callsign"),
                "behavior": st.column_config.SelectboxColumn(
                    "Behavior", options=["patrol", "loiter", "pursue"],
                    required=True,
                    help="patrol = orbit a centre; loiter = hover; pursue = chase"),
                "x":        st.column_config.NumberColumn("x [m]", format="%.2f"),
                "y":        st.column_config.NumberColumn("y [m]", format="%.2f"),
                "z":        st.column_config.NumberColumn("z [m]", format="%.2f"),
                "speed":    st.column_config.NumberColumn("Speed [m/s]",
                                                          format="%.2f", min_value=0.0),
                "det_r":    st.column_config.NumberColumn("Detect [m]",
                                                          format="%.2f", min_value=0.0,
                                                          help="Detection radius — ownship reacts inside this"),
                "leth_r":   st.column_config.NumberColumn("Lethal [m]",
                                                          format="%.2f", min_value=0.0,
                                                          help="Below this range = intercept counted"),
                "orbit_cx": st.column_config.NumberColumn("Orbit cx",
                                                          format="%.2f"),
                "orbit_cy": st.column_config.NumberColumn("Orbit cy",
                                                          format="%.2f"),
                "orbit_r":  st.column_config.NumberColumn("Orbit r",
                                                          format="%.2f", min_value=0.0),
            },
            column_order=["name", "behavior", "x", "y", "z", "speed",
                          "det_r", "leth_r", "orbit_cx", "orbit_cy", "orbit_r"],
            hide_index=True,
        )
        if len(en_df) > 3:
            en_df = en_df.iloc[:3].reset_index(drop=True)
        st.session_state.enemy_df = en_df

    # ---- Monte Carlo -----------------------------------------------------
    with st.expander("Monte Carlo Dispersion", expanded=False):
        mc_n_runs = st.slider("Number of runs", 5, 200, 30, 5)
        mc_wind_jitter = st.slider("Wind perturbation [±%]", 0, 100, 40, 5) / 100.0
        mc_mass_jitter = st.slider("Mass perturbation [±%]",  0,  20,  5, 1) / 100.0
        mc_imu_bias    = st.slider("IMU bias σ [deg]",        0.0, 3.0, 0.5, 0.1)
        mc_start_jit   = st.slider("Start XY jitter [±m]",    0.0, 2.0, 0.3, 0.1)
        run_mc_button  = st.button("Run dispersion sweep",
                                   width="stretch", type="secondary")
        if st.session_state.get("mc_result") is not None:
            if st.button("Clear dispersion results", width="stretch"):
                st.session_state.mc_result = None
                st.rerun()


# ====================================================================== #
# Build active geofence zones from the editor
# ====================================================================== #
def _zones_from_df(df: pd.DataFrame) -> list[CylinderZone]:
    zones: list[CylinderZone] = []
    if df is None or len(df) == 0:
        return zones
    for _, row in df.iterrows():
        try:
            zones.append(CylinderZone(
                name=str(row["name"]),
                cx=float(row["cx"]), cy=float(row["cy"]),
                radius=float(row["r"]),
                z_min=float(row["z_min"]), z_max=float(row["z_max"]),
                kind=str(row["kind"]) if str(row["kind"]) in ("no_fly", "threat") else "no_fly",
            ))
        except (KeyError, ValueError, TypeError):
            continue
    return zones


geofence_zones = _zones_from_df(st.session_state.geofence_df) if enable_geofence else []


def _enemies_from_df(df: pd.DataFrame) -> list[EnemyDrone]:
    enemies: list[EnemyDrone] = []
    if df is None or len(df) == 0:
        return enemies
    for _, row in df.iterrows():
        try:
            behavior = str(row["behavior"])
            if behavior not in ("patrol", "loiter", "pursue"):
                behavior = "loiter"
            enemies.append(EnemyDrone(
                name=str(row["name"]),
                x=float(row["x"]), y=float(row["y"]), z=float(row["z"]),
                speed=float(row["speed"]),
                detection_radius=float(row["det_r"]),
                lethal_radius=float(row["leth_r"]),
                behavior=behavior,
                orbit_cx=float(row.get("orbit_cx", 0.0)),
                orbit_cy=float(row.get("orbit_cy", 0.0)),
                orbit_r=float(row.get("orbit_r", 0.0)),
            ))
        except (KeyError, ValueError, TypeError):
            continue
    return enemies


active_enemies = (_enemies_from_df(st.session_state.enemy_df)
                  if enable_threats else [])


# ====================================================================== #
# Waypoint editor (main area)
# ====================================================================== #
st.subheader("Mission Plan")

# ---- Section header: 3D editor ---------------------------------------- #
_h_l, _h_c, _h_r = st.columns([1, 6, 3])
with _h_c:
    st.markdown(
        f"""
        <div style="display:flex;align-items:center;justify-content:space-between;
                    padding:10px 14px;margin-top:4px;
                    background:linear-gradient(90deg,{PALETTE['panel']} 0%,
                                                       {PALETTE['panel_soft']} 100%);
                    border:1px solid rgba(0,212,255,0.18);
                    border-radius:10px;">
          <div style="display:flex;align-items:center;gap:10px;">
            <span style="display:inline-block;width:5px;height:20px;
                         background:{PALETTE['cyan']};border-radius:2px;"></span>
            <span style="font-size:1.0rem;font-weight:600;color:{PALETTE['text']};
                         letter-spacing:0.3px;">3D Draggable Editor</span>
          </div>
          <div style="display:flex;gap:6px;font-size:0.66rem;letter-spacing:1.2px;
                      font-weight:600;">
            <span style="background:rgba(0,212,255,0.14);color:{PALETTE['cyan']};
                         padding:3px 9px;border-radius:11px;">CLICK · DRAG</span>
            <span style="background:rgba(255,193,7,0.14);color:{PALETTE['amber']};
                         padding:3px 9px;border-radius:11px;">SHIFT-CLICK · ADD</span>
            <span style="background:rgba(255,82,82,0.14);color:{PALETTE['red']};
                         padding:3px 9px;border-radius:11px;">DEL · REMOVE</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

# ---- 3D editor (full width — no side padding to avoid dead strips) --- #
edited_3d = waypoint_editor_3d(st.session_state.waypoints, key="wp3d")
if edited_3d is not None:
    clean = [[float(v) for v in p] for p in edited_3d]
    if clean != st.session_state.waypoints:
        n = len(clean)
        if n > len(st.session_state.yaws):
            st.session_state.yaws = st.session_state.yaws + [0.0] * (
                n - len(st.session_state.yaws)
            )
        else:
            st.session_state.yaws = st.session_state.yaws[:n]
        st.session_state.waypoints = clean
        st.rerun()

# ---- Section header: waypoint table ----------------------------------- #
_t_l, _t_c, _t_r = st.columns([1, 6, 3])
with _t_c:
    st.markdown(
        f"""
        <div style="display:flex;align-items:center;justify-content:space-between;
                    padding:10px 14px;
                    background:linear-gradient(90deg,{PALETTE['panel']} 0%,
                                                       {PALETTE['panel_soft']} 100%);
                    border:1px solid rgba(0,212,255,0.18);
                    border-radius:10px;">
          <div style="display:flex;align-items:center;gap:10px;">
            <span style="display:inline-block;width:5px;height:20px;
                         background:{PALETTE['amber']};border-radius:2px;"></span>
            <span style="font-size:1.0rem;font-weight:600;color:{PALETTE['text']};
                         letter-spacing:0.3px;">Waypoint Table</span>
          </div>
          <div style="font-size:0.72rem;color:{PALETTE['muted']};">
            Editable: <b style="color:{PALETTE['cyan']};">X · Y · Z · yaw</b>
            &nbsp;·&nbsp;
            Computed: <b style="color:{PALETTE['violet']};">Leg · Brg · Δz · ETA</b>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

# Centred wide table.
_pad_l, coltab, _pad_r = st.columns([1, 6, 1], gap="medium")

with coltab:
    # ---- Precompute leg distances, bearings, ETAs ---------------------- #
    _wps_arr = np.asarray(st.session_state.waypoints, dtype=float)
    _yaws_arr = np.asarray(st.session_state.yaws, dtype=float)
    _n_wps = len(_wps_arr)
    _legs_xy = np.zeros(_n_wps)
    _legs_3d = np.zeros(_n_wps)
    _dz      = np.zeros(_n_wps)
    _brg     = np.full(_n_wps, np.nan)
    if _n_wps > 1:
        diffs = _wps_arr[1:] - _wps_arr[:-1]
        _legs_xy[1:] = np.linalg.norm(diffs[:, 0:2], axis=1)
        _legs_3d[1:] = np.linalg.norm(diffs, axis=1)
        _dz[1:]      = diffs[:, 2]
        # Bearing in nav convention: 0° = +Y (north), 90° = +X (east)
        _brg[1:] = (np.degrees(np.arctan2(diffs[:, 0], diffs[:, 1])) + 360.0) % 360.0
    _CRUISE_SPEED = 2.0  # m/s — rough nominal for ETA estimate
    _eta = np.cumsum(_legs_3d / _CRUISE_SPEED)

    _total_dist = float(_legs_3d.sum())
    _max_alt    = float(_wps_arr[:, 2].max()) if _n_wps else 0.0
    _min_alt    = float(_wps_arr[:, 2].min()) if _n_wps else 0.0
    _eta_total  = float(_eta[-1]) if _n_wps else 0.0

    # ---- Summary strip above the table -------------------------------- #
    st.markdown(
        f"""
        <div style="display:flex;gap:8px;margin-bottom:8px;flex-wrap:wrap;">
          <div style="background:{PALETTE['panel']};border:1px solid rgba(0,212,255,0.18);
               border-radius:8px;padding:6px 12px;flex:1;min-width:90px;">
            <div style="font-size:0.68rem;letter-spacing:1.2px;color:{PALETTE['muted']};">WAYPOINTS</div>
            <div style="font-size:1.1rem;color:{PALETTE['cyan']};font-weight:600;">{_n_wps}</div>
          </div>
          <div style="background:{PALETTE['panel']};border:1px solid rgba(0,212,255,0.18);
               border-radius:8px;padding:6px 12px;flex:1;min-width:90px;">
            <div style="font-size:0.68rem;letter-spacing:1.2px;color:{PALETTE['muted']};">TOTAL PATH</div>
            <div style="font-size:1.1rem;color:{PALETTE['cyan']};font-weight:600;">{_total_dist:.1f} m</div>
          </div>
          <div style="background:{PALETTE['panel']};border:1px solid rgba(0,212,255,0.18);
               border-radius:8px;padding:6px 12px;flex:1;min-width:90px;">
            <div style="font-size:0.68rem;letter-spacing:1.2px;color:{PALETTE['muted']};">ALT RANGE</div>
            <div style="font-size:1.1rem;color:{PALETTE['cyan']};font-weight:600;">
              {_min_alt:.1f}–{_max_alt:.1f} m</div>
          </div>
          <div style="background:{PALETTE['panel']};border:1px solid rgba(0,212,255,0.18);
               border-radius:8px;padding:6px 12px;flex:1;min-width:90px;">
            <div style="font-size:0.68rem;letter-spacing:1.2px;color:{PALETTE['muted']};">ETA @ {_CRUISE_SPEED:.0f} M/S</div>
            <div style="font-size:1.1rem;color:{PALETTE['cyan']};font-weight:600;">{_eta_total:.1f} s</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        f"<div style='color:{PALETTE['muted']};font-size:0.78rem;margin-bottom:6px;'>"
        "Editable: <b style='color:#e1e8f0'>X · Y · Z · Yaw</b>. "
        "Computed columns (Leg, Brg, Δz, ETA) update live after Run."
        "</div>",
        unsafe_allow_html=True,
    )

    # ---- Build the rich dataframe ------------------------------------- #
    _wp_ids = [f"WPT-{i + 1}" for i in range(_n_wps)]
    _df_source = pd.DataFrame({
        "WPT":     _wp_ids,
        "x [m]":   _wps_arr[:, 0] if _n_wps else [],
        "y [m]":   _wps_arr[:, 1] if _n_wps else [],
        "z [m]":   _wps_arr[:, 2] if _n_wps else [],
        "yaw [°]": _yaws_arr,
        "Leg [m]": _legs_3d,
        "Brg [°]": _brg,
        "Δz [m]":  _dz,
        "ETA [s]": _eta,
    })

    wp_df = st.data_editor(
        _df_source,
        num_rows="dynamic",
        width="stretch",
        key="wp_editor",
        hide_index=True,
        column_config={
            "WPT": st.column_config.TextColumn(
                "WPT", disabled=True, width="small",
                help="Waypoint identifier — auto-numbered in the order flown."),
            "x [m]": st.column_config.NumberColumn(
                "x [m]", format="%.2f", step=0.1,
                help="East coordinate (ENU)."),
            "y [m]": st.column_config.NumberColumn(
                "y [m]", format="%.2f", step=0.1,
                help="North coordinate (ENU)."),
            "z [m]": st.column_config.NumberColumn(
                "z [m]", format="%.2f", step=0.1, min_value=0.0,
                help="Altitude above ground."),
            "yaw [°]": st.column_config.NumberColumn(
                "yaw [°]", format="%.1f", step=5.0,
                min_value=-180.0, max_value=360.0,
                help="Heading setpoint at this waypoint (0° = +X / east)."),
            "Leg [m]": st.column_config.NumberColumn(
                "Leg [m]", format="%.2f", disabled=True,
                help="3D distance from the previous waypoint."),
            "Brg [°]": st.column_config.NumberColumn(
                "Brg [°]", format="%.0f", disabled=True,
                help="Compass bearing from previous waypoint (0=N, 90=E)."),
            "Δz [m]": st.column_config.NumberColumn(
                "Δz [m]", format="%+.2f", disabled=True,
                help="Altitude change from previous waypoint."),
            "ETA [s]": st.column_config.NumberColumn(
                "ETA [s]", format="%.1f", disabled=True,
                help=f"Cumulative time at nominal {_CRUISE_SPEED:.0f} m/s cruise."),
        },
        column_order=["WPT", "x [m]", "y [m]", "z [m]", "yaw [°]",
                      "Leg [m]", "Brg [°]", "Δz [m]", "ETA [s]"],
    )
    new_wps = wp_df[["x [m]", "y [m]", "z [m]"]].to_numpy().tolist()
    new_yaws = wp_df["yaw [°]"].tolist()
    if (new_wps != st.session_state.waypoints
            or new_yaws != st.session_state.yaws):
        st.session_state.waypoints = [[float(v) for v in p] for p in new_wps]
        st.session_state.yaws = [float(y) for y in new_yaws]
        st.rerun()

    # ---- Glossary expander (collapsed by default) ------------------- #
    with st.expander("📖  Column legend & explanations", expanded=False):
        gc1, gc2 = st.columns(2)
        with gc1:
            st.markdown(
                f"""
**:blue[Editable columns]**

- **WPT** — Waypoint identifier, auto-numbered in flight order.
- **x · y · z [m]** — Position in ENU frame.
  - **X** = east, **Y** = north, **Z** = up (altitude above ground).
- **yaw [°]** — Heading setpoint at this waypoint.
  - **0°** faces +X (east); positive yaw rotates the nose right.
                """
            )
        with gc2:
            st.markdown(
                f"""
**:violet[Computed columns (read-only)]**

- **Leg [m]** — 3D distance from the previous waypoint.
- **Brg [°]** — Compass bearing of the leg.
  - 0° = N, 90° = E, 180° = S, 270° = W.
- **Δz [m]** — Altitude change. **+** = climb, **−** = descent.
- **ETA [s]** — Cumulative flight time at nominal **{_CRUISE_SPEED:.0f} m/s** cruise.
  - Real time depends on PID tuning + wind.
                """
            )
        st.caption(
            "💡 Add or remove rows from the bottom of the table, or "
            "shift-click on the 3D editor / tactical map to drop a new "
            "waypoint. The table reflows automatically."
        )

# ---- Acceptance radius + Run row -------------------------------------- #
_r_l, _r_c, _r_r = st.columns([1, 6, 1])
with _r_c:
    rad_col, btn_col = st.columns([3, 2], gap="medium")
    with rad_col:
        accept_radius = st.slider(
            "Waypoint acceptance radius [m]", 0.1, 2.0, 0.35, 0.05,
            help="Ownship marks a waypoint as 'reached' once it comes within "
                 "this radius. Smaller = tighter tracking.",
        )
    with btn_col:
        st.markdown("<div style='height:28px;'></div>", unsafe_allow_html=True)
        run_button = st.button("▶ Run simulation", type="primary",
                               width="stretch")


# ====================================================================== #
# Simulation runner (cached)
# ====================================================================== #
@st.cache_data(show_spinner="Running closed-loop simulation...")
def run_sim(params_tuple) -> dict:
    (dt, t_final, seed, x0, y0, z0, mass,
     kp_xy, ki_xy, kd_xy, tilt_deg,
     kp_z, ki_z, kd_z,
     kp_att, kd_att, kp_yaw, kd_yaw,
     enable_wind, wx, wy, wz, gust,
     enable_noise, pos_std, att_std_deg,
     wp_tuple, yaw_tuple, accept_radius,
     enemy_tuple, react_threats_flag,
     enable_ekf_flag, ekf_jerk_val) = params_tuple

    waypoints = np.array(wp_tuple, dtype=float)
    yaws      = np.deg2rad(np.array(yaw_tuple, dtype=float))

    qp = QuadrotorParams(mass=mass)
    model = QuadrotorModel(qp)

    pos_ctrl = PositionController(
        mass=qp.mass, g=qp.g,
        xy_gains=(kp_xy, ki_xy, kd_xy),
        z_gains=(kp_z, ki_z, kd_z),
        max_tilt_deg=tilt_deg,
        thrust_limits=(qp.thrust_min, qp.thrust_max),
    )
    att_ctrl = AttitudeController(
        roll_gains=(kp_att, 0.1, kd_att),
        pitch_gains=(kp_att, 0.1, kd_att),
        yaw_gains=(kp_yaw, 0.05, kd_yaw),
        tau_limit=qp.tau_max,
    )
    wp_mgr = WaypointManager(waypoints, acceptance_radius=accept_radius,
                             yaw_setpoints=yaws)

    wind = WindModel(
        mean_wind=(wx, wy, wz),
        gust_std=(gust, gust, gust * 0.33),
        rng=np.random.default_rng(seed),
    ) if enable_wind else None

    noise = SensorNoise(
        position_std=pos_std,
        attitude_std_deg=att_std_deg,
        rng=np.random.default_rng(seed + 1),
    ) if enable_noise else None

    state0 = QuadrotorModel.initial_state(position=(x0, y0, z0))

    enemies_run: list[EnemyDrone] = []
    for row in enemy_tuple:
        (nm, ex, ey, ez, behav, spd, det, leth,
         ocx, ocy, orr) = row
        enemies_run.append(EnemyDrone(
            name=nm, x=ex, y=ey, z=ez,
            speed=spd, detection_radius=det, lethal_radius=leth,
            behavior=behav,
            orbit_cx=ocx, orbit_cy=ocy, orbit_r=orr,
        ))
    threats = ThreatManager(enemies_run, react=react_threats_flag) if enemies_run else None

    estimator = (PositionEKF(sigma_pos=max(pos_std, 1e-3),
                             sigma_jerk=ekf_jerk_val)
                 if enable_ekf_flag else None)

    sim = Simulator(model, pos_ctrl, att_ctrl, wp_mgr,
                    wind=wind, sensor_noise=noise, threats=threats,
                    estimator=estimator,
                    dt=dt, t_final=t_final, initial_state=state0)
    result = sim.run()
    metrics = compute_performance_metrics(result)

    return {
        "t": result.t,
        "state": result.state,
        "control": result.control,
        "waypoint": result.waypoint,
        "euler_cmd": result.euler_cmd,
        "wind_force": result.wind_force,
        "waypoints": result.waypoints,
        "reached_log": result.reached_log,
        "metrics": metrics,
        "enemy_hist": result.enemy_hist,
        "threat_report": result.threat_report,
        "enemy_static":  [
            {"name": e.name, "behavior": e.behavior,
             "det_r": e.detection_radius, "leth_r": e.lethal_radius,
             "z": e.z}
            for e in enemies_run
        ],
        "meas_pos":      result.meas_pos,
        "state_est":     result.state_est,
        "pos_cov_trace": result.pos_cov_trace,
        "estimator_used": result.estimator_used,
    }


if run_button or "last_result" not in st.session_state:
    wp_array = st.session_state.waypoints
    yaw_list = st.session_state.yaws
    enemy_tuple = tuple(
        (e.name, e.x, e.y, e.z, e.behavior, e.speed,
         e.detection_radius, e.lethal_radius,
         e.orbit_cx, e.orbit_cy, e.orbit_r)
        for e in active_enemies
    )
    params_tuple = (
        dt, t_final, seed, x0, y0, z0, mass,
        kp_xy, ki_xy, kd_xy, tilt_deg,
        kp_z, ki_z, kd_z,
        kp_att, kd_att, kp_yaw, kd_yaw,
        enable_wind, wx, wy, wz, gust,
        enable_noise, pos_std, att_std_deg,
        tuple(tuple(row) for row in wp_array),
        tuple(yaw_list),
        accept_radius,
        enemy_tuple,
        bool(react_threats),
        bool(enable_ekf), float(ekf_jerk),
    )
    st.session_state.last_result = run_sim(params_tuple)

res     = st.session_state.last_result
t       = res["t"]
pos     = res["state"][:, 0:3]
euler   = res["state"][:, 6:9]
eul_cmd = res["euler_cmd"]
u       = res["control"]
wps     = res["waypoints"]
err     = pos - res["waypoint"]
metrics = res["metrics"]

geofence_report = check_geofence(t, pos, geofence_zones)

enemy_hist    = res.get("enemy_hist", np.zeros((0, 0, 4)))
threat_report = res.get("threat_report")
enemy_static  = res.get("enemy_static", [])

state_est       = res.get("state_est", np.zeros((len(t), 6)))
meas_pos        = res.get("meas_pos",  pos.copy())
pos_cov_trace   = res.get("pos_cov_trace", np.zeros(len(t)))
estimator_used  = bool(res.get("estimator_used", False))


# ====================================================================== #
# Monte Carlo factory + dispatch
# ====================================================================== #
def _mc_factory(p: dict) -> Simulator:
    """Build a Simulator from a perturbed param dict (no Streamlit cache)."""
    qp = QuadrotorParams(mass=p["mass"])
    model = QuadrotorModel(qp)
    pos_ctrl = PositionController(
        mass=qp.mass, g=qp.g,
        xy_gains=p["xy_gains"], z_gains=p["z_gains"],
        max_tilt_deg=p["tilt_deg"],
        thrust_limits=(qp.thrust_min, qp.thrust_max),
    )
    att_ctrl = AttitudeController(
        roll_gains=(p["kp_att"], 0.1, p["kd_att"]),
        pitch_gains=(p["kp_att"], 0.1, p["kd_att"]),
        yaw_gains=(p["kp_yaw"], 0.05, p["kd_yaw"]),
        tau_limit=qp.tau_max,
    )
    waypoints = np.array(p["waypoints"], dtype=float)
    yaws = np.deg2rad(np.array(p["yaws"], dtype=float))
    wp_mgr = WaypointManager(waypoints, acceptance_radius=p["accept_radius"],
                             yaw_setpoints=yaws)
    wind = WindModel(
        mean_wind=p["mean_wind"],
        gust_std=p["gust_std"],
        rng=np.random.default_rng(p["seed"]),
    ) if p.get("enable_wind", True) else None
    noise = SensorNoise(
        position_std=p["pos_std"],
        attitude_std_deg=p["att_std_deg"],
        attitude_bias_deg=p.get("attitude_bias_deg", (0.0, 0.0, 0.0)),
        rng=np.random.default_rng(p["seed"] + 7919),
    ) if p.get("enable_noise", True) else None
    state0 = QuadrotorModel.initial_state(position=(p["x0"], p["y0"], p["z0"]))
    return Simulator(model, pos_ctrl, att_ctrl, wp_mgr,
                     wind=wind, sensor_noise=noise,
                     dt=p["dt"], t_final=p["t_final"], initial_state=state0)


if run_mc_button:
    base = dict(
        dt=dt, t_final=t_final, mass=mass,
        xy_gains=(kp_xy, ki_xy, kd_xy),
        z_gains=(kp_z, ki_z, kd_z),
        tilt_deg=tilt_deg,
        kp_att=kp_att, kd_att=kd_att,
        kp_yaw=kp_yaw, kd_yaw=kd_yaw,
        x0=x0, y0=y0, z0=z0, seed=seed,
        mean_wind=(wx, wy, wz), gust_std=(gust, gust, gust * 0.33),
        enable_wind=enable_wind, enable_noise=enable_noise,
        pos_std=pos_std, att_std_deg=att_std_deg,
        waypoints=st.session_state.waypoints,
        yaws=st.session_state.yaws,
        accept_radius=accept_radius,
    )
    mc_cfg = MonteCarloConfig(
        n_runs=mc_n_runs, seed_base=int(seed),
        wind_mean_jitter=mc_wind_jitter,
        wind_extra_gust=mc_wind_jitter,
        mass_jitter=mc_mass_jitter,
        start_xy_jitter=mc_start_jit,
        imu_bias_std_deg=mc_imu_bias,
    )

    progress = st.progress(0.0, text=f"Monte Carlo: 0 / {mc_n_runs}")
    def _cb(i, n):
        progress.progress(i / n, text=f"Monte Carlo: {i} / {n}")

    st.session_state.mc_result = run_monte_carlo(
        _mc_factory, base, mc_cfg, progress_cb=_cb,
    )
    progress.empty()


# ====================================================================== #
# Performance metric cards
# ====================================================================== #
st.subheader("Performance Metrics")
c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Waypoints reached",
          f"{metrics.waypoints_reached} / {metrics.waypoints_total}")
c2.metric("Mission time",
          f"{metrics.total_mission_time:.2f} s"
          if metrics.total_mission_time is not None else "n/a")
c3.metric("RMS tracking error", f"{metrics.rms_position_error:.3f} m")
c4.metric("Final position error", f"{metrics.final_position_error:.3f} m")
c5.metric("Altitude overshoot", f"{metrics.overshoot_z * 100:.2f} %")
if enable_geofence and geofence_zones:
    c6.metric("Geofence violations",
              f"{geofence_report.total_time_in_zone:.2f} s",
              delta=f"{len(geofence_report.zones_entered)} zone(s)"
                    if geofence_report.zones_entered else "clear",
              delta_color=("inverse" if geofence_report.zones_entered else "normal"))
else:
    c6.metric("Geofence violations", "—",
              delta="disabled", delta_color="off")


# ====================================================================== #
# Threat-encounter panel
# ====================================================================== #
if threat_report is not None and enemy_hist.shape[1] > 0:
    st.subheader("Threat Analysis")
    dt_sim = float(np.median(np.diff(t))) if len(t) > 1 else 0.01
    min_rng   = threat_report.min_range
    t_det     = threat_report.time_in_detection(dt_sim)
    t_leth    = threat_report.time_in_lethal(dt_sim)
    n_hits    = threat_report.n_intercepts

    tc1, tc2, tc3, tc4 = st.columns(4)
    tc1.metric("Nearest approach", f"{min_rng:.2f} m",
               delta="intercepted" if n_hits > 0 else "stand-off",
               delta_color=("inverse" if n_hits > 0 else "normal"))
    tc2.metric("Time in detection", f"{t_det:.2f} s")
    tc3.metric("Time in lethal",    f"{t_leth:.2f} s",
               delta_color=("inverse" if t_leth > 0 else "off"),
               delta=("engaged" if t_leth > 0 else "safe"))
    tc4.metric("Intercepts", f"{n_hits}",
               delta_color=("inverse" if n_hits > 0 else "off"),
               delta=", ".join(threat_report.enemy_names[j]
                               for j, _ in threat_report.intercept_events)
                      if n_hits > 0 else "none")

    # Range-vs-time line plot, one curve per enemy
    rng_fig = go.Figure()
    for j, name in enumerate(threat_report.enemy_names):
        rng_fig.add_trace(go.Scatter(
            x=t, y=threat_report.per_step_min_range[:, j],
            mode="lines", name=name,
            line=dict(width=2),
        ))
        if j < len(enemy_static):
            rng_fig.add_hline(
                y=enemy_static[j]["det_r"],
                line=dict(color=PALETTE["amber"], width=1, dash="dot"),
                opacity=0.35,
            )
            rng_fig.add_hline(
                y=enemy_static[j]["leth_r"],
                line=dict(color=PALETTE["red"],   width=1, dash="dot"),
                opacity=0.35,
            )
    rng_fig.update_layout(
        height=260,
        xaxis_title="Time [s]", yaxis_title="Range [m]",
        margin=dict(l=10, r=10, t=10, b=30),
        legend=dict(orientation="h", y=1.02, x=0),
    )
    st.plotly_chart(rng_fig, width="stretch")
    st.caption("Dotted lines show each threat's detection (amber) and "
               "lethal (red) radii. Evasion kicks in below the amber line "
               "when ownship-reaction is enabled.")


# ====================================================================== #
# State-Estimator panel (true vs measured vs EKF)
# ====================================================================== #
if enable_noise:
    st.subheader("State Estimator")
    if estimator_used:
        st.caption(
            "EKF fuses noisy GPS-style position fixes with a constant-velocity "
            "model. The position controller consumes the **estimated** state, "
            "not the raw measurement."
        )
    else:
        st.caption(
            "EKF is **off** — the controller is being fed raw noisy measurements "
            "directly. Toggle the EKF on (sidebar → State Estimation) to compare."
        )

    # Per-axis residuals (true minus signal)
    raw_resid = meas_pos - pos          # (N, 3) raw measurement noise
    est_resid = state_est[:, 0:3] - pos # (N, 3) estimator residual
    raw_rms = float(np.sqrt(np.mean(raw_resid ** 2)))
    est_rms = float(np.sqrt(np.mean(est_resid ** 2)))
    improvement = (1.0 - est_rms / raw_rms) * 100.0 if raw_rms > 1e-9 else 0.0
    vel_true = res["state"][:, 3:6]
    vel_est  = state_est[:, 3:6]
    vel_rms  = float(np.sqrt(np.mean((vel_est - vel_true) ** 2)))

    ec1, ec2, ec3, ec4 = st.columns(4)
    ec1.metric("Raw GPS RMS", f"{raw_rms * 100:.2f} cm")
    if estimator_used:
        ec2.metric("EKF position RMS", f"{est_rms * 100:.2f} cm",
                   delta=f"{improvement:+.1f}% vs raw",
                   delta_color="normal" if improvement > 0 else "inverse")
        ec3.metric("EKF velocity RMS", f"{vel_rms:.3f} m/s",
                   help="Velocity isn't directly measured — EKF derives it.")
        ec4.metric("Final P-trace", f"{float(pos_cov_trace[-1]):.4f} m²",
                   help="Trace of estimated position covariance — smaller is more confident.")
    else:
        ec2.metric("EKF position RMS", "—", delta="disabled")
        ec3.metric("EKF velocity RMS", "—", delta="disabled")
        ec4.metric("Final P-trace", "—", delta="disabled")

    # True / Measured / Estimated overlay per axis
    est_fig = make_subplots(rows=3, cols=1, shared_xaxes=True,
                            subplot_titles=("X position", "Y position", "Z position"),
                            vertical_spacing=0.06)
    axis_labels = ["x", "y", "z"]
    for i in range(3):
        est_fig.add_trace(go.Scatter(
            x=t, y=meas_pos[:, i],
            name="Measured", mode="lines",
            line=dict(color=PALETTE["amber"], width=1, dash="dot"),
            opacity=0.55, showlegend=(i == 0),
            legendgroup="meas",
        ), row=i + 1, col=1)
        if estimator_used:
            est_fig.add_trace(go.Scatter(
                x=t, y=state_est[:, i],
                name="EKF", mode="lines",
                line=dict(color=PALETTE["cyan"], width=2),
                showlegend=(i == 0),
                legendgroup="ekf",
            ), row=i + 1, col=1)
        est_fig.add_trace(go.Scatter(
            x=t, y=pos[:, i],
            name="True", mode="lines",
            line=dict(color=PALETTE["green"], width=2),
            showlegend=(i == 0),
            legendgroup="true",
        ), row=i + 1, col=1)
        est_fig.update_yaxes(title_text=f"{axis_labels[i]} [m]", row=i + 1, col=1)
    est_fig.update_xaxes(title_text="Time [s]", row=3, col=1)
    est_fig.update_layout(
        height=520,
        margin=dict(l=10, r=10, t=40, b=30),
        legend=dict(orientation="h", y=1.06, x=0),
    )
    st.plotly_chart(est_fig, width="stretch")


# ====================================================================== #
# Monte Carlo dispersion panel
# ====================================================================== #
mc_res = st.session_state.get("mc_result")
if mc_res is not None and len(mc_res.trajectories) > 0:
    st.subheader("Monte Carlo Dispersion")
    cfg_mc = mc_res.config
    st.caption(
        f"{len(mc_res.trajectories)} runs · wind ±{int(cfg_mc.wind_mean_jitter * 100)}% · "
        f"mass ±{int(cfg_mc.mass_jitter * 100)}% · "
        f"IMU bias σ={cfg_mc.imu_bias_std_deg:.1f}° · "
        f"start XY jitter ±{cfg_mc.start_xy_jitter:.2f} m"
    )

    cmc1, cmc2, cmc3, cmc4 = st.columns(4)
    cmc1.metric("Success rate",
                f"{mc_res.success_rate * 100:.1f} %",
                delta=f"{int(mc_res.success_mask.sum())} / {len(mc_res.trajectories)}",
                delta_color="off")
    cmc2.metric("Final-error mean",
                f"{float(np.mean(mc_res.final_errors)):.2f} m",
                delta=f"σ = {float(np.std(mc_res.final_errors)):.2f} m",
                delta_color="off")
    cmc3.metric("Mean RMS error",
                f"{float(np.mean(mc_res.rms_errors)):.2f} m")
    cmc4.metric("Mean mission time",
                f"{float(np.mean(mc_res.mission_times)):.2f} s")

    cleft, cright = st.columns([3, 2], gap="medium")

    with cleft:
        st.markdown("**Trajectory cloud (top-down)**")
        cloud = go.Figure()
        # zone overlays first so they sit underneath
        ring_theta = np.linspace(0.0, 2 * np.pi, 96)
        for z in geofence_zones:
            cloud.add_trace(go.Scatter(
                x=z.cx + z.radius * np.cos(ring_theta),
                y=z.cy + z.radius * np.sin(ring_theta),
                mode="lines", fill="toself",
                line=dict(color=PALETTE["red" if z.kind == "no_fly" else "amber"],
                          width=1, dash="dash"),
                fillcolor=zone_color(z, alpha=0.12),
                name=z.name, hoverinfo="skip", showlegend=False,
            ))
        # all dispersed runs (faded)
        for traj in mc_res.trajectories:
            cloud.add_trace(go.Scatter(
                x=traj[:, 0], y=traj[:, 1],
                mode="lines",
                line=dict(color="rgba(0,212,255,0.10)", width=1),
                hoverinfo="skip", showlegend=False,
            ))
        # CEP rings + waypoint markers
        for i, wp in enumerate(mc_res.waypoints):
            for radius, label, dash in (
                (mc_res.cep50_per_wp[i], "CEP50", "dot"),
                (mc_res.cep95_per_wp[i], "CEP95", "dash"),
            ):
                if radius <= 0:
                    continue
                cloud.add_trace(go.Scatter(
                    x=wp[0] + radius * np.cos(ring_theta),
                    y=wp[1] + radius * np.sin(ring_theta),
                    mode="lines",
                    line=dict(color=PALETTE["pink"], width=1, dash=dash),
                    hovertemplate=f"{label} WPT-{i + 1}: {radius:.2f} m<extra></extra>",
                    showlegend=(i == 0 and label == "CEP50"),
                    name=label,
                ))
            cloud.add_trace(go.Scatter(
                x=[wp[0]], y=[wp[1]],
                mode="markers+text",
                marker=dict(size=11, color=PALETTE["amber"], symbol="diamond"),
                text=[f"WPT-{i + 1}"], textposition="top center",
                textfont=dict(color=PALETTE["amber"], size=10),
                hoverinfo="skip", showlegend=False,
            ))
        # endpoint scatter coloured by success
        ok = mc_res.success_mask
        cloud.add_trace(go.Scatter(
            x=mc_res.endpoints[ok, 0], y=mc_res.endpoints[ok, 1],
            mode="markers",
            marker=dict(size=6, color=PALETTE["green"],
                        line=dict(color=PALETTE["bg"], width=0.5)),
            name=f"Endpoint ✓ ({int(ok.sum())})",
        ))
        if (~ok).any():
            cloud.add_trace(go.Scatter(
                x=mc_res.endpoints[~ok, 0], y=mc_res.endpoints[~ok, 1],
                mode="markers",
                marker=dict(size=7, color=PALETTE["red"], symbol="x"),
                name=f"Endpoint ✗ ({int((~ok).sum())})",
            ))

        cloud.update_xaxes(title="East X [m]", scaleanchor="y", scaleratio=1)
        cloud.update_yaxes(title="North Y [m]")
        cloud.update_layout(
            height=480, margin=dict(l=10, r=10, b=30, t=20),
            legend=dict(x=0.01, y=0.99, bgcolor="rgba(10,14,26,0.6)"),
        )
        st.plotly_chart(cloud, width='stretch')

    with cright:
        st.markdown("**Final position-error distribution**")
        hist = go.Figure()
        hist.add_trace(go.Histogram(
            x=mc_res.final_errors, nbinsx=20,
            marker=dict(color=PALETTE["cyan"],
                        line=dict(color=PALETTE["bg"], width=1)),
            opacity=0.85, name="final error",
        ))
        hist.add_vline(
            x=cfg_mc.success_radius,
            line=dict(color=PALETTE["green"], width=2, dash="dash"),
            annotation_text=f"success ≤ {cfg_mc.success_radius:.1f} m",
            annotation_position="top right",
            annotation_font_color=PALETTE["green"],
        )
        hist.update_layout(
            height=230, margin=dict(l=10, r=10, b=30, t=10),
            xaxis_title="Final error [m]", yaxis_title="Runs",
            bargap=0.05, showlegend=False,
        )
        st.plotly_chart(hist, width='stretch')

        st.markdown("**CEP per waypoint**")
        cep_tbl = pd.DataFrame({
            "WPT": [f"WPT-{i + 1}" for i in range(len(mc_res.waypoints))],
            "CEP50 [m]": np.round(mc_res.cep50_per_wp, 3),
            "CEP95 [m]": np.round(mc_res.cep95_per_wp, 3),
        })
        st.dataframe(cep_tbl, width='stretch', hide_index=True)


# ====================================================================== #
# Tactical Map (interactive canvas component)
# ====================================================================== #
st.subheader("Tactical Map")
st.caption(
    "Drag waypoints, bandits or zones with the mouse · scroll to zoom · "
    "drag empty space to pan · ▶ play to replay the flight · "
    "use the **Add to Scenario** panel below to spawn new entities."
)


# ---------------------------------------------------------------------- #
# Quick-add panel: spawn waypoints / bandits / zones inline
# ---------------------------------------------------------------------- #
def _next_name(existing: list[str], stem: str) -> str:
    """Find the smallest integer N such that '{stem}-N' isn't taken."""
    used = set(existing)
    i = 1
    while f"{stem}-{i}" in used:
        i += 1
    return f"{stem}-{i}"


def _add_waypoint(x: float, y: float, z: float, yaw: float) -> None:
    st.session_state.waypoints = (
        list(st.session_state.waypoints) + [[float(x), float(y), float(z)]]
    )
    st.session_state.yaws = list(st.session_state.yaws) + [float(yaw)]
    st.session_state.pop("last_result", None)


def _add_bandit(name: str, x: float, y: float, z: float, behavior: str,
                speed: float, det_r: float, leth_r: float,
                orbit_cx: float, orbit_cy: float, orbit_r: float) -> None:
    cur = st.session_state.enemy_df.copy()
    if len(cur) >= 3:
        st.warning("Maximum 3 bandits supported. Remove one first.")
        return
    new_row = pd.DataFrame([{
        "name": name, "x": x, "y": y, "z": z,
        "behavior": behavior, "speed": speed,
        "det_r": det_r, "leth_r": leth_r,
        "orbit_cx": orbit_cx, "orbit_cy": orbit_cy, "orbit_r": orbit_r,
    }])
    st.session_state.enemy_df = pd.concat([cur, new_row], ignore_index=True)
    st.session_state.pop("last_result", None)


def _add_zone(name: str, kind: str, cx: float, cy: float, r: float,
              z_min: float, z_max: float) -> None:
    cur = st.session_state.geofence_df.copy()
    new_row = pd.DataFrame([{
        "name": name, "cx": cx, "cy": cy, "r": r,
        "z_min": z_min, "z_max": z_max, "kind": kind,
    }])
    st.session_state.geofence_df = pd.concat([cur, new_row], ignore_index=True)
    st.session_state.pop("last_result", None)


# ---- Header card for the add panel ----
st.markdown(
    f"""
    <div style="display:flex;align-items:center;gap:10px;
                padding:10px 14px;margin-top:6px;
                background:linear-gradient(90deg,{PALETTE['panel']} 0%,
                                                   {PALETTE['panel_soft']} 100%);
                border:1px solid rgba(0,212,255,0.18);
                border-radius:10px;">
      <span style="display:inline-block;width:5px;height:20px;
                   background:{PALETTE['green']};border-radius:2px;"></span>
      <span style="font-size:1.0rem;font-weight:600;color:{PALETTE['text']};
                   letter-spacing:0.3px;">Add to Scenario</span>
      <span style="margin-left:auto;font-size:0.74rem;color:{PALETTE['muted']};
                   letter-spacing:0.5px;">
        Pick a tab · fill the form · the entity drops onto the map below.
      </span>
    </div>
    """,
    unsafe_allow_html=True,
)

_existing_wp_names = [f"WPT-{i + 1}" for i in range(len(st.session_state.waypoints))]
_existing_enemy_names = (
    list(st.session_state.enemy_df["name"].astype(str))
    if len(st.session_state.enemy_df) else []
)
_existing_zone_names = (
    list(st.session_state.geofence_df["name"].astype(str))
    if len(st.session_state.geofence_df) else []
)

add_tabs = st.tabs([
    "📍  Waypoint",
    "🛩  Bandit",
    "🚫  No-fly Zone",
    "⚠  Threat Zone",
])

# ---- Waypoint tab ----
with add_tabs[0]:
    cols = st.columns([1, 1, 1, 1, 1.4])
    new_wp_x   = cols[0].number_input("x [m]",   -20.0, 20.0, 0.0, 0.5, key="qa_wp_x")
    new_wp_y   = cols[1].number_input("y [m]",   -20.0, 20.0, 0.0, 0.5, key="qa_wp_y")
    new_wp_z   = cols[2].number_input("z [m]",     0.0, 15.0, 3.0, 0.5, key="qa_wp_z")
    new_wp_yaw = cols[3].number_input("yaw [°]", -180.0, 360.0, 0.0, 5.0, key="qa_wp_yaw")
    cols[4].markdown("<div style='height:28px;'></div>", unsafe_allow_html=True)
    if cols[4].button("＋ Add waypoint", type="primary",
                      width="stretch", key="qa_wp_btn"):
        _add_waypoint(new_wp_x, new_wp_y, new_wp_z, new_wp_yaw)
        st.toast(f"Waypoint added at ({new_wp_x:.1f}, {new_wp_y:.1f}, {new_wp_z:.1f}).",
                 icon="📍")
        st.rerun()
    st.caption(":material/info: Or **shift-click anywhere on the map below** to drop "
               "a waypoint at the cursor location.")

# ---- Bandit tab ----
with add_tabs[1]:
    if len(st.session_state.enemy_df) >= 3:
        st.info("3 bandits already deployed — the simulator is capped at 3. "
                "Remove one from the sidebar table to free a slot.")
    else:
        r1c = st.columns([1.3, 1, 1, 1, 1.3])
        new_bn_name = r1c[0].text_input(
            "Callsign", value=_next_name(_existing_enemy_names, "BANDIT"),
            key="qa_bn_name")
        new_bn_x = r1c[1].number_input("x [m]", -20.0, 20.0, 4.0, 0.5, key="qa_bn_x")
        new_bn_y = r1c[2].number_input("y [m]", -20.0, 20.0, 4.0, 0.5, key="qa_bn_y")
        new_bn_z = r1c[3].number_input("z [m]",   0.0, 15.0, 3.0, 0.5, key="qa_bn_z")
        new_bn_behavior = r1c[4].selectbox(
            "Behaviour", ["patrol", "loiter", "pursue"],
            help="patrol = orbit a centre · loiter = hover · pursue = chase",
            key="qa_bn_behav")

        r2c = st.columns([1, 1, 1, 1, 1, 1.3])
        new_bn_spd  = r2c[0].number_input("Speed [m/s]", 0.0, 5.0, 1.5, 0.1, key="qa_bn_spd")
        new_bn_det  = r2c[1].number_input("Detect [m]",  0.5, 10.0, 3.5, 0.1, key="qa_bn_det")
        new_bn_leth = r2c[2].number_input("Lethal [m]",  0.1,  5.0, 1.0, 0.1, key="qa_bn_leth")
        orbit_disabled = (new_bn_behavior != "patrol")
        new_bn_ocx = r2c[3].number_input("Orbit cx", -20.0, 20.0, 4.0, 0.5,
                                         key="qa_bn_ocx", disabled=orbit_disabled)
        new_bn_ocy = r2c[4].number_input("Orbit cy", -20.0, 20.0, 4.0, 0.5,
                                         key="qa_bn_ocy", disabled=orbit_disabled)
        r2c[5].markdown("<div style='height:28px;'></div>", unsafe_allow_html=True)
        if r2c[5].button("＋ Deploy bandit", type="primary",
                         width="stretch", key="qa_bn_btn"):
            orbit_r = float(np.hypot(new_bn_ocx - new_bn_x,
                                     new_bn_ocy - new_bn_y)) if new_bn_behavior == "patrol" else 0.0
            _add_bandit(new_bn_name, new_bn_x, new_bn_y, new_bn_z,
                        new_bn_behavior, new_bn_spd, new_bn_det, new_bn_leth,
                        new_bn_ocx if new_bn_behavior == "patrol" else 0.0,
                        new_bn_ocy if new_bn_behavior == "patrol" else 0.0,
                        orbit_r)
            st.toast(f"Bandit {new_bn_name} deployed.", icon="🛩")
            st.rerun()
        st.caption(":material/info: **Detect** = ownship reacts inside this radius. "
                   "**Lethal** = intercept counted below this range. "
                   "Orbit fields are only used by *patrol* behaviour.")

# ---- No-fly zone tab ----
with add_tabs[2]:
    cols = st.columns([1.4, 1, 1, 1, 1, 1, 1.4])
    new_nf_name = cols[0].text_input(
        "Name", value=_next_name(_existing_zone_names, "RESTRICTED"),
        key="qa_nf_name")
    new_nf_cx = cols[1].number_input("cx [m]",  -20.0, 20.0, 0.0, 0.5, key="qa_nf_cx")
    new_nf_cy = cols[2].number_input("cy [m]",  -20.0, 20.0, 0.0, 0.5, key="qa_nf_cy")
    new_nf_r  = cols[3].number_input("Radius [m]", 0.1, 10.0, 1.5, 0.1, key="qa_nf_r")
    new_nf_zmin = cols[4].number_input("z_min [m]", 0.0, 15.0, 0.0, 0.5, key="qa_nf_zmin")
    new_nf_zmax = cols[5].number_input("z_max [m]", 0.5, 15.0, 6.0, 0.5, key="qa_nf_zmax")
    cols[6].markdown("<div style='height:28px;'></div>", unsafe_allow_html=True)
    if cols[6].button("＋ Add no-fly", type="primary",
                      width="stretch", key="qa_nf_btn"):
        if new_nf_zmax <= new_nf_zmin:
            st.error("z_max must be greater than z_min.")
        else:
            _add_zone(new_nf_name, "no_fly", new_nf_cx, new_nf_cy, new_nf_r,
                      new_nf_zmin, new_nf_zmax)
            st.toast(f"No-fly zone {new_nf_name} added.", icon="🚫")
            st.rerun()
    st.caption(":material/info: A **no-fly** is a hard restriction — the dashboard "
               "tallies time spent inside as a violation.")

# ---- Threat zone tab ----
with add_tabs[3]:
    cols = st.columns([1.4, 1, 1, 1, 1, 1, 1.4])
    new_tz_name = cols[0].text_input(
        "Name", value=_next_name(_existing_zone_names, "THREAT"),
        key="qa_tz_name")
    new_tz_cx = cols[1].number_input("cx [m]",  -20.0, 20.0, 3.0, 0.5, key="qa_tz_cx")
    new_tz_cy = cols[2].number_input("cy [m]",  -20.0, 20.0, 3.0, 0.5, key="qa_tz_cy")
    new_tz_r  = cols[3].number_input("Radius [m]", 0.1, 10.0, 1.2, 0.1, key="qa_tz_r")
    new_tz_zmin = cols[4].number_input("z_min [m]", 0.0, 15.0, 0.0, 0.5, key="qa_tz_zmin")
    new_tz_zmax = cols[5].number_input("z_max [m]", 0.5, 15.0, 6.0, 0.5, key="qa_tz_zmax")
    cols[6].markdown("<div style='height:28px;'></div>", unsafe_allow_html=True)
    if cols[6].button("＋ Add threat", type="primary",
                      width="stretch", key="qa_tz_btn"):
        if new_tz_zmax <= new_tz_zmin:
            st.error("z_max must be greater than z_min.")
        else:
            _add_zone(new_tz_name, "threat", new_tz_cx, new_tz_cy, new_tz_r,
                      new_tz_zmin, new_tz_zmax)
            st.toast(f"Threat zone {new_tz_name} added.", icon="⚠")
            st.rerun()
    st.caption(":material/info: A **threat zone** is a soft warning — the dashboard "
               "highlights time-in-zone but doesn't fail the mission.")

st.markdown("<div style='height:6px;'></div>", unsafe_allow_html=True)

_tac_zone_payload = [
    {"name": z.name, "cx": z.cx, "cy": z.cy, "radius": z.radius,
     "z_min": z.z_min, "z_max": z.z_max, "kind": z.kind}
    for z in geofence_zones
]
# Subsample the flown trajectory so we don't ship 4000 points to the iframe.
_tac_stride = max(1, len(pos) // 600)
_tac_flown    = pos[::_tac_stride].tolist()
_tac_timeline = t[::_tac_stride].tolist()
_tac_vehicle_track = [
    {"x": float(p[0]), "y": float(p[1]), "z": float(p[2]),
     "yaw": float(eul[2])}
    for p, eul in zip(pos[::_tac_stride], euler[::_tac_stride])
]
_tac_vehicle = {
    "x": float(pos[-1, 0]), "y": float(pos[-1, 1]),
    "z": float(pos[-1, 2]), "yaw": float(euler[-1, 2]),
}

# Enemy payload: final pose + per-step (x, y, heading) track.
_tac_enemies: list[dict] = []
if enemy_hist.shape[1] > 0:
    for j, info in enumerate(enemy_static):
        sub = enemy_hist[::_tac_stride, j]   # (K, 4) -> [x,y,z,heading]
        track = sub[:, [0, 1, 3]].tolist()
        final = enemy_hist[-1, j]
        _tac_enemies.append({
            "name":     info["name"],
            "behavior": info["behavior"],
            "x":        float(final[0]),
            "y":        float(final[1]),
            "z":        float(info["z"]),
            "heading":  float(final[3]),
            "det_r":    float(info["det_r"]),
            "leth_r":   float(info["leth_r"]),
            "track":    track,
        })

_tac_edited = tactical_map(
    waypoints=st.session_state.waypoints,
    flown=_tac_flown,
    zones=_tac_zone_payload,
    vehicle=_tac_vehicle,
    enemies=_tac_enemies,
    timeline=_tac_timeline,
    vehicle_track=_tac_vehicle_track,
    key="tac",
)


def _apply_tac_response(payload):
    """Dispatch the tactical-map payload back into Streamlit session state.

    The component emits ``{"waypoints": [...], "enemies": [...], "zones": [...]}``
    after any drag/add/remove. We update each session-state slot only if the
    relevant section actually changed, then trigger a rerun.
    """
    changed = False
    if isinstance(payload, list):  # legacy: just waypoints
        payload = {"waypoints": payload}
    if not isinstance(payload, dict):
        return False

    new_wps = payload.get("waypoints")
    if new_wps is not None:
        cleaned = [[float(v) for v in p] for p in new_wps]
        if cleaned != st.session_state.waypoints:
            n = len(cleaned)
            if n > len(st.session_state.yaws):
                st.session_state.yaws = (st.session_state.yaws
                                         + [0.0] * (n - len(st.session_state.yaws)))
            else:
                st.session_state.yaws = st.session_state.yaws[:n]
            st.session_state.waypoints = cleaned
            changed = True

    new_enemies = payload.get("enemies")
    if new_enemies is not None and isinstance(new_enemies, list):
        cur = st.session_state.enemy_df.copy()
        for upd in new_enemies:
            name = str(upd.get("name", ""))
            if not name:
                continue
            mask = (cur["name"] == name)
            if not mask.any():
                continue
            for col in ("x", "y", "z", "orbit_cx", "orbit_cy", "orbit_r"):
                if col in upd:
                    try:
                        cur.loc[mask, col] = float(upd[col])
                    except (TypeError, ValueError):
                        pass
        if not cur.equals(st.session_state.enemy_df):
            st.session_state.enemy_df = cur
            changed = True

    new_zones = payload.get("zones")
    if new_zones is not None and isinstance(new_zones, list):
        cur = st.session_state.geofence_df.copy()
        for upd in new_zones:
            name = str(upd.get("name", ""))
            if not name:
                continue
            mask = (cur["name"] == name)
            if not mask.any():
                continue
            for src, dst in (("cx", "cx"), ("cy", "cy"), ("radius", "r")):
                if src in upd:
                    try:
                        cur.loc[mask, dst] = float(upd[src])
                    except (TypeError, ValueError):
                        pass
        if not cur.equals(st.session_state.geofence_df):
            st.session_state.geofence_df = cur
            changed = True

    return changed


if _tac_edited is not None and _apply_tac_response(_tac_edited):
    st.rerun()


# ====================================================================== #
# Animated 3D flight view + HUD
# ====================================================================== #
st.subheader("3D Flight View")
st.caption(
    "Press Play to watch the drone fly. Rotate / zoom with the mouse, or "
    "drag the slider under the plot to scrub. The flown path is coloured "
    "by instantaneous 3D tracking error (blue = on-target, red = high error)."
)

# --- Downsample for smooth in-browser animation ----------------------- #
N_DISPLAY = min(400, len(t))
disp_idx  = np.linspace(0, len(t) - 1, N_DISPLAY, dtype=int)
td        = t[disp_idx]
posd      = pos[disp_idx]
eulerd    = euler[disp_idx]
ud        = u[disp_idx]
veld      = res["state"][disp_idx, 3:6]
errd      = err[disp_idx]

err_norm_d = np.linalg.norm(errd, axis=1)
speed_d    = np.linalg.norm(veld, axis=1)
tilt_deg_d = np.rad2deg(np.sqrt(eulerd[:, 0] ** 2 + eulerd[:, 1] ** 2))
thrust_max = max(float(ud[:, 0].max()) * 1.1, 20.0)
thrust_pct_d = 100.0 * ud[:, 0] / thrust_max

N_FRAMES = min(120, N_DISPLAY)
frame_idx = np.linspace(0, N_DISPLAY - 1, N_FRAMES, dtype=int)

ground_z = float(min(posd[:, 2].min(), 0.0)) - 0.05
err_max  = float(max(err_norm_d.max(), 0.1))
alt_max  = float(max(posd[:, 2].max(), 1.0)) * 1.15
spd_max  = float(max(speed_d.max(), 1.0)) * 1.15
tilt_max = float(max(tilt_deg_d.max(), 5.0)) * 1.15

ARM_LEN = 0.45


def drone_geometry(p_, phi_, theta_, psi_, arm_len=ARM_LEN):
    """Return body-line xyz (with None separators) and rotor-tip positions."""
    R_ = euler_to_rotmat(phi_, theta_, psi_)
    tips_body = np.array([
        [arm_len, 0.0, 0.0], [-arm_len, 0.0, 0.0],
        [0.0,  arm_len, 0.0], [0.0, -arm_len, 0.0],
    ])
    tips_ = (R_ @ tips_body.T).T + p_
    xs_, ys_, zs_ = [], [], []
    for tip in tips_:
        xs_ += [p_[0], tip[0], None]
        ys_ += [p_[1], tip[1], None]
        zs_ += [p_[2], tip[2], None]
    return xs_, ys_, zs_, tips_


# Palette-aligned rotor colours: cyan front/back, pink sides (LED-style)
ROTOR_COLORS = [PALETTE["cyan"], PALETTE["cyan"], PALETTE["pink"], PALETTE["pink"]]


def ground_grid_lines(xr, yr, step, z_level):
    """Crosshatch of grid lines on the ground plane, packed into one trace."""
    xs, ys, zs = [], [], []
    y0 = np.floor(yr[0] / step) * step
    y1 = np.ceil(yr[1] / step) * step
    x0 = np.floor(xr[0] / step) * step
    x1 = np.ceil(xr[1] / step) * step
    for y in np.arange(y0, y1 + step * 0.5, step):
        xs += [x0, x1, None]
        ys += [y, y, None]
        zs += [z_level, z_level, None]
    for x in np.arange(x0, x1 + step * 0.5, step):
        xs += [x, x, None]
        ys += [y0, y1, None]
        zs += [z_level, z_level, None]
    return xs, ys, zs


def waypoint_pillar_lines(wps_, z_floor):
    """Vertical stem from ground plane to each waypoint, packed in one trace."""
    xs, ys, zs = [], [], []
    for w in wps_:
        xs += [w[0], w[0], None]
        ys += [w[1], w[1], None]
        zs += [z_floor, w[2], None]
    return xs, ys, zs

# --- Figure skeleton --------------------------------------------------- #
fig = make_subplots(
    rows=2, cols=4,
    specs=[
        [{"type": "indicator"}, {"type": "indicator"},
         {"type": "indicator"}, {"type": "indicator"}],
        [{"type": "scene", "colspan": 4}, None, None, None],
    ],
    row_heights=[0.16, 0.84],
    vertical_spacing=0.03,
)

# --- Trace 0..3: HUD indicators (initial values) ---------------------- #
GAUGE_BG = PALETTE["panel_soft"]
GAUGE_BORDER = "rgba(0,212,255,0.25)"


def _gauge(value, title, suffix, axis_max, bar_color,
           value_format=".2f", steps=None):
    g = {
        "axis": {"range": [0, axis_max],
                 "tickcolor": PALETTE["muted"],
                 "tickfont": {"color": PALETTE["muted"], "size": 10}},
        "bar": {"color": bar_color, "thickness": 0.32},
        "bgcolor": GAUGE_BG,
        "borderwidth": 1,
        "bordercolor": GAUGE_BORDER,
    }
    if steps is not None:
        g["steps"] = steps
    return go.Indicator(
        mode="gauge+number",
        value=float(value),
        title={"text": title,
               "font": {"color": PALETTE["muted"], "size": 13}},
        number={"suffix": suffix, "valueformat": value_format,
                "font": {"color": PALETTE["text"], "size": 26}},
        gauge=g,
    )


THRUST_STEPS = [
    {"range": [0, 50],   "color": "rgba( 46,204,113,0.18)"},
    {"range": [50, 85],  "color": "rgba(255,193,  7,0.18)"},
    {"range": [85, 100], "color": "rgba(255, 82, 82,0.20)"},
]

fig.add_trace(_gauge(posd[0, 2],   "Altitude", " m",
                     alt_max, PALETTE["cyan"]),   row=1, col=1)
fig.add_trace(_gauge(speed_d[0],   "Airspeed", " m/s",
                     spd_max, PALETTE["green"]),  row=1, col=2)
fig.add_trace(_gauge(thrust_pct_d[0], "Thrust", " %",
                     100.0, PALETTE["amber"], ".1f", THRUST_STEPS),
              row=1, col=3)
fig.add_trace(_gauge(tilt_deg_d[0], "Tilt", " deg",
                     tilt_max, PALETTE["violet"], ".1f"),
              row=1, col=4)

# Scene bounding box (pad so grid extends past the trajectory)
xr_all = np.concatenate([pos[:, 0], wps[:, 0]])
yr_all = np.concatenate([pos[:, 1], wps[:, 1]])
xr = (float(xr_all.min()) - 1.5, float(xr_all.max()) + 1.5)
yr = (float(yr_all.min()) - 1.5, float(yr_all.max()) + 1.5)
grid_step = max(1.0, round((max(xr[1] - xr[0], yr[1] - yr[0])) / 10))

# --- Trace 4: ground grid floor (static) ------------------------------ #
gx, gy, gz = ground_grid_lines(xr, yr, grid_step, ground_z)
fig.add_trace(go.Scatter3d(
    x=gx, y=gy, z=gz,
    mode="lines",
    line=dict(color="rgba(0,212,255,0.22)", width=1),
    name="Ground grid", showlegend=False, hoverinfo="skip",
), row=2, col=1)

# --- Trace 5: waypoint pillars (static) ------------------------------- #
px_, py_, pz_ = waypoint_pillar_lines(wps, ground_z)
fig.add_trace(go.Scatter3d(
    x=px_, y=py_, z=pz_,
    mode="lines",
    line=dict(color="rgba(255,193,7,0.35)", width=2, dash="dot"),
    name="Pillars", showlegend=False, hoverinfo="skip",
), row=2, col=1)

# --- Trace 6: planned path (static) ----------------------------------- #
fig.add_trace(go.Scatter3d(
    x=wps[:, 0], y=wps[:, 1], z=wps[:, 2],
    mode="lines+markers+text",
    line=dict(color=PALETTE["amber"], width=4, dash="dash"),
    marker=dict(size=8, color=PALETTE["amber"],
                line=dict(color="#5a4500", width=1)),
    text=[f"WP{i}" for i in range(len(wps))],
    textposition="top center",
    textfont=dict(color=PALETTE["amber"], size=11),
    name="Planned",
), row=2, col=1)

# --- Trace 7: full faded trajectory (static reference) ---------------- #
fig.add_trace(go.Scatter3d(
    x=pos[:, 0], y=pos[:, 1], z=pos[:, 2],
    mode="lines",
    line=dict(color="rgba(225,232,240,0.12)", width=2),
    name="Full path",
    showlegend=False,
), row=2, col=1)

# --- Trace 8: flown-so-far, coloured by tracking error ---------------- #
fig.add_trace(go.Scatter3d(
    x=[posd[0, 0]], y=[posd[0, 1]], z=[posd[0, 2]],
    mode="markers",
    marker=dict(
        size=4,
        color=[err_norm_d[0]],
        colorscale="Turbo",
        cmin=0.0, cmax=err_max,
        colorbar=dict(
            title=dict(text="Err [m]", font=dict(color=PALETTE["muted"])),
            thickness=12, len=0.55, x=0.99, y=0.4,
            tickfont=dict(color=PALETTE["muted"]),
            outlinecolor="rgba(0,0,0,0)",
        ),
    ),
    name="Flown",
), row=2, col=1)

# --- Trace 9: ground shadow ------------------------------------------- #
fig.add_trace(go.Scatter3d(
    x=[posd[0, 0]], y=[posd[0, 1]], z=[ground_z],
    mode="lines",
    line=dict(color=PALETTE["shadow"], width=5),
    name="Shadow", showlegend=False,
), row=2, col=1)

# --- Trace 10: drone body arms ---------------------------------------- #
xs0, ys0, zs0, tips0 = drone_geometry(posd[0], *eulerd[0])
fig.add_trace(go.Scatter3d(
    x=xs0, y=ys0, z=zs0,
    mode="lines",
    line=dict(color="#e1e8f0", width=8),
    name="Drone", showlegend=False,
), row=2, col=1)

# --- Trace 11: rotor tips --------------------------------------------- #
fig.add_trace(go.Scatter3d(
    x=tips0[:, 0], y=tips0[:, 1], z=tips0[:, 2],
    mode="markers",
    marker=dict(size=12, color=ROTOR_COLORS,
                line=dict(color="#0a0e1a", width=1)),
    name="Rotors", showlegend=False,
), row=2, col=1)

# --- Static traces 12+: geofence cylinders + top rings ---------------- #
# Appended after the dynamic traces so frame trace indices stay stable.
for _z in geofence_zones:
    fig.add_trace(cylinder_mesh3d(_z),    row=2, col=1)
    fig.add_trace(cylinder_top_ring(_z),  row=2, col=1)

# --- Static: enemy tracks + final markers + detection domes ----------- #
if enemy_hist.shape[1] > 0:
    _ring_theta = np.linspace(0.0, 2 * np.pi, 48)
    for j, info in enumerate(enemy_static):
        track_xy = enemy_hist[:, j, 0:2]
        fig.add_trace(go.Scatter3d(
            x=track_xy[:, 0], y=track_xy[:, 1],
            z=np.full(track_xy.shape[0], info["z"]),
            mode="lines",
            line=dict(color="rgba(255, 82, 82, 0.55)", width=3, dash="dot"),
            name=f"{info['name']} track",
            showlegend=False, hoverinfo="skip",
        ), row=2, col=1)
        fx, fy = float(track_xy[-1, 0]), float(track_xy[-1, 1])
        fig.add_trace(go.Scatter3d(
            x=[fx], y=[fy], z=[info["z"]],
            mode="markers+text",
            marker=dict(size=9, color=PALETTE["red"], symbol="diamond",
                        line=dict(color="#0a0e1a", width=1)),
            text=[info["name"]], textposition="top center",
            textfont=dict(color=PALETTE["red"], size=11),
            name=info["name"], showlegend=False,
            hovertemplate=(f"{info['name']}<br>{info['behavior']}"
                           f"<br>det=%{{customdata[0]:.1f}} m"
                           f"<br>leth=%{{customdata[1]:.1f}} m<extra></extra>"),
            customdata=[[info["det_r"], info["leth_r"]]],
        ), row=2, col=1)
        # Detection ring at enemy altitude
        fig.add_trace(go.Scatter3d(
            x=fx + info["det_r"] * np.cos(_ring_theta),
            y=fy + info["det_r"] * np.sin(_ring_theta),
            z=np.full_like(_ring_theta, info["z"]),
            mode="lines",
            line=dict(color=PALETTE["red"], width=2, dash="dash"),
            name=f"{info['name']} detect",
            showlegend=False, hoverinfo="skip",
        ), row=2, col=1)

# --- Frames ----------------------------------------------------------- #
frames = []
for fi in frame_idx:
    p_k = posd[fi]
    xs_k, ys_k, zs_k, tips_k = drone_geometry(p_k, *eulerd[fi])
    n = int(fi) + 1
    frames.append(go.Frame(
        name=f"{td[fi]:.2f}",
        data=[
            # 0..3 HUD
            _gauge(posd[fi, 2],    "Altitude", " m",
                   alt_max, PALETTE["cyan"]),
            _gauge(speed_d[fi],    "Airspeed", " m/s",
                   spd_max, PALETTE["green"]),
            _gauge(thrust_pct_d[fi], "Thrust", " %",
                   100.0, PALETTE["amber"], ".1f", THRUST_STEPS),
            _gauge(tilt_deg_d[fi], "Tilt", " deg",
                   tilt_max, PALETTE["violet"], ".1f"),
            # 8 flown-so-far coloured
            go.Scatter3d(
                x=posd[:n, 0], y=posd[:n, 1], z=posd[:n, 2],
                mode="markers",
                marker=dict(size=4, color=err_norm_d[:n],
                            colorscale="Turbo",
                            cmin=0.0, cmax=err_max, showscale=False),
            ),
            # 9 shadow
            go.Scatter3d(
                x=posd[:n, 0], y=posd[:n, 1],
                z=np.full(n, ground_z),
                mode="lines",
                line=dict(color=PALETTE["shadow"], width=5),
            ),
            # 10 drone body
            go.Scatter3d(
                x=xs_k, y=ys_k, z=zs_k,
                mode="lines",
                line=dict(color="#e1e8f0", width=8),
            ),
            # 11 rotor tips
            go.Scatter3d(
                x=tips_k[:, 0], y=tips_k[:, 1], z=tips_k[:, 2],
                mode="markers",
                marker=dict(size=12, color=ROTOR_COLORS,
                            line=dict(color="#0a0e1a", width=1)),
            ),
        ],
        traces=[0, 1, 2, 3, 8, 9, 10, 11],
    ))
fig.frames = frames

# --- Layout, play/pause, time slider ---------------------------------- #
play_button = dict(
    type="buttons", direction="left",
    x=0.05, y=-0.02, xanchor="right", yanchor="top",
    pad={"r": 8, "t": 8}, showactive=False,
    buttons=[
        dict(label="Play", method="animate",
             args=[None, {"frame": {"duration": 60, "redraw": True},
                          "fromcurrent": True, "transition": {"duration": 0}}]),
        dict(label="Pause", method="animate",
             args=[[None], {"frame": {"duration": 0, "redraw": False},
                            "mode": "immediate", "transition": {"duration": 0}}]),
    ],
)

slider = dict(
    active=0, x=0.08, y=-0.02, xanchor="left", yanchor="top", len=0.9,
    pad={"t": 8, "b": 0},
    currentvalue={"prefix": "t = ", "suffix": " s",
                  "visible": True, "xanchor": "right"},
    steps=[
        dict(method="animate",
             args=[[f.name],
                   {"frame": {"duration": 0, "redraw": True},
                    "mode": "immediate", "transition": {"duration": 0}}],
             label=f.name)
        for f in frames
    ],
)

fig.update_layout(
    height=1100,
    scene=dict(
        xaxis_title="East X [m]",
        yaxis_title="North Y [m]",
        zaxis_title="Up Z [m]",
        aspectmode="data",
        camera=dict(eye=dict(x=1.6, y=1.6, z=0.9)),
        domain=dict(x=[0.0, 1.0], y=[0.0, 0.95]),
    ),
    margin=dict(l=0, r=0, b=70, t=20),
    legend=dict(x=0, y=0.85),
    updatemenus=[play_button],
    sliders=[slider],
)
st.plotly_chart(fig, width='stretch')


# ====================================================================== #
# Time-series plots
# ====================================================================== #
st.subheader("Time-Series Analysis")
tabs = st.tabs(["Altitude", "Position error", "Attitude",
                "Control inputs", "Disturbance"])

with tabs[0]:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=t, y=pos[:, 2], name="z actual",
                             line=dict(color="royalblue", width=2)))
    fig.add_trace(go.Scatter(x=t, y=res["waypoint"][:, 2], name="z commanded",
                             line=dict(color="red", dash="dash")))
    fig.update_layout(height=380, xaxis_title="Time [s]",
                      yaxis_title="Altitude [m]")
    st.plotly_chart(fig, width='stretch')

with tabs[1]:
    fig = go.Figure()
    for i, name in enumerate(["x error", "y error", "z error"]):
        fig.add_trace(go.Scatter(x=t, y=err[:, i], name=name))
    fig.add_trace(go.Scatter(x=t, y=np.linalg.norm(err, axis=1),
                             name="|error|",
                             line=dict(color="black", dash="dash", width=2)))
    fig.update_layout(height=380, xaxis_title="Time [s]",
                      yaxis_title="Error [m]")
    st.plotly_chart(fig, width='stretch')

with tabs[2]:
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True,
                        subplot_titles=("Roll", "Pitch", "Yaw"))
    for i in range(3):
        fig.add_trace(go.Scatter(x=t, y=np.rad2deg(euler[:, i]),
                                 name="measured", line=dict(color="royalblue"),
                                 showlegend=(i == 0)),
                      row=i + 1, col=1)
        fig.add_trace(go.Scatter(x=t, y=np.rad2deg(eul_cmd[:, i]),
                                 name="commanded",
                                 line=dict(color="red", dash="dash"),
                                 showlegend=(i == 0)),
                      row=i + 1, col=1)
    fig.update_yaxes(title_text="deg")
    fig.update_xaxes(title_text="Time [s]", row=3, col=1)
    fig.update_layout(height=540)
    st.plotly_chart(fig, width='stretch')

with tabs[3]:
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        subplot_titles=("Thrust", "Torques"))
    fig.add_trace(go.Scatter(x=t, y=u[:, 0], name="T [N]",
                             line=dict(color="darkgreen")),
                  row=1, col=1)
    for i, label in enumerate(["tau_phi", "tau_theta", "tau_psi"]):
        fig.add_trace(go.Scatter(x=t, y=u[:, i + 1], name=label),
                      row=2, col=1)
    fig.update_yaxes(title_text="N",   row=1, col=1)
    fig.update_yaxes(title_text="N.m", row=2, col=1)
    fig.update_xaxes(title_text="Time [s]", row=2, col=1)
    fig.update_layout(height=540)
    st.plotly_chart(fig, width='stretch')

with tabs[4]:
    wf = res["wind_force"]
    if np.any(wf):
        fig = go.Figure()
        for i, name in enumerate(["Fx", "Fy", "Fz"]):
            fig.add_trace(go.Scatter(x=t, y=wf[:, i], name=name))
        fig.update_layout(height=380, xaxis_title="Time [s]",
                          yaxis_title="Wind force [N]")
        st.plotly_chart(fig, width='stretch')
    else:
        st.info("Wind disturbance is disabled.")

st.caption(
    "Edit the waypoint table, tune gains, then press **Run simulation**. "
    "Press **Play** on the 3D view to watch the flight replay; the HUD "
    "gauges, drone attitude, and shadow update together."
)
