"""Optional physical mirror of the virtual traffic lights (Task: parallel output to a real signal by IP).

    SimulationEngine._apply_lights()  (writes light.state — the ONLY writer, see engine/simulation.py)
              |
              v
       UdpMatrixLight.send(state)   (per configured light id; unreachable / unconfigured = silently skipped)
              |
              v
       real LED-matrix traffic light, UDP, one frame per address (task_files/traffic_light.py protocol)

A light with no entry in the config sends nothing (no hardware required to run the simulation, same rule as the
camera and GPIO abstractions elsewhere in the project). Never imported by anything that decides traffic — this
module only ever reads a light's already-decided state and relays it.
"""
from .config import load_light_hardware
from .udp_matrix import UdpMatrixLight

__all__ = ["load_light_hardware", "UdpMatrixLight"]
