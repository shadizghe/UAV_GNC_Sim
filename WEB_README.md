# Drone Flight Control - Web App (Phases 1-5)

A two-tier rewrite of the Streamlit dashboard:

```
src/                ← simulator (untouched)
backend/            ← FastAPI service exposing /api/{presets,simulate}
web/                ← Next.js 15 + React + TS + Tailwind + react-three-fiber
app.py              ← legacy Streamlit dashboard (still works)
```

## What Phase 1 ships

- **FastAPI** wraps the existing simulator with two endpoints:
  - `GET  /api/presets`            → list mission scenarios
  - `GET  /api/presets/{label}`    → full mission spec (waypoints, zones, enemies)
  - `POST /api/simulate`           → run closed-loop sim, return time series
  - `WS   /api/monte-carlo/ws`     → stream Monte Carlo dispersion runs and CEP summaries
  - Auto-generated OpenAPI docs at <http://localhost:8000/docs>
- **Next.js** dashboard with:
  - Dark ops-tactical theme (mirrors the Streamlit palette)
  - Top bar with brand, current scenario, live status pill
  - Left sidebar: preset picker, performance metrics, EKF metrics
  - Main pane: full-screen `react-three-fiber` 3D scene with
    waypoints, planned path, flown path, geofence cylinders,
    enemy drones with detection spheres, and a stylised quadrotor.
  - Compass rose, infinite ground grid, animated waypoint diamonds

Round-trip: pick a preset in the sidebar → POST `/api/simulate` →
the flown trajectory streams back as JSON → the 3D scene re-renders.

## Setup

### 1) Backend (FastAPI)

From the project root, with the existing virtualenv activated:

```bash
# install API deps (one-off)
.venv/Scripts/python.exe -m pip install -r backend/requirements.txt

# start the API on :8000
.venv/Scripts/python.exe -m uvicorn backend.main:app --reload --port 8000
```

Hit <http://localhost:8000/docs> to explore the API interactively.

### 2) Frontend (Next.js)

In a second terminal, from `web/`:

```bash
cd web
npm install         # one-off, ~30 s
npm run dev         # serves on http://localhost:3000
```

Open <http://localhost:3000>. The app auto-loads the first preset and
renders the scene; click any preset in the sidebar to swap.

### Environment

The frontend talks to `NEXT_PUBLIC_API_BASE` (default
`http://localhost:8000`). To point it at a deployed backend:

```bash
NEXT_PUBLIC_API_BASE=https://api.your-host.com npm run dev
```

## Roadmap (next phases)

- **Phase 2**: Mission Plan port — 3D draggable waypoints, full waypoint
  table with computed columns, scenario presets UI parity.
- **Phase 3**: Tactical Map port — canvas radar with playback, drag,
  Add-to-Scenario panel.
- **Phase 4**: Telemetry — Plotly time-series tabs, threat analysis,
  EKF true/measured/estimated overlay, animated flight replay.
- **Phase 5**: Monte Carlo — WebSocket-streamed dispersion sweep,
  CEP rings on the tactical map, animated sweep-run playback, and draggable
  launch drone editing. **Ported in web workspace.**
- **Simulation Room**: 3D room lighting/camera presets, launch drone controls,
  and entity roster edits for deleting waypoints, zones, and bandits or changing
  bandit behavior between patrol, loiter, and pursue. Bandits and zones can
  also be selected and dragged directly in the 3D room. Drone dynamics controls
  expose speed cap, XY acceleration, max tilt, and mass.

The Streamlit `app.py` will keep running in parallel until the web
app reaches feature parity, so the demo never goes dark mid-migration.
