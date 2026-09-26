"""SimulationBridge: ordering, throttling, failure isolation."""
import asyncio
import json

import httpx

from backend.vision.bridge import SimulationBridge


def make_bridge(handler, **kw):
    client = httpx.AsyncClient(base_url="http://si.test", transport=httpx.MockTransport(handler))
    return SimulationBridge("http://si.test", client=client, **kw)


async def test_pushes_are_throttled_but_forced_updates_always_go_through():
    seen = []

    async def handler(req):
        seen.append(json.loads(req.content))
        return httpx.Response(200, json={})
    b = make_bridge(handler, min_interval_s=10.0)
    assert await b.push({"n": 1}) is True
    assert await b.push({"n": 2}) is False                # throttled
    assert await b.push({"n": 3}, force=True) is True
    assert [s["n"] for s in seen] == [1, 3]


async def test_a_late_healthy_update_can_never_overwrite_camera_lost():
    """Regression: an in-flight snapshot push must not reach the simulation after the 'camera lost' push."""
    seen = []
    gate = asyncio.Event()

    async def handler(req):
        body = json.loads(req.content)
        if body["tag"] == "first":
            await gate.wait()                             # a slow request is on the wire
        seen.append(body["tag"])
        return httpx.Response(200, json={})
    b = make_bridge(handler, min_interval_s=0.0)
    first = asyncio.create_task(b.push({"tag": "first", "camera_ok": True}))
    await asyncio.sleep(0.01)
    late = asyncio.create_task(b.push({"tag": "late", "camera_ok": True}))       # queued behind the first
    lost = asyncio.create_task(b.push({"tag": "lost", "camera_ok": False}, force=True))
    await asyncio.sleep(0.01)
    gate.set()
    await asyncio.gather(first, late, lost)
    assert seen[-1] == "lost" and "late" not in seen


async def test_unreachable_simulation_is_not_an_error():
    def handler(req):
        raise httpx.ConnectError("refused")
    b = make_bridge(handler, min_interval_s=0.0)
    assert await b.push({"x": 1}) is False and await b.push({"x": 2}, force=True) is False
    await b.release()                                     # must not raise either
    await b.close()


async def test_recovery_after_failure_is_reported_once():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(500) if calls["n"] == 1 else httpx.Response(200, json={})
    b = make_bridge(handler, min_interval_s=0.0)
    assert await b.push({}) is False
    assert await b.push({}) is True and b.pushes == 1
