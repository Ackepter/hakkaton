from fastapi import APIRouter, Query
from ..core import app_state

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


@router.get("")
async def get_metrics():
    return app_state.metrics.get_latest()


@router.get("/history")
async def get_history(seconds: int = Query(default=60, ge=10, le=300)):
    return app_state.metrics.get_history(seconds)


@router.get("/chart/{metric}")
async def get_chart_data(metric: str, seconds: int = Query(default=60, ge=10, le=300)):
    return app_state.metrics.get_chart_data(metric, seconds)
