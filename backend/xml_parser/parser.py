"""
XML Parser for Smart Intersection state XML.
Validates against XSD using lxml if available; falls back to stdlib ET parse.
"""
import xml.etree.ElementTree as ET
import os
import logging
from .dto import (
    IntersectionData, SimulationInfoDTO, LightDTO, PedestrianLightDTO, VehicleDTO,
    PedestrianDTO, MetricsDTO,
)

logger = logging.getLogger(__name__)

XSD_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "smart_intersection", "xml_export", "intersection.xsd",
)


class XmlParseError(ValueError):
    pass


class XmlParser:
    _schema = None  # lxml schema, loaded once

    @classmethod
    def _get_schema(cls):
        if cls._schema is not None:
            return cls._schema
        try:
            from lxml import etree
            with open(XSD_PATH, "rb") as f:
                schema_doc = etree.parse(f)
            cls._schema = etree.XMLSchema(schema_doc)
            logger.debug("XSD schema loaded for validation")
        except ImportError:
            logger.warning("lxml not installed — XSD validation disabled")
            cls._schema = False
        except Exception as e:
            logger.warning("Failed to load XSD schema: %s", e)
            cls._schema = False
        return cls._schema

    @classmethod
    def validate(cls, xml_str: str) -> bool:
        """Return True if XML validates against XSD. Raises XmlParseError on failure."""
        schema = cls._get_schema()
        if not schema:
            return True  # validation skipped
        try:
            from lxml import etree
            doc = etree.fromstring(xml_str.encode("utf-8"))
            if not schema.validate(doc):
                errors = "\n".join(str(e) for e in schema.error_log)
                raise XmlParseError(f"XML validation failed:\n{errors}")
            return True
        except XmlParseError:
            raise
        except Exception as e:
            raise XmlParseError(f"XML parse error: {e}") from e

    @classmethod
    def parse(cls, xml_str: str, validate: bool = True) -> IntersectionData:
        """Parse XML string → IntersectionData. Validates against the XSD when lxml is available."""
        if validate:
            cls.validate(xml_str)

        # Strip XML declaration for ElementTree
        body = xml_str
        if body.startswith("<?xml"):
            body = body.split("?>", 1)[-1].strip()

        try:
            root = ET.fromstring(body)
        except ET.ParseError as e:
            raise XmlParseError(f"Malformed XML: {e}") from e

        # <simulation>
        sim_el = root.find("simulation")
        if sim_el is None:
            raise XmlParseError("Missing <simulation> element")

        sim_info = SimulationInfoDTO(
            intersection_id=sim_el.get("id", ""),
            status=sim_el.get("status", "stopped"),
            sim_time=float(sim_el.get("sim_time", 0)),
            time_scale=float(sim_el.get("time_scale", 1.0)),
            scenario=sim_el.get("scenario", "normal"),
            seed=int(sim_el.get("seed", 42)),
        )

        # <trafficLights>
        lights = []
        lights_el = root.find("trafficLights")
        if lights_el is not None:
            for el in lights_el.findall("light"):
                lights.append(LightDTO(
                    id=el.get("id", ""),
                    direction=el.get("direction", ""),
                    state=el.get("state", "RED"),
                    phase_index=int(el.get("phase_index", 0)),
                    phase_switches=int(el.get("phase_switches", 0)),
                    sections={s.get("movement", ""): s.get("state", "RED") for s in el.findall("section")},
                ))

        # <pedestrianLights>
        pedestrian_lights = []
        ped_lights_el = root.find("pedestrianLights")
        if ped_lights_el is not None:
            for el in ped_lights_el.findall("pedestrianLight"):
                pedestrian_lights.append(PedestrianLightDTO(
                    id=el.get("id", ""),
                    direction=el.get("direction", ""),
                    state=el.get("state", "RED"),
                    phase_switches=int(el.get("phase_switches", 0)),
                    waiting_peds=int(el.get("waiting_peds", 0)),
                    crossing_peds=int(el.get("crossing_peds", 0)),
                ))

        # <vehicles>
        vehicles = []
        vehicles_el = root.find("vehicles")
        if vehicles_el is not None:
            for el in vehicles_el.findall("vehicle"):
                vehicles.append(VehicleDTO(
                    id=el.get("id", ""),
                    vehicle_type=el.get("type", "car"),
                    lane_id=el.get("lane_id", ""),
                    direction=el.get("direction", ""),
                    position_m=float(el.get("position_m", 0)),
                    speed_mps=float(el.get("speed_mps", 0)),
                    state=el.get("state", "driving"),
                    wait_time=float(el.get("wait_time", 0)),
                    movement=el.get("movement", "straight"),
                    lane_index=int(el.get("lane_index", 0)),
                    x=float(el.get("x")) if el.get("x") is not None else None,
                    z=float(el.get("z")) if el.get("z") is not None else None,
                    heading=float(el.get("heading", 0.0)),
                ))

        # <pedestrians>
        pedestrians = []
        peds_el = root.find("pedestrians")
        if peds_el is not None:
            for el in peds_el.findall("pedestrian"):
                pedestrians.append(PedestrianDTO(
                    id=el.get("id", ""),
                    crossing_id=el.get("crossing_id", ""),
                    state=el.get("state", "walking_to_crossing"),
                    position_m=float(el.get("position_m", 0)),
                    wait_time=float(el.get("wait_time", 0)),
                    direction=int(el.get("direction", 1)),
                    offset=float(el.get("offset", 0.0)),
                    x=float(el.get("x")) if el.get("x") is not None else None,
                    z=float(el.get("z")) if el.get("z") is not None else None,
                ))

        # <metrics>
        metrics = None
        m_el = root.find("metrics")
        if m_el is not None:
            metrics = MetricsDTO(
                vehicles_active=int(m_el.get("vehicles_active", 0)),
                vehicles_waiting=int(m_el.get("vehicles_waiting", 0)),
                passed_total=int(m_el.get("passed_total", 0)),
                avg_wait_s=float(m_el.get("avg_wait_s", 0.0)),
                max_wait_s=float(m_el.get("max_wait_s", 0.0)),
                throughput_per_min=float(m_el.get("throughput_per_min", 0.0)),
                congestion_pct=float(m_el.get("congestion_pct", 0.0)),
                efficiency_pct=float(m_el.get("efficiency_pct", 100.0)),
                ped_signal_switches=int(m_el.get("ped_signal_switches", 0)),
            )

        return IntersectionData(
            simulation=sim_info,
            lights=lights,
            pedestrian_lights=pedestrian_lights,
            vehicles=vehicles,
            pedestrians=pedestrians,
            metrics=metrics,
        )
