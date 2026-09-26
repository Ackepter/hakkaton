"""
/api/si/* — proxy to the Smart Intersection microservice (port 8001).
Fetches the XML state, validates + parses it, returns a JSON DTO.
"""
import dataclasses
import logging
import os

import httpx
from fastapi import APIRouter, HTTPException

from backend.xml_parser.parser import XmlParser, XmlParseError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/si")

SI_BASE_URL = os.environ.get("SI_BASE_URL", "http://127.0.0.1:8001")
# trust_env=False: system HTTP(S)_PROXY settings must never be applied to a loopback service
_http_client = httpx.AsyncClient(base_url=SI_BASE_URL, timeout=5.0, trust_env=False)


def _dto_to_dict(obj):
    return dataclasses.asdict(obj) if dataclasses.is_dataclass(obj) and not isinstance(obj, type) else obj


async def _si(method: str, path: str, **kwargs) -> httpx.Response:
    """Call the SI service; every transport problem becomes 503, every HTTP error status 502."""
    try:
        resp = await _http_client.request(method, path, **kwargs)
        resp.raise_for_status()
        return resp
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"SI service error: {e.response.status_code}")
    except httpx.HTTPError:
        raise HTTPException(status_code=503, detail="Smart Intersection service unreachable")


@router.get("/state")
async def get_si_state():
    resp = await _si("GET", "/xml/state")
    try:
        return _dto_to_dict(XmlParser.parse(resp.text))
    except XmlParseError as e:
        raise HTTPException(status_code=502, detail=f"XML parse error: {e}")


@router.get("/health")
async def get_si_health():
    return (await _si("GET", "/health")).json()


@router.post("/simulation/start")
async def si_start():
    return (await _si("POST", "/simulation/start")).json()


@router.post("/simulation/stop")
async def si_stop():
    return (await _si("POST", "/simulation/stop")).json()


@router.post("/scenario/start")
async def si_scenario_start(scenario_id: str):
    return (await _si("POST", "/scenario/start", json={"scenario_id": scenario_id})).json()
