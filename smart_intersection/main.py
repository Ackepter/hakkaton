"""
Smart Intersection microservice entry point.
Runs on port 8001 by default.
"""
import logging
import os
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .engine.simulation import SimulationEngine
from .api.routes import router, set_engine, set_store
from .layout import LayoutStore, default_layout, validate_layout

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    store = LayoutStore(os.environ.get("SI_LAYOUT_DIR", str(Path(__file__).resolve().parents[1] / "config" / "layouts")))
    layout = store.last() or default_layout()
    if validate_layout(layout):
        logger.warning("Stored layout is invalid, using the default one")
        layout = default_layout()
    engine = SimulationEngine(seed=42, layout=layout)
    set_engine(engine)
    set_store(store)
    app.state.engine = engine
    logger.info("Smart Intersection microservice started")
    yield
    await engine.stop()
    logger.info("Smart Intersection microservice stopped")


app = FastAPI(
    title="Smart Intersection Simulation API",
    description="Physics-based intersection simulation with XML data exchange",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("smart_intersection.main:app", host="0.0.0.0", port=8001, reload=False)
