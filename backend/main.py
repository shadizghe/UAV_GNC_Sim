"""
FastAPI entry-point for the Drone Flight Control web app.

Run from the project root:

    uvicorn backend.main:app --reload --port 8000

OpenAPI docs are auto-mounted at http://localhost:8000/docs.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import monte_carlo, presets, simulate


app = FastAPI(
    title="Drone Flight Control API",
    version="0.1.0",
    description=(
        "REST surface over the quadrotor GNC simulator. Exposes the mission "
        "preset catalogue and a closed-loop simulation runner so a Next.js "
        "frontend (or any other client) can drive the same engine that powers "
        "the legacy Streamlit dashboard."
    ),
)

# Allow the Next.js dev server (and a few common deploy targets) to call us
# from a different origin without CORS pre-flight failures.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
    ],
    allow_origin_regex=r"^http://(localhost|127\.0\.0\.1):30\d\d$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok"}


app.include_router(presets.router)
app.include_router(simulate.router)
app.include_router(monte_carlo.router)
