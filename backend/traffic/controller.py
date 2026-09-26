import asyncio
import logging
import time
from typing import Dict, List, Optional, Any
from ..models.schemas import SystemMode, LightState, IntersectionConfig, TrafficLightConfig
from ..hardware.base import HardwareInterface
from .light import TrafficLight

logger = logging.getLogger(__name__)


class TrafficController:
    """
    Central controller for all traffic lights.
    Manages AUTO / MANUAL / FAILSAFE modes.
    """

    FAILSAFE_PHASES = [
        {"state": "RED", "duration": 20},
        {"state": "YELLOW", "duration": 3},
        {"state": "GREEN", "duration": 15},
        {"state": "YELLOW", "duration": 3},
    ]

    def __init__(self, hardware: HardwareInterface):
        self._hardware = hardware
        self._lights: Dict[str, TrafficLight] = {}
        self._mode = SystemMode.AUTO
        self._failsafe_reason: Optional[str] = None
        self._running = False
        self._start_time = time.monotonic()
        self._phase_switches = 0
        self._traffic_data: Dict[str, Any] = {}
        self._direction_priorities: Dict[str, float] = {
            "north": 1.0, "south": 1.0, "east": 1.0, "west": 1.0,
        }
        self._pedestrian_priority_threshold = 5
        self._pedestrian_priority_weight = 1.3
        self._task: Optional[asyncio.Task] = None

    def load_config(self, config: IntersectionConfig) -> None:
        """Load intersection config and create/update traffic lights."""
        self._direction_priorities = {**self._direction_priorities, **config.direction_priorities}
        existing_ids = set(self._lights.keys())
        new_ids = {tl.id for tl in config.traffic_lights}

        for tl_id in existing_ids - new_ids:
            del self._lights[tl_id]

        for tl_cfg in config.traffic_lights:
            if tl_cfg.id in self._lights:
                self._lights[tl_cfg.id].set_phases(tl_cfg.phase_sequence)
                self._lights[tl_cfg.id].priority = tl_cfg.priority
            else:
                self._lights[tl_cfg.id] = TrafficLight(
                    light_id=tl_cfg.id,
                    phases=tl_cfg.phase_sequence,
                    direction=tl_cfg.direction.value if tl_cfg.direction else None,
                    lane_ids=tl_cfg.lane_ids,
                    priority=tl_cfg.priority,
                    conflict_ids=tl_cfg.conflict_ids,
                )
        logger.info(f"Controller loaded {len(self._lights)} traffic lights")

    def add_light(self, config: TrafficLightConfig) -> None:
        self._lights[config.id] = TrafficLight(
            light_id=config.id,
            phases=config.phase_sequence,
            direction=config.direction.value if config.direction else None,
            lane_ids=config.lane_ids,
            priority=config.priority,
            conflict_ids=config.conflict_ids,
        )

    @property
    def mode(self) -> SystemMode:
        return self._mode

    @property
    def uptime(self) -> float:
        return time.monotonic() - self._start_time

    @property
    def phase_switches(self) -> int:
        return self._phase_switches

    @property
    def failsafe_reason(self) -> Optional[str]:
        return self._failsafe_reason

    def get_lights(self) -> Dict[str, TrafficLight]:
        return dict(self._lights)

    def get_light_states(self) -> List[Dict]:
        return [light.to_dict() for light in self._lights.values()]

    def set_mode(self, mode: SystemMode, reason: Optional[str] = None) -> None:
        prev = self._mode
        self._mode = mode
        if mode == SystemMode.FAILSAFE:
            self._failsafe_reason = reason or "Unknown reason"
            self._apply_failsafe_phases()
            logger.warning(f"FAILSAFE activated: {self._failsafe_reason}")
        elif mode == SystemMode.AUTO:
            self._failsafe_reason = None
            logger.info("AUTO mode activated")
        elif mode == SystemMode.MANUAL:
            logger.info("MANUAL mode activated")
        if prev != mode:
            logger.info(f"Mode: {prev.value} → {mode.value}")

    def trigger_failsafe(self, reason: str) -> None:
        if self._mode != SystemMode.FAILSAFE:
            self.set_mode(SystemMode.FAILSAFE, reason)

    def recover_from_failsafe(self) -> None:
        if self._mode == SystemMode.FAILSAFE:
            self.set_mode(SystemMode.AUTO)
            logger.info("System recovered from FAILSAFE")

    def _apply_failsafe_phases(self) -> None:
        for light in self._lights.values():
            light.set_phases(self.FAILSAFE_PHASES)

    def manual_set_light(self, light_id: str, state: LightState) -> bool:
        if self._mode != SystemMode.MANUAL:
            logger.warning(f"Manual command rejected — not in MANUAL mode (current: {self._mode.value})")
            return False
        if light_id not in self._lights:
            return False
        self._lights[light_id].force_state(state)
        self._sync_hardware(light_id, state)
        return True

    def _sync_hardware(self, light_id: str, state: LightState) -> None:
        self._hardware.set_light(
            light_id,
            red=(state == LightState.RED),
            yellow=(state == LightState.YELLOW),
            green=(state == LightState.GREEN),
        )

    def update_traffic_data(self, data: Dict[str, Any]) -> None:
        """Receive traffic data from simulation/vision module."""
        self._traffic_data = data

    def _auto_decide(self) -> None:
        """Simple adaptive algorithm: prioritize the most loaded direction."""
        if not self._traffic_data or not self._lights:
            return

        queues = self._traffic_data.get("queues", {})
        if not queues:
            return

        # Calculate pressure score per light
        scores: Dict[str, float] = {}
        for light_id, light in self._lights.items():
            if light.state != LightState.RED:
                continue
            score = 0.0
            for lane_id in light.lane_ids:
                q = queues.get(lane_id, {})
                cars = q.get("cars", 0)
                trucks = q.get("trucks", 0)
                pedestrians = q.get("pedestrians", 0)
                score += (cars + trucks * 1.5) * light.priority
                if pedestrians >= self._pedestrian_priority_threshold:
                    score += pedestrians * self._pedestrian_priority_weight

            direction = light.direction or "north"
            score *= self._direction_priorities.get(direction, 1.0)
            if score > 0:
                scores[light_id] = score

        # Extend green for the highest-pressure red light if it's about to switch
        if scores:
            best_id = max(scores, key=lambda k: scores[k])
            best_light = self._lights[best_id]
            # Will be handled by phase timing — just log for now
            logger.debug(f"Auto: highest pressure on {best_id} (score={scores[best_id]:.1f})")

    async def run(self) -> None:
        """Main control loop."""
        self._running = True
        self._hardware.initialize()
        logger.info("TrafficController started")

        while self._running:
            try:
                await self._tick()
            except Exception as e:
                logger.error(f"Controller tick error: {e}")
            await asyncio.sleep(0.1)

    async def _tick(self) -> None:
        for light_id, light in self._lights.items():
            changed = light.tick()
            if changed:
                self._phase_switches += 1
                self._sync_hardware(light_id, light.state)

            if self._mode == SystemMode.AUTO:
                self._auto_decide()

    async def start(self) -> None:
        self._task = asyncio.create_task(self.run())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._hardware.cleanup()
        logger.info("TrafficController stopped")
