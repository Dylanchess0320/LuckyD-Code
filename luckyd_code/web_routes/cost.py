"""Cost tracking route."""

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/api/cost")
async def get_cost(request: Request):
    from ..cost_tracker import CostTracker
    tracker = CostTracker()
    return tracker.get_stats()
