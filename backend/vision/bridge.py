"""
Simulation Mode feedback channel: camera-derived demand -> Smart Intersection signal logic (Task 55).

In Simulation Mode the chain is  SI -> virtual camera -> detection -> traffic analysis -> (this bridge) -> SI signals.
With real hardware the last hop is the local TrafficController instead; the analysis code is identical.
Delivery is best effort: an unreachable simulation must never disturb the vision pipeline.
"""
import asyncio
import logging
import time
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)


class SimulationBridge:
    def __init__(self, base_url: str, min_interval_s: float = 0.2, client: Optional[httpx.AsyncClient] = None):
        self._client = client or httpx.AsyncClient(base_url=base_url, timeout=1.0, trust_env=False)
        self.min_interval_s = min_interval_s
        self._last_push = 0.0
        self._last_ok: Optional[bool] = None
        self._lock = asyncio.Lock()
        self._generation = 0            # bumped by every forced (health) update
        self.pushes = 0

    async def push(self, payload: Dict[str, Any], force: bool = False) -> bool:
        """Deliver in order: a forced (health) update always has the last word; older pushes are dropped."""
        now = time.monotonic()
        if not force and now - self._last_push < self.min_interval_s:
            return False
        self._last_push = now
        if force:
            self._generation += 1
        mine = self._generation
        async with self._lock:
            if mine != self._generation:            # a newer health update overtook this one
                return False
            return await self._send(payload)

    async def _send(self, payload: Dict[str, Any]) -> bool:
        try:
            r = await self._client.post("/perception", json=payload)
            ok = r.status_code == 200
        except httpx.HTTPError as e:
            ok = False
            if self._last_ok is not False:
                logger.warning("Simulation unreachable, perception not delivered: %s", e)
        if ok and self._last_ok is False:
            logger.info("Simulation perception channel restored")
        self._last_ok = ok
        self.pushes += ok
        return ok

    async def release(self) -> None:
        """Detach from the simulation: it returns to its own ground-truth demand."""
        try:
            await self._client.delete("/perception")
        except httpx.HTTPError:
            pass

    async def close(self) -> None:
        await self._client.aclose()
