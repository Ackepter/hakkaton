from fastapi import APIRouter, HTTPException
from typing import List
from ..models.schemas import ManualLightCommand, LightPhasesUpdate, TrafficLightConfig, SystemMode
from ..core import app_state

router = APIRouter(prefix="/api/lights", tags=["lights"])


@router.get("")
async def get_lights():
    return app_state.controller.get_light_states()


@router.post("/manual")
async def manual_control(cmd: ManualLightCommand):
    if app_state.controller.mode != SystemMode.MANUAL:
        raise HTTPException(400, "System must be in MANUAL mode to use manual control")
    ok = app_state.controller.manual_set_light(cmd.light_id, cmd.state)
    if not ok:
        raise HTTPException(404, f"Light {cmd.light_id} not found")
    return {"ok": True, "light_id": cmd.light_id, "state": cmd.state}


@router.put("/phases")
async def update_phases(update: LightPhasesUpdate):
    lights = app_state.controller.get_lights()
    if update.light_id not in lights:
        raise HTTPException(404, f"Light {update.light_id} not found")
    lights[update.light_id].set_phases(update.phases)
    return {"ok": True}
