from fastapi import APIRouter
from ..models.schemas import ModeChangeRequest, SimulationControl, PriorityUpdate, SystemMode
from ..core import app_state

router = APIRouter(prefix="/api/control", tags=["control"])


@router.post("/mode")
async def set_mode(req: ModeChangeRequest):
    app_state.controller.set_mode(req.mode)
    return {"ok": True, "mode": req.mode}


@router.post("/failsafe")
async def trigger_failsafe(reason: str = "Manual trigger"):
    app_state.controller.trigger_failsafe(reason)
    return {"ok": True, "mode": SystemMode.FAILSAFE, "reason": reason}


@router.post("/recover")
async def recover():
    app_state.controller.recover_from_failsafe()
    return {"ok": True, "mode": app_state.controller.mode}


@router.post("/simulation")
async def simulation_control(req: SimulationControl):
    if req.action == "start":
        if not app_state.simulator.is_running:
            await app_state.simulator.start()
    elif req.action == "stop":
        await app_state.simulator.stop()
    elif req.action == "reset":
        app_state.simulator.reset()
    if req.speed is not None:
        app_state.simulator.set_speed(req.speed)
    return {"ok": True, "action": req.action, "running": app_state.simulator.is_running}


@router.post("/priorities")
async def update_priorities(update: PriorityUpdate):
    app_state.controller._direction_priorities.update(update.direction_priorities)
    return {"ok": True, "priorities": app_state.controller._direction_priorities}


@router.get("/status")
async def get_status():
    return {
        "mode": app_state.controller.mode.value,
        "uptime": round(app_state.controller.uptime, 1),
        "phase_switches": app_state.controller.phase_switches,
        "failsafe_reason": app_state.controller.failsafe_reason,
        "simulation_running": app_state.simulator.is_running,
        "lights_count": len(app_state.controller.get_lights()),
        "intersection_loaded": app_state.intersection is not None,
    }
