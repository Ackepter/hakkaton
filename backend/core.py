"""
Application state — single instance shared across all routes.
"""
import dataclasses
import json
import logging
import os
from typing import List, Optional

import httpx
import yaml

from .config.settings import settings
from .hardware.mock_gpio import MockGPIO
from .models.schemas import IntersectionConfig
from .traffic.controller import TrafficController
from .simulation.simulator import SimulationEngine
from .metrics.collector import MetricsCollector
from .vision import CameraConfig, VisionManager, Zone, build_manager, load_cameras, perception_payload
from .vision.sim_view import SimView
from .vision.bridge import SimulationBridge

logger = logging.getLogger(__name__)


class AppState:
    def __init__(self):
        hardware = MockGPIO()
        self.controller = TrafficController(hardware)
        self.simulator = SimulationEngine()
        self.metrics = MetricsCollector()
        self.intersection: Optional[IntersectionConfig] = None
        self._config_path = settings.intersection_config_path
        self.vision: Optional[VisionManager] = None
        self.bridge: Optional[SimulationBridge] = None

    # ---- vision (cameras -> detection -> analysis); optional, never required to run the backend
    async def start_vision(self, configs: Optional[List[CameraConfig]] = None) -> None:
        if not settings.vision_enabled:
            logger.info("Vision disabled (VISION_ENABLED=false)")
            return
        try:
            configs = configs if configs is not None else load_cameras(settings.vision_config_path, settings)
        except (ValueError, OSError, yaml.YAMLError) as e:
            logger.error("Camera configuration is invalid, vision not started: %s", e)
            return
        for c in configs:
            if c.source == "simulation" and not c.uri:
                c.uri = settings.si_base_url
        if settings.vision_push_to_simulation and any(c.source == "simulation" for c in configs):
            self.bridge = SimulationBridge(settings.si_base_url)
        self.vision = build_manager(configs, ped_priority_threshold=settings.pedestrian_priority_threshold,
                                    on_health=self._vision_health, on_snapshot=self._vision_snapshot)
        await self.vision.start()
        logger.info("Vision started: %s", ", ".join(f"{p.cfg.id}({p.cfg.source}/{p.cfg.detector})"
                                                    for p in self.vision.pipelines.values()) or "no cameras")

    async def stop_vision(self) -> None:
        if self.vision:
            await self.vision.stop()
        if self.bridge:
            await self.bridge.release()
            await self.bridge.close()
        self.vision = self.bridge = None
        self.controller.set_data_health(True)

    # ---- constructor: cameras placed in the simulation layout become vision cameras
    async def _fetch_layout(self) -> Optional[dict]:
        try:
            async with httpx.AsyncClient(base_url=settings.si_base_url, timeout=2.0, trust_env=False) as c:
                r = await c.get("/layout")
                return r.json() if r.status_code == 200 else None
        except (httpx.HTTPError, ValueError):
            return None

    async def _fetch_geometry(self) -> Optional[dict]:
        try:
            async with httpx.AsyncClient(base_url=settings.si_base_url, timeout=2.0, trust_env=False) as c:
                r = await c.get("/geometry")
                return r.json() if r.status_code == 200 else None
        except (httpx.HTTPError, ValueError):
            return None

    def desired_cameras(self, layout: dict, geometry: dict) -> List[CameraConfig]:
        """
        Camera configs for this layout: yaml cameras + layout cameras. Every camera gets the road zones it really sees:
        the lane approaches and crosswalks of `geometry` projected through its mount (position, height, heading, tilt, FOV).
        """
        base = load_cameras(settings.vision_config_path, settings)
        box = geometry["box_half"]
        others = [c for c in base if c.source != "simulation"]
        template = next((c for c in base if c.source == "simulation"), None)
        placed = [c for c in layout.get("cameras", []) if c.get("enabled", True)]
        sims = []
        if placed:
            for lc in placed:
                cfg = dataclasses.replace(template) if template else CameraConfig()
                cfg.id, cfg.name, cfg.source, cfg.detector = lc["id"], f"Camera {lc['id']}", "simulation", "virtual"
                cfg.x, cfg.z, cfg.range_m = lc["x"], lc["z"], lc.get("radius_m")
                cfg.height_m, cfg.fov_deg = lc.get("height_m"), lc.get("fov_deg")
                cfg.yaw_deg, cfg.pitch_deg = lc.get("yaw_deg"), lc.get("pitch_deg")
                sims.append(cfg)
        elif template is not None:
            sims.append(dataclasses.replace(template))
        assigned: set = set()
        for cfg in sims + [c for c in others if c.x is not None and not c.zones]:      # real cameras with a known mount too
            if cfg.source == "simulation":
                cfg.uri = cfg.uri or settings.si_base_url
            zones = SimView(cfg.width, cfg.height, cfg.pose(box), geometry).zones(skip=assigned)
            assigned |= {z.id for z in zones}            # every zone is watched by one camera only (no double counting)
            cfg.zones = zones or [Zone("no-zones", "lane", [(-1, -1), (-1, -1), (-1, -1)], None)]
        return others + sims

    async def sync_layout_cameras(self) -> Optional[dict]:
        """Bring the running cameras in line with the simulation layout. None = simulation unreachable."""
        layout = await self._fetch_layout()
        geometry = await self._fetch_geometry() if layout is not None else None
        if layout is None or geometry is None:
            return None
        desired = self.desired_cameras(layout, geometry)
        def sig(cfg, zone_ids):
            return (cfg.id, cfg.source, cfg.uri, cfg.x, cfg.z, cfg.height_m, cfg.yaw_deg, cfg.pitch_deg, cfg.fov_deg,
                    cfg.range_m, cfg.width, cfg.height, frozenset(zone_ids))
        running = {sig(p.cfg, (z.id for z in p.analyzer.zones) if p.cfg.zones or p.cfg.source == "simulation" else ())
                   for p in self.vision.pipelines.values()} if self.vision else None
        wanted = {sig(c, (z.id for z in c.zones)) for c in desired if c.enabled}
        if running is not None and running == wanted:
            return {"changed": False, "cameras": [p.cfg.id for p in self.vision.pipelines.values()]}
        await self.stop_vision()
        await self.start_vision(desired)
        return {"changed": True, "cameras": [c.id for c in desired]}

    async def _vision_health(self, healthy: bool, reason: str) -> None:
        self.controller.set_data_health(healthy, reason)
        if not healthy and self.bridge:
            await self.bridge.push(perception_payload(None, False), force=True)

    async def _vision_snapshot(self, snap, healthy: bool) -> None:
        if self.bridge:
            await self.bridge.push(perception_payload(snap, healthy))

    def load_intersection(self, config: IntersectionConfig) -> None:
        self.intersection = config
        self.controller.load_config(config)

        lane_ids = [l.id for l in config.lanes]
        crossing_ids = [c.id for c in config.pedestrian_crossings]
        lane_to_light: dict = {}
        for tl in config.traffic_lights:
            for lane_id in tl.lane_ids:
                lane_to_light[lane_id] = tl.id
        self.simulator.configure(lane_ids, crossing_ids, lane_to_light)
        logger.info(f"Intersection loaded: {config.name}")

    def save_config_to_file(self) -> None:
        if not self.intersection:
            return
        os.makedirs(os.path.dirname(self._config_path), exist_ok=True)
        with open(self._config_path, "w", encoding="utf-8") as f:
            json.dump(self.intersection.model_dump(), f, indent=2, ensure_ascii=False)
        logger.info(f"Config saved to {self._config_path}")

    def load_config_from_file(self) -> bool:
        if not os.path.exists(self._config_path):
            return False
        try:
            with open(self._config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            config = IntersectionConfig(**data)
            self.load_intersection(config)
            logger.info(f"Config loaded from {self._config_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            return False


app_state = AppState()
