"""Simulation endpoint."""

from fastapi import APIRouter

from ..schemas import SimRequest, SimResponse
from ..sim_runner import run_simulation

router = APIRouter(prefix="/api/simulate", tags=["simulate"])


@router.post("", response_model=SimResponse)
def simulate(req: SimRequest) -> SimResponse:
    return run_simulation(req)
