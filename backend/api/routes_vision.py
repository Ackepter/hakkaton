"""
/api/vision/* — cameras, video stream, detections and analysis.
The video endpoints work without any detector; a missing camera is reported, never raised as a server error.
"""
import asyncio
import time
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from ..core import app_state
from ..vision.sources import discover_usb_cameras
from ..vision.types import ALL_CLASSES

router = APIRouter(prefix="/api/vision", tags=["vision"])

BOUNDARY = "frame"


def _pipeline(camera_id: str):
    if app_state.vision is None:
        raise HTTPException(status_code=404, detail="vision is not running")
    try:
        return app_state.vision.get(camera_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown camera {camera_id!r}")


@router.get("/cameras")
async def cameras():
    if app_state.vision is None:
        return {"active": False, "healthy": False, "reason": "vision not running", "cameras": [], "analysis": None}
    return app_state.vision.status()


@router.get("/cameras/{camera_id}")
async def camera(camera_id: str):
    return _pipeline(camera_id).status()


@router.get("/cameras/{camera_id}/snapshot.jpg")
async def snapshot(camera_id: str, overlay: bool = True, zones: bool = False):
    p = _pipeline(camera_id)
    data = await asyncio.to_thread(p.render, overlay, zones)
    return Response(content=data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.get("/cameras/{camera_id}/stream")
async def stream(request: Request, camera_id: str, overlay: bool = True, zones: bool = False):
    """MJPEG stream (multipart/x-mixed-replace) - works in a plain <img> tag."""
    p = _pipeline(camera_id)

    async def frames():
        last, sent_at = None, 0.0
        while not await request.is_disconnected():
            data = await asyncio.to_thread(p.render, overlay, zones)
            if data is not last or time.monotonic() - sent_at > 1.0:      # new picture, or keep-alive
                yield (f"--{BOUNDARY}\r\nContent-Type: image/jpeg\r\nContent-Length: {len(data)}\r\n\r\n").encode() \
                    + data + b"\r\n"
                last, sent_at = data, time.monotonic()
            await asyncio.sleep(1.0 / max(p.cfg.fps, 1.0))

    return StreamingResponse(frames(), media_type=f"multipart/x-mixed-replace; boundary={BOUNDARY}",
                             headers={"Cache-Control": "no-store"})


@router.get("/cameras/{camera_id}/detections")
async def detections(camera_id: str):
    p = _pipeline(camera_id)
    return {"camera": camera_id, "state": p.camera_state, "detections": [d.to_dict() for d in p.detections],
            "analysis": p.snapshot.to_dict() if p.snapshot else None}


@router.post("/cameras/{camera_id}/disconnect")
async def disconnect(camera_id: str):
    p = _pipeline(camera_id)
    await p.disconnect()
    return p.status(detail=False)


@router.post("/cameras/{camera_id}/connect")
async def connect(camera_id: str):
    p = _pipeline(camera_id)
    await p.connect()
    return p.status(detail=False)


class DetectorConfig(BaseModel):
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    classes: Optional[List[str]] = None


@router.patch("/cameras/{camera_id}/config")
async def configure(camera_id: str, cfg: DetectorConfig):
    """Change the confidence threshold and tracked classes of a running camera."""
    p = _pipeline(camera_id)
    unknown = set(cfg.classes or []) - set(ALL_CLASSES)
    if unknown:
        raise HTTPException(status_code=422, detail=f"unknown classes: {sorted(unknown)}")
    p.detector.configure(confidence=cfg.confidence, classes=cfg.classes)
    if cfg.confidence is not None:
        p.cfg.confidence = cfg.confidence
    if cfg.classes is not None:
        p.cfg.classes = list(cfg.classes)
    return p.detector.describe()


@router.get("/analysis")
async def analysis():
    snap = app_state.vision.snapshot() if app_state.vision else None
    return snap.to_dict() if snap else None


@router.post("/sync-layout")
async def sync_layout():
    """Rebuild the simulation cameras from the current simulation layout (call after the constructor applied it)."""
    result = await app_state.sync_layout_cameras()
    if result is None:
        raise HTTPException(status_code=503, detail="simulation service unreachable")
    return result


@router.get("/discover")
async def discover():
    """USB cameras visible to OpenCV (empty when none / OpenCV missing)."""
    found = await asyncio.to_thread(discover_usb_cameras)
    return {"usb": found}
