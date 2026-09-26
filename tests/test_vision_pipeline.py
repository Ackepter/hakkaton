"""Pipeline behaviour: health, FAILSAFE triggers, reconnect, error isolation, rendering."""
import asyncio
import io

import pytest
from PIL import Image

from backend.vision.config import CameraConfig
from backend.vision.pipeline import VisionManager, build_manager
from .vision_helpers import FakeDetector, FakeSource, make_pipeline, wait_for


@pytest.fixture
async def running():
    pipes = []

    async def start(p):
        pipes.append(p)
        await p.start()
        return p
    yield start
    for p in pipes:
        await p.stop()


async def test_healthy_camera_produces_frames_detections_and_snapshot(running):
    p = await running(make_pipeline())
    assert await wait_for(lambda: p.snapshot is not None and p.frames >= 3)
    assert p.camera_state == "connected" and p.healthy and p.detector_state == "ok"
    assert p.snapshot.vehicles == 1 and p.snapshot.pedestrians == 1
    assert p.status()["fps"] > 5 and p.status()["last_frame_age_s"] < 0.5


async def test_lost_signal_becomes_unhealthy_only_after_the_timeout_and_recovers(running):
    events = []
    p = make_pipeline(on_health=lambda cid, ok, why: events.append((ok, why)))
    src = p.source
    await running(p)
    assert await wait_for(lambda: p.frames >= 3)
    src.mode = "none"                                     # cable pulled: read() returns nothing
    assert await wait_for(lambda: p.camera_state == "no_signal")
    assert p.healthy                                      # a brief drop is tolerated
    assert await wait_for(lambda: not p.healthy)          # timeout_s = 0.3
    assert events[-1][0] is False and "no signal" in events[-1][1]
    await asyncio.sleep(0.4)                              # several reconnect attempts later ...
    assert p.camera_state == "no_signal" and src.open_calls >= 2   # ... it is still "no signal", not "connecting"
    src.mode = "ok"
    assert await wait_for(lambda: p.healthy)
    assert [ok for ok, _ in events] == [False, True]      # exactly one transition each way, no flapping


async def test_read_exceptions_do_not_kill_the_loop_and_the_camera_reopens(running):
    p = make_pipeline()
    src = p.source
    await running(p)
    assert await wait_for(lambda: p.frames >= 2)
    src.mode = "raise"
    assert await wait_for(lambda: p.camera_state == "error")
    assert "usb glitch" in p.camera_error and not p.healthy
    src.mode = "ok"
    assert await wait_for(lambda: p.camera_state == "connected" and p.healthy)
    assert src.open_calls >= 2 and src.closed >= 1        # source was closed and re-opened


async def test_camera_that_cannot_be_opened_is_retried_and_reports_the_reason(running):
    p = make_pipeline(source=FakeSource(CameraConfig(id="CAM-T", fps=100, width=64, height=48, timeout_s=0.3,
                                                     reconnect_s=0.05), fail_open=2))
    await running(p)
    assert await wait_for(lambda: p.camera_state == "error")
    assert "device busy" in p.camera_error
    assert await wait_for(lambda: p.camera_state == "connected")     # third attempt succeeds
    assert p.source.open_calls == 3 and p.camera_error is None and p.healthy


async def test_camera_never_available_becomes_unhealthy_after_the_grace_period(running):
    cfg = CameraConfig(id="CAM-T", fps=100, width=64, height=48, timeout_s=0.2, reconnect_s=0.05)
    p = make_pipeline(cfg, source=FakeSource(cfg, fail_open=10_000))
    await running(p)
    assert p.healthy                                      # grace period: no FAILSAFE flash at start-up
    assert await wait_for(lambda: not p.healthy)


async def test_detector_unavailable_keeps_the_image_but_reports_failsafe_condition(running):
    det = FakeDetector()
    det.mode = "unavailable"
    p = make_pipeline(detector=det)
    await running(p)
    assert await wait_for(lambda: not p.healthy)
    assert p.camera_state == "connected" and p.frame is not None            # image still displayed
    assert "detector failure" in p.reason and p.detector_state == "unavailable"
    Image.open(io.BytesIO(p.render()))                                       # still renders a JPEG
    det.mode = "ok"
    assert await wait_for(lambda: p.healthy)


async def test_detector_errors_are_reported_and_clear_when_inference_works_again(running):
    det = FakeDetector()
    p = make_pipeline(detector=det)
    await running(p)
    assert await wait_for(lambda: p.snapshot is not None)
    det.mode = "error"
    assert await wait_for(lambda: p.detector_state == "error")
    det.mode = "ok"
    assert await wait_for(lambda: p.healthy and p.detector_state == "ok")


async def test_manual_disconnect_and_connect(running):
    events = []
    p = make_pipeline(on_health=lambda cid, ok, why: events.append(ok))
    await running(p)
    assert await wait_for(lambda: p.frames >= 2)
    await p.disconnect()
    assert p.camera_state == "disconnected" and not p.healthy and p.frame is None and p.reason == "camera disconnected"
    assert p.source.closed >= 1
    await asyncio.sleep(0.1)
    assert p.camera_state == "disconnected"               # loop must not silently reconnect
    await p.connect()
    assert await wait_for(lambda: p.healthy and p.camera_state == "connected")
    assert events == [False, True]


