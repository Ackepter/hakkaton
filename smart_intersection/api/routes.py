"""
Smart Intersection API routes.
All state lives in the global engine singleton.
"""
import asyncio
import logging
from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from typing import Optional

from ..engine.simulation import SimulationEngine
from ..xml_export.exporter import SimStateExporter
from ..scenarios.presets import SCENARIOS, get_scenario

logger = logging.getLogger(__name__)
router = APIRouter()

# Global engine instance (injected via app.state in main.py)
_engine: Optional[SimulationEngine] = None


def set_engine(engine: SimulationEngine):
    global _engine
    _engine = engine


def _get_engine() -> SimulationEngine:
    if _engine is None:
        raise HTTPException(status_code=503, detail="Simulation engine not initialized")
    return _engine


# ──────────────────── Simulation control ────────────────────

class SimConfig(BaseModel):
    spawn_rate: Optional[float] = Field(None, ge=0, le=200)
    ped_spawn_rate: Optional[float] = Field(None, ge=0, le=200)
    time_scale: Optional[float] = Field(None, ge=0.1, le=20)
    scenario: Optional[str] = None
    control_mode: Optional[str] = Field(None, pattern="^(auto|failsafe)$")


@router.post("/simulation/start")
async def start_simulation():
    engine = _get_engine()
    await engine.start()
    return {"status": engine.status}


@router.post("/simulation/stop")
async def stop_simulation():
    engine = _get_engine()
    await engine.stop()
    return {"status": engine.status}


@router.post("/simulation/pause")
async def pause_simulation():
    engine = _get_engine()
    await engine.pause()
    return {"status": engine.status}


@router.post("/simulation/resume")
async def resume_simulation():
    engine = _get_engine()
    await engine.resume()
    return {"status": engine.status}


@router.post("/simulation/reset")
async def reset_simulation(seed: int = Query(42, ge=0)):
    engine = _get_engine()
    await engine.reset(seed=seed)
    return {"status": engine.status, "seed": engine.seed}


@router.get("/simulation/state")
async def get_simulation_state():
    return _get_engine().get_state()


@router.get("/simulation/config")
async def get_config():
    engine = _get_engine()
    return {
        "spawn_rate": engine._spawn.spawn_rate,
        "ped_spawn_rate": engine._spawn.ped_spawn_rate,
        "time_scale": engine.time_scale,
        "control_mode": engine.control_mode,
        "tick_rate": engine.tick_rate,
        "scenario": engine.scenario,
        "seed": engine.seed,
    }


@router.post("/simulation/config")
async def update_config(cfg: SimConfig):
    engine = _get_engine()
    kwargs = {k: v for k, v in cfg.model_dump().items() if v is not None}
    engine.configure(**kwargs)
    return {"updated": list(kwargs.keys())}


# ──────────────────── Traffic lights ────────────────────

class LightCommand(BaseModel):
    state: str  # RED / YELLOW / GREEN


@router.get("/traffic-lights")
async def get_lights():
    state = _get_engine().get_state()
    return {"lights": state["lights"]}


@router.post("/traffic-lights/{light_id}/state")
async def set_light_state(light_id: str, cmd: LightCommand):
    engine = _get_engine()
    valid = {"RED", "YELLOW", "GREEN", "AUTO"}
    if cmd.state not in valid:
        raise HTTPException(status_code=422, detail=f"state must be one of {sorted(valid)}")
    if not engine.set_light_state(light_id, cmd.state):
        raise HTTPException(status_code=404, detail=f"Unknown traffic light {light_id!r}")
    return {"light_id": light_id, "state": cmd.state}


# ──────────────────── Metrics ────────────────────

@router.get("/metrics")
async def get_metrics():
    state = _get_engine().get_state()
    return state["metrics"]


@router.get("/statistics")
async def get_statistics():
    engine = _get_engine()
    return {
        "summary": engine._metrics.get_summary(),
        "history_len": len(engine._metrics.get_history()),
    }


# ──────────────────── Scenarios ────────────────────

class ScenarioRequest(BaseModel):
    scenario_id: str


@router.post("/scenario/start")
async def start_scenario(req: ScenarioRequest):
    engine = _get_engine()
    try:
        cfg = get_scenario(req.scenario_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))

    await engine.reset(seed=engine.seed)
    cfg.pop("name", None)
    cfg.pop("description", None)
    cfg["scenario"] = req.scenario_id
    engine.configure(**cfg)
    await engine.start()
    return {"scenario": req.scenario_id, "status": engine.status}


@router.post("/scenario/stop")
async def stop_scenario():
    engine = _get_engine()
    await engine.stop()
    return {"status": engine.status}


@router.get("/scenarios")
async def list_scenarios():
    return {k: {"name": v["name"], "description": v["description"]} for k, v in SCENARIOS.items()}


# ──────────────────── XML export ────────────────────

@router.get("/xml/state")
async def get_xml_state():
    from fastapi.responses import Response
    state = _get_engine().get_state()
    xml_str = SimStateExporter.to_xml(state)
    return Response(content=xml_str, media_type="application/xml")


# ──────────────────── Health ────────────────────

@router.get("/health")
async def health():
    engine = _get_engine()
    return {
        "status": "ok",
        "sim_status": engine.status,
        "sim_time": round(engine.sim_time, 2),
        "vehicles": len(engine._vehicles),
        "pedestrians": len(engine._pedestrians),
    }


# ──────────────────── WebSocket ────────────────────

_ws_clients: list = []
WS_INTERVAL_S = 0.1   # matches the engine tick rate so the 3D view can interpolate smoothly


@router.websocket("/ws/state")
async def websocket_state(websocket: WebSocket):
    await websocket.accept()
    _ws_clients.append(websocket)
    logger.info("WS client connected (%d total)", len(_ws_clients))
    try:
        while True:
            await asyncio.sleep(WS_INTERVAL_S)
            if _engine is None:
                continue
            await websocket.send_json(_engine.get_state())
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        if websocket in _ws_clients:
            _ws_clients.remove(websocket)
        logger.info("WS client disconnected (%d remaining)", len(_ws_clients))
