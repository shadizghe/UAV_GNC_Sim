"""Mission preset endpoints."""

from fastapi import APIRouter, HTTPException

from src.guidance import list_presets, get_preset
from ..schemas import PresetSummary, PresetDetail, ZonePayload, EnemyPayload

router = APIRouter(prefix="/api/presets", tags=["presets"])


def _summary(p: dict) -> PresetSummary:
    return PresetSummary(
        label=p["label"], tag=p["tag"], description=p["description"],
        duration_s=p["duration_s"],
        n_waypoints=len(p["waypoints"]),
        n_zones=len(p["zones"]),
        n_enemies=len(p["enemies"]),
        enable_threats=p.get("enable_threats", True),
        enable_geofence=p.get("enable_geofence", True),
    )


def _detail(p: dict) -> PresetDetail:
    return PresetDetail(
        **_summary(p).model_dump(),
        waypoints=[list(w) for w in p["waypoints"]],
        yaws_deg=list(p["yaws_deg"]),
        zones=[ZonePayload(**z) for z in p["zones"]],
        enemies=[EnemyPayload(**e) for e in p["enemies"]],
    )


@router.get("", response_model=list[PresetSummary])
def list_all_presets() -> list[PresetSummary]:
    return [_summary(p) for p in list_presets()]


@router.get("/{label}", response_model=PresetDetail)
def get_preset_detail(label: str) -> PresetDetail:
    p = get_preset(label)
    if p is None:
        raise HTTPException(status_code=404, detail=f"Unknown preset: {label!r}")
    return _detail(p)