async def test_placeholder_is_rendered_instead_of_a_stale_frame_when_signal_is_lost(running):
    p = make_pipeline()
    await running(p)
    assert await wait_for(lambda: p.frames >= 2)
    live = p.render()
    p.source.mode = "none"
    assert await wait_for(lambda: p.camera_state == "no_signal")
    stale = p.render()
    assert stale != live
    await p.disconnect()
    assert Image.open(io.BytesIO(p.render())).size == (64, 48)


async def test_overlay_draws_boxes_and_zones_only_when_asked(running):
    p = make_pipeline()
    await running(p)
    assert await wait_for(lambda: p.snapshot is not None)
    plain = Image.open(io.BytesIO(p.render(overlay=False))).convert("RGB")
    boxed = Image.open(io.BytesIO(p.render(overlay=True))).convert("RGB")
    zoned = Image.open(io.BytesIO(p.render(overlay=True, zones=True))).convert("RGB")
    assert len(plain.getcolors(1000)) <= 2                                                     # flat background
    assert len(boxed.getcolors(5000)) > len(plain.getcolors(5000))                             # boxes add colours
    assert zoned.tobytes() != boxed.tobytes()


async def test_render_is_cached_per_frame(running):
    p = make_pipeline()
    await running(p)
    assert await wait_for(lambda: p.frame is not None)
    p.source.mode = "none"
    await asyncio.sleep(0.05)
    a = p.render()
    assert p.render() is a


async def test_status_never_leaks_stream_credentials():
    cfg = CameraConfig(id="N", source="network", uri="rtsp://admin:hunter2@10.0.0.5/stream")
    p = make_pipeline(cfg, source=FakeSource(cfg))
    assert "hunter2" not in str(p.status()) and "//***@10.0.0.5" in p.status()["uri"]


# ---------------------------------------------------------------- manager

async def test_manager_aggregates_health_and_reports_transitions_once(running):
    events = []
    a, b = make_pipeline(), make_pipeline(CameraConfig(id="CAM-B", fps=100, width=64, height=48, timeout_s=0.3,
                                                       reconnect_s=0.1))
    mgr = VisionManager([a, b], on_health=lambda ok, why: events.append((ok, why)))
    await mgr.start()
    try:
        assert await wait_for(lambda: a.frames >= 2 and b.frames >= 2)
        assert mgr.healthy and mgr.reason == "ok"
        b.source.mode = "none"
        assert await wait_for(lambda: not mgr.healthy)
        assert "CAM-B" in mgr.reason and "CAM-T" not in mgr.reason
        b.source.mode = "ok"
        assert await wait_for(lambda: mgr.healthy)
        assert [ok for ok, _ in events] == [False, True]
    finally:
        await mgr.stop()


async def test_manager_snapshot_only_uses_healthy_cameras_and_status_is_json_ready():
    import json
    p = make_pipeline()
    mgr = VisionManager([p])
    await mgr.start()
    try:
        assert await wait_for(lambda: p.snapshot is not None)
        assert mgr.snapshot().vehicles == 1
        st = mgr.status()
        json.dumps(st)
        assert st["active"] and st["healthy"] and st["cameras"][0]["id"] == "CAM-T" and st["analysis"]["vehicles"] == 1
        await p.disconnect()
        assert mgr.snapshot() is None                     # nothing from an unhealthy camera reaches the controller
    finally:
        await mgr.stop()


async def test_manager_snapshot_callback_receives_health_flag():
    got = []
    p = make_pipeline()
    mgr = VisionManager([p], on_snapshot=lambda snap, healthy: got.append((snap.vehicles, healthy)))
    await mgr.start()
    try:
        assert await wait_for(lambda: len(got) >= 3)
        assert all(v == 1 and h is True for v, h in got)
    finally:
        await mgr.stop()


async def test_async_callbacks_are_supported():
    events = []

    async def on_health(ok, why):
        events.append(ok)
    p = make_pipeline()
    mgr = VisionManager([p], on_health=on_health)
    await mgr.start()
    try:
        assert await wait_for(lambda: p.frames >= 2)
        await p.disconnect()
        assert events == [False]
    finally:
        await mgr.stop()


def test_empty_manager_is_inactive_not_an_error():
    mgr = VisionManager([])
    assert not mgr.active and not mgr.healthy and mgr.snapshot() is None and mgr.status()["cameras"] == []
    with pytest.raises(KeyError):
        mgr.get("nope")


def test_build_manager_skips_disabled_cameras_and_uses_simulation_zones():
    mgr = build_manager([CameraConfig(id="A", source="simulation", enabled=True),
                         CameraConfig(id="B", source="simulation", enabled=False)])
    assert list(mgr.pipelines) == ["A"]
    assert {z.id for z in mgr.get("A").analyzer.zones} >= {"north-in", "PC-N"}
