"""
Wiring for physical traffic lights: which light id (e.g. "TL-N") mirrors to which real signal (ip[, port]).

Optional and off by default — same rule as the camera config (Task 10, 34.11): nothing here is required to run the
simulation. A missing file, or a light id the file doesn't mention, simply gets no physical output.
"""
import logging
import os
from typing import Dict, Optional

import yaml

from .udp_matrix import UdpMatrixLight

logger = logging.getLogger(__name__)

DEFAULT_PORT = 9000


def _entry(light_id: str, raw) -> UdpMatrixLight:
    if isinstance(raw, str):
        ip, port = raw, DEFAULT_PORT
    else:
        ip = raw["ip"]
        port = int(raw.get("port", DEFAULT_PORT))
    return UdpMatrixLight(light_id=light_id, address=(ip, port))


def load_light_hardware(path: Optional[str]) -> Dict[str, UdpMatrixLight]:
    """`config/traffic_lights.yaml` (or `path`) -> {light_id: UdpMatrixLight}. Missing / empty file -> {} (no hardware)."""
    if not path or not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    lights = raw.get("lights") or {}
    if not isinstance(lights, dict):
        raise ValueError(f"{path}: 'lights' must be a mapping of light id -> ip (or {{ip, port}})")
    out = {light_id: _entry(light_id, cfg) for light_id, cfg in lights.items()}
    if out:
        logger.info("Physical traffic lights configured: %s", ", ".join(sorted(out)))
    return out
