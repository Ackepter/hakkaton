from fastapi import APIRouter, HTTPException
from ..models.schemas import IntersectionConfig
from ..core import app_state

router = APIRouter(prefix="/api/intersection", tags=["intersection"])


@router.get("", response_model=IntersectionConfig)
async def get_intersection():
    if not app_state.intersection:
        return IntersectionConfig()
    return app_state.intersection


@router.post("", response_model=IntersectionConfig)
async def save_intersection(config: IntersectionConfig):
    app_state.load_intersection(config)
    app_state.save_config_to_file()
    return config


@router.delete("")
async def clear_intersection():
    app_state.intersection = None
    return {"ok": True}
