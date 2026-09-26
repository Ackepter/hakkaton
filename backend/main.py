import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

from .config.settings import settings
from .api import intersection_router, lights_router, control_router, metrics_router
from .core import app_state
from .models.schemas import IntersectionConfig, SystemMode

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

connected_clients: list[WebSocket] = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Smart Intersection backend...")

    # Load saved intersection config
    app_state.load_config_from_file()

    # Start traffic controller
    await app_state.controller.start()

    # Start simulation
    await app_state.simulator.start()

    # Start background broadcast task
    broadcast_task = asyncio.create_task(broadcast_loop())

    logger.info(f"Backend ready on http://{settings.host}:{settings.port}")
    yield

    # Shutdown
    broadcast_task.cancel()
    await app_state.simulator.stop()
    await app_state.controller.stop()
    logger.info("Backend shutdown complete")


app = FastAPI(
    title="Smart Intersection API",
    description="Web-based smart traffic intersection management system",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(intersection_router)
app.include_router(lights_router)
app.include_router(control_router)
app.include_router(metrics_router)


async def broadcast_loop():
    """Send real-time updates to all WebSocket clients every 500ms."""
    while True:
        try:
            if connected_clients:
                # Gather current state
                traffic_data = app_state.simulator.get_traffic_data()
                light_states = app_state.controller.get_light_states()

                # Update light states in simulator
                app_state.simulator.update_light_states(
                    {l["id"]: l["state"] for l in light_states}
                )

                # Update controller traffic data (for AUTO mode decisions)
                app_state.controller.update_traffic_data(traffic_data)

                # Update metrics
                app_state.metrics.update(
                    traffic_data=traffic_data,
                    light_states=light_states,
                    mode=app_state.controller.mode,
                    phase_switches=app_state.controller.phase_switches,
                    failsafe_reason=app_state.controller.failsafe_reason,
                )

                payload = {
                    "type": "state_update",
                    "ts": time.time(),
                    "mode": app_state.controller.mode.value,
                    "failsafe_reason": app_state.controller.failsafe_reason,
                    "lights": light_states,
                    "metrics": app_state.metrics.get_latest(),
                    "simulation_running": app_state.simulator.is_running,
                }

                msg = json.dumps(payload)
                dead = []
                for ws in connected_clients:
                    try:
                        await ws.send_text(msg)
                    except Exception:
                        dead.append(ws)
                for ws in dead:
                    connected_clients.remove(ws)
        except Exception as e:
            logger.error(f"Broadcast error: {e}")

        await asyncio.sleep(0.5)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_clients.append(websocket)
    logger.info(f"WebSocket client connected ({len(connected_clients)} total)")
    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                await handle_ws_message(msg, websocket)
            except Exception as e:
                await websocket.send_text(json.dumps({"type": "error", "message": str(e)}))
    except WebSocketDisconnect:
        connected_clients.remove(websocket)
        logger.info(f"WebSocket client disconnected ({len(connected_clients)} total)")


async def handle_ws_message(msg: dict, ws: WebSocket):
    """Handle incoming WebSocket commands from frontend."""
    mtype = msg.get("type")
    if mtype == "ping":
        await ws.send_text(json.dumps({"type": "pong"}))
    elif mtype == "set_mode":
        mode = SystemMode(msg["mode"])
        app_state.controller.set_mode(mode)
    elif mtype == "manual_light":
        from .models.schemas import LightState
        app_state.controller.manual_set_light(msg["light_id"], LightState(msg["state"]))
    elif mtype == "simulation_control":
        action = msg.get("action")
        if action == "start" and not app_state.simulator.is_running:
            await app_state.simulator.start()
        elif action == "stop":
            await app_state.simulator.stop()
        elif action == "reset":
            app_state.simulator.reset()


@app.get("/api/health")
async def health():
    return {"status": "ok", "mode": app_state.controller.mode.value}


# Serve frontend static files if built
frontend_dist = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.isdir(frontend_dist):
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
