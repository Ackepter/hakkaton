"""
/api/si/* — proxy to Smart Intersection microservice on port 8001.
Fetches XML state, parses it, returns JSON DTO.
"""
import logging
from fastapi import APIRouter, HTTPException
import httpx

from backend.xml_parser.parser import XmlParser, XmlParseError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/si")

SI_BASE_URL = "http://localhost:8001"
_http_client = httpx.AsyncClient(base_url=SI_BASE_URL, timeout=5.0)


def _dto_to_dict(obj) -> dict:
    """Recursively convert dataclass to dict."""
    import dataclasses
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {k: _dto_to_dict(v) for k, v in dataclasses.asdict(obj).items()}
    if isinstance(obj, list):
        return [_dto_to_dict(i) for i in obj]
    return obj


@router.get("/state")
async def get_si_state():
    """Fetch XML from SI, parse, return as JSON."""
    try:
        resp = await _http_client.get("/xml/state")
        resp.raise_for_status()
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="Smart Intersection service unreachable")
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"SI service error: {e.response.status_code}")

    try:
        data = XmlParser.parse(resp.text)
    except XmlParseError as e:
        raise HTTPException(status_code=502, detail=f"XML parse error: {e}")

    return _dto_to_dict(data)


@router.get("/health")
async def get_si_health():
    """Forward health check to SI service."""
    try:
        resp = await _http_client.get("/health")
        resp.raise_for_status()
        return resp.json()
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="Smart Intersection service unreachable")


@router.post("/simulation/start")
async def si_start():
    try:
        resp = await _http_client.post("/simulation/start")
        return resp.json()
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="Smart Intersection service unreachable")


@router.post("/simulation/stop")
async def si_stop():
    try:
        resp = await _http_client.post("/simulation/stop")
        return resp.json()
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="Smart Intersection service unreachable")


@router.post("/scenario/start")
async def si_scenario_start(scenario_id: str):
    try:
        resp = await _http_client.post("/scenario/start", json={"scenario_id": scenario_id})
        return resp.json()
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="Smart Intersection service unreachable")
