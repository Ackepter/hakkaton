"""
Traffic scenario presets.
Each scenario is a dict that maps to SimulationEngine.configure(**kwargs).
"""

SCENARIOS = {
    "empty": {
        "name": "Empty Intersection",
        "description": "No traffic — useful for baseline testing",
        "spawn_rate": 0.0,
        "ped_spawn_rate": 0.0,
        "time_scale": 1.0,
        "direction_probs": {"north": 0.25, "south": 0.25, "east": 0.25, "west": 0.25},
        "type_probs": {"car": 1.0, "truck": 0.0, "bus": 0.0, "tram": 0.0, "emergency": 0.0},
    },
    "normal": {
        "name": "Normal City Traffic",
        "description": "Typical urban traffic flow",
        "spawn_rate": 12.0,
        "ped_spawn_rate": 5.0,
        "time_scale": 1.0,
        "direction_probs": {"north": 0.25, "south": 0.25, "east": 0.25, "west": 0.25},
        "type_probs": {"car": 0.75, "truck": 0.10, "bus": 0.10, "tram": 0.04, "emergency": 0.01},
    },
    "heavy": {
        "name": "Heavy Traffic",
        "description": "Rush-hour congestion",
        "spawn_rate": 40.0,
        "ped_spawn_rate": 8.0,
        "time_scale": 1.0,
        "direction_probs": {"north": 0.25, "south": 0.25, "east": 0.25, "west": 0.25},
        "type_probs": {"car": 0.80, "truck": 0.08, "bus": 0.10, "tram": 0.02, "emergency": 0.0},
    },
    "pedestrian_rush": {
        "name": "Pedestrian Rush Hour",
        "description": "Many pedestrians, moderate vehicle traffic",
        "spawn_rate": 8.0,
        "ped_spawn_rate": 30.0,
        "time_scale": 1.0,
        "direction_probs": {"north": 0.25, "south": 0.25, "east": 0.25, "west": 0.25},
        "type_probs": {"car": 0.75, "truck": 0.10, "bus": 0.10, "tram": 0.04, "emergency": 0.01},
    },
    "unbalanced": {
        "name": "Unbalanced North Flow",
        "description": "70% of traffic arrives from the north",
        "spawn_rate": 12.0,
        "ped_spawn_rate": 3.0,
        "time_scale": 1.0,
        "direction_probs": {"north": 0.70, "south": 0.10, "east": 0.10, "west": 0.10},
        "type_probs": {"car": 0.75, "truck": 0.10, "bus": 0.10, "tram": 0.04, "emergency": 0.01},
    },
    "emergency": {
        "name": "Emergency Vehicle Priority",
        "description": "Normal traffic + frequent emergency vehicle spawns",
        "spawn_rate": 12.0,
        "ped_spawn_rate": 3.0,
        "time_scale": 1.0,
        "direction_probs": {"north": 0.25, "south": 0.25, "east": 0.25, "west": 0.25},
        "type_probs": {"car": 0.50, "truck": 0.05, "bus": 0.05, "tram": 0.02, "emergency": 0.38},
    },
    "traffic_jam": {
        "name": "Traffic Jam",
        "description": "Extreme congestion — queues fill all lanes",
        "spawn_rate": 60.0,
        "ped_spawn_rate": 5.0,
        "time_scale": 1.0,
        "direction_probs": {"north": 0.25, "south": 0.25, "east": 0.25, "west": 0.25},
        "type_probs": {"car": 0.80, "truck": 0.10, "bus": 0.08, "tram": 0.02, "emergency": 0.0},
    },
    "failsafe": {
        "name": "Sensor Failure — FAILSAFE Mode",
        "description": "Normal traffic but intersection operates on failsafe timing",
        "spawn_rate": 12.0,
        "ped_spawn_rate": 5.0,
        "time_scale": 1.0,
        "direction_probs": {"north": 0.25, "south": 0.25, "east": 0.25, "west": 0.25},
        "type_probs": {"car": 0.75, "truck": 0.10, "bus": 0.10, "tram": 0.04, "emergency": 0.01},
        "_notes": "Triggers FAILSAFE mode on the main controller",
    },
    "demo_city_intersection": {
        "name": "Full Demo — City Intersection",
        "description": "Dynamic scenario that progresses through all traffic phases",
        "spawn_rate": 5.0,           # starts light, then ramps up
        "ped_spawn_rate": 2.0,
        "time_scale": 2.0,           # 2× speed for demo
        "direction_probs": {"north": 0.25, "south": 0.25, "east": 0.25, "west": 0.25},
        "type_probs": {"car": 0.75, "truck": 0.10, "bus": 0.10, "tram": 0.04, "emergency": 0.01},
        "_timeline": [
            {"at_sim_s": 0,   "spawn_rate": 5.0,  "ped_spawn_rate": 2.0},
            {"at_sim_s": 20,  "spawn_rate": 12.0, "ped_spawn_rate": 5.0},
            {"at_sim_s": 60,  "spawn_rate": 25.0, "direction_probs": {"north": 0.60, "south": 0.15, "east": 0.15, "west": 0.10}},
            {"at_sim_s": 90,  "spawn_rate": 10.0, "ped_spawn_rate": 25.0},
            {"at_sim_s": 120, "spawn_rate": 60.0, "ped_spawn_rate": 5.0},
            {"at_sim_s": 150, "spawn_rate": 12.0, "ped_spawn_rate": 5.0, "direction_probs": {"north": 0.25, "south": 0.25, "east": 0.25, "west": 0.25}},
        ],
    },
}


def get_scenario(scenario_id: str) -> dict:
    """Return scenario config dict, raises KeyError if not found."""
    if scenario_id not in SCENARIOS:
        raise KeyError(f"Unknown scenario: {scenario_id!r}. Available: {list(SCENARIOS.keys())}")
    return SCENARIOS[scenario_id].copy()
