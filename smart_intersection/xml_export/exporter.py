"""
SimStateExporter — converts simulation state dict to XML string.
Uses stdlib xml.etree.ElementTree only (no external dependencies).
"""
import xml.etree.ElementTree as ET
import time


class SimStateExporter:
    VERSION = "1.0"

    @staticmethod
    def to_xml(state: dict) -> str:
        """Convert state dict (from SimulationEngine.get_state()) to XML string."""
        root = ET.Element("intersectionSimulation")
        root.set("version", SimStateExporter.VERSION)
        root.set("timestamp", str(round(time.time(), 3)))

        # <simulation>
        sim_el = ET.SubElement(root, "simulation")
        sim_el.set("id", str(state.get("intersection_id", "SI-001")))
        sim_el.set("status", str(state.get("status", "stopped")))
        sim_el.set("sim_time", str(round(float(state.get("sim_time", 0)), 3)))
        sim_el.set("time_scale", str(round(float(state.get("time_scale", 1.0)), 2)))
        sim_el.set("scenario", str(state.get("scenario", "normal")))
        sim_el.set("seed", str(state.get("seed", 42)))

        # <trafficLights>
        lights_el = ET.SubElement(root, "trafficLights")
        for light in state.get("lights", []):
            l_el = ET.SubElement(lights_el, "light")
            l_el.set("id", str(light["id"]))
            l_el.set("direction", str(light["direction"]))
            l_el.set("state", str(light["state"]))
            l_el.set("phase_index", str(light.get("phase_index", 0)))
            l_el.set("phase_switches", str(light.get("phase_switches", 0)))
            for movement, section_state in sorted((light.get("sections") or {}).items()):
                s_el = ET.SubElement(l_el, "section")
                s_el.set("movement", str(movement))
                s_el.set("state", str(section_state))

        # <pedestrianLights>
        ped_lights = state.get("pedestrian_lights", [])
        ped_lights_el = ET.SubElement(root, "pedestrianLights")
        ped_lights_el.set("count", str(len(ped_lights)))
        for pl in ped_lights:
            pl_el = ET.SubElement(ped_lights_el, "pedestrianLight")
            pl_el.set("id", str(pl["id"]))
            pl_el.set("direction", str(pl["direction"]))
            pl_el.set("state", str(pl["state"]))
            pl_el.set("phase_switches", str(pl.get("phase_switches", 0)))
            pl_el.set("waiting_peds", str(pl.get("waiting_peds", 0)))
            pl_el.set("crossing_peds", str(pl.get("crossing_peds", 0)))

        # <vehicles>
        vehicles = state.get("vehicles", [])
        vehicles_el = ET.SubElement(root, "vehicles")
        vehicles_el.set("count", str(len(vehicles)))
        for v in vehicles:
            v_el = ET.SubElement(vehicles_el, "vehicle")
            v_el.set("id", str(v["id"]))
            v_el.set("type", str(v["vehicle_type"]))
            v_el.set("lane_id", str(v["lane_id"]))
            v_el.set("direction", str(v["direction"]))
            v_el.set("position_m", str(round(float(v.get("position_m", 0)), 2)))
            v_el.set("speed_mps", str(round(float(v.get("speed_mps", 0)), 2)))
            v_el.set("state", str(v.get("state", "driving")))
            v_el.set("wait_time", str(round(float(v.get("wait_time", 0)), 2)))
            v_el.set("movement", str(v.get("movement", "straight")))
            v_el.set("lane_index", str(int(v.get("lane_index", 0))))
            if "x" in v:                                   # world position: consumers need no road geometry
                v_el.set("x", str(round(float(v["x"]), 2)))
                v_el.set("z", str(round(float(v["z"]), 2)))
                v_el.set("heading", str(round(float(v.get("heading", 0.0)), 3)))

        # <pedestrians>
        pedestrians = state.get("pedestrians", [])
        peds_el = ET.SubElement(root, "pedestrians")
        peds_el.set("count", str(len(pedestrians)))
        for p in pedestrians:
            p_el = ET.SubElement(peds_el, "pedestrian")
            p_el.set("id", str(p["id"]))
            p_el.set("crossing_id", str(p["crossing_id"]))
            p_el.set("state", str(p.get("state", "walking_to_crossing")))
            p_el.set("position_m", str(round(float(p.get("position_m", 0)), 2)))
            p_el.set("wait_time", str(round(float(p.get("wait_time", 0)), 2)))
            p_el.set("direction", str(int(p.get("direction", 1))))
            p_el.set("offset", str(round(float(p.get("offset", 0.0)), 2)))
            if "x" in p:
                p_el.set("x", str(round(float(p["x"]), 2)))
                p_el.set("z", str(round(float(p["z"]), 2)))

        # <metrics>
        metrics = state.get("metrics", {})
        m_el = ET.SubElement(root, "metrics")
        m_el.set("vehicles_active", str(int(metrics.get("vehicles_active", 0))))
        m_el.set("vehicles_waiting", str(int(metrics.get("vehicles_waiting", 0))))
        m_el.set("passed_total", str(int(metrics.get("passed_total", 0))))
        m_el.set("avg_wait_s", str(round(float(metrics.get("avg_wait_s", 0.0)), 2)))
        m_el.set("max_wait_s", str(round(float(metrics.get("max_wait_s", 0.0)), 2)))
        m_el.set("throughput_per_min", str(round(float(metrics.get("throughput_per_min", 0.0)), 2)))
        m_el.set("congestion_pct", str(round(float(metrics.get("congestion_pct", 0.0)), 1)))
        m_el.set("efficiency_pct", str(round(float(metrics.get("efficiency_pct", 100.0)), 1)))
        m_el.set("ped_signal_switches", str(int(metrics.get("ped_signal_switches", 0))))

        ET.indent(root, space="  ")
        return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode")
