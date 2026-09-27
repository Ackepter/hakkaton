"""
Smart Intersection API routes.
All state lives in the global engine singleton.
"""
import asyncio
import logging
from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from typing import Dict, Literal, Optional

from ..engine.simulation import SimulationEngine
from ..xml_export.exporter import SimStateExporter
from ..scenarios.presets import SCENARIOS, get_scenario
from ..geometry import scene_geometry
from ..layout import Layout, LayoutStore, junction_types, presets as layout_presets, validate_layout

logger = logging.getLogger(__name__)
router = APIRouter()

# Global engine instance (injected via app.state in main.py)
_engine: Optional[SimulationEngine] = None


_store: Optional[LayoutStore] = None


def set_engine(engine: SimulationEngine):
    global _engine
    _engine = engine


def set_store(store: Optional[LayoutStore]):
    global _store
    _store = store


def _get_store() -> LayoutStore:
    if _store is None:
        raise HTTPException(status_code=503, detail="layout store not initialized")
    return _store


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
    camera_failure: Optional[bool] = None


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


class CameraFailure(BaseModel):
    active: bool


@router.post("/simulation/camera-failure")
async def set_camera_failure(req: CameraFailure):
    """Unplug / re-plug the virtual camera (scenario 'Camera/Detection Failure')."""
    _get_engine().configure(camera_failure=req.active)
    return {"camera_failure": req.active}


class Perception(BaseModel):
    """What the camera pipeline of the main project currently sees (arm -> vehicles in the approach zone)."""
    camera_ok: bool = True
    vehicles: Dict[str, int] = {}
    pedestrians_waiting: Dict[str, int] = {}
    ped_priority: Dict[str, bool] = {}          # crosswalk -> crowd above the configured threshold
    emergency: Dict[str, bool] = {}


@router.post("/perception")
async def push_perception(p: Perception):
    engine = _get_engine()
    engine.set_perception(p.model_dump())
    return {"failsafe_reason": engine.failsafe_reason()}


@router.delete("/perception")
async def clear_perception():
    _get_engine().clear_perception()
    return {"active": False}


# ──────────────────── Constructor: layout ────────────────────

def _check(layout: Layout) -> None:
    errors = validate_layout(layout)
    if errors:
        raise HTTPException(status_code=422, detail=errors)


@router.get("/layout")
async def get_layout():
    return _get_engine().layout.model_dump()


@router.post("/layout/validate")
async def validate(layout: Layout):
    errors = validate_layout(layout)
    return {"valid": not errors, "errors": errors}


@router.put("/layout")
async def apply_layout(layout: Layout):
    """Build the world from a layout. Restarts the simulation (it is stopped, the layout is remembered)."""
    _check(layout)
    engine = _get_engine()
    await engine.apply_layout(layout)
    try:
        store = _get_store()
        store.save(layout)
        store.remember(layout.name)
    except (OSError, HTTPException):
        logger.warning("layout applied but could not be stored", exc_info=True)
    return engine.layout.model_dump()


@router.get("/layout/presets")
async def list_presets():
    return {name: l.model_dump() for name, l in layout_presets().items()}


@router.get("/layout/junction-types")
async def list_junction_types():
    """Catalogue of ready-made junctions (name, kind, what the logic does)."""
    return {"types": junction_types()}


@router.get("/geometry")
async def get_geometry():
    """Road geometry of the current layout (box, lanes, crossings, light poles): what a camera needs to draw and zone the road."""
    return scene_geometry(_get_engine().layout)


@router.get("/layouts")
async def list_layouts():
    return {"saved": _get_store().list(), "presets": sorted(layout_presets())}


@router.post("/layouts")
async def save_layout(layout: Layout):
    _check(layout)
    _get_store().save(layout)
    return {"saved": layout.name}


@router.get("/layouts/{name}")
async def load_layout(name: str):
    try:
        return _get_store().load(name).model_dump()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"no saved layout {name!r}")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.delete("/layouts/{name}")
async def delete_layout(name: str):
    try:
        _get_store().delete(name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"no saved layout {name!r}")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"deleted": name}


class SpawnRequest(BaseModel):
    kind: Literal["vehicle", "pedestrian"]
    arm: Optional[Literal["north", "south", "east", "west"]] = None
    type: str = "car"
    crossing: Optional[str] = None
    lane: Optional[int] = Field(None, ge=0, le=3)                 # inbound lane, 0 = innermost (default: any)
    movement: Optional[Literal["left", "straight", "right", "uturn"]] = None


@router.post("/simulation/spawn")
async def spawn(req: SpawnRequest):
    """Interactive scenario control: add a vehicle on an arm or a pedestrian at a crosswalk right now."""
    engine = _get_engine()
    if req.kind == "vehicle":
        if req.arm is None or f"{req.arm}-in" not in engine._lanes:
            raise HTTPException(status_code=404, detail="that arm does not exist in the current layout")
        v = engine.spawn_vehicle(req.arm, req.type, req.lane, req.movement)
        if v is None:
            raise HTTPException(status_code=409, detail="entry is blocked, the vehicle type is unknown, or that lane / movement "
                                                        "does not exist")
        return {"id": v.id}
    if req.crossing is None or req.crossing not in engine._crossings:
        raise HTTPException(status_code=404, detail="that crosswalk does not exist in the current layout")
    p = engine.spawn_pedestrian(req.crossing)
    return {"id": p.id}


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


# ──────────────────── Pedestrian lights ────────────────────

@router.get("/pedestrian-lights")
async def get_pedestrian_lights():
    state = _get_engine().get_state()
    return {"pedestrian_lights": state["pedestrian_lights"]}


@router.post("/pedestrian-lights/{crossing_id}/state")
async def set_pedestrian_light_state(crossing_id: str, cmd: LightCommand):
    """Manual override of one pedestrian signal (Task 9: MANUAL must be able to force a light; 'AUTO' releases it)."""
    engine = _get_engine()
    valid = {"RED", "YELLOW", "GREEN", "AUTO"}
    if cmd.state not in valid:
        raise HTTPException(status_code=422, detail=f"state must be one of {sorted(valid)}")
    if not engine.set_ped_light_state(crossing_id, cmd.state):
        raise HTTPException(status_code=404, detail=f"Unknown pedestrian crossing {crossing_id!r}")
    return {"crossing_id": crossing_id, "state": cmd.state}


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


@router.get("/sensor/camera-feed")
async def camera_feed():
    """Virtual camera output (XML). 503 while the camera is 'unplugged' so consumers see a real signal loss."""
    engine = _get_engine()
    if engine.camera_failure:
        raise HTTPException(status_code=503, detail="virtual camera unavailable")
    from fastapi.responses import Response
    return Response(content=SimStateExporter.to_xml(engine.get_state()), media_type="application/xml")


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
