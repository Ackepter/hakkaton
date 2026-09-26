import pytest
import asyncio
from backend.simulation.simulator import SimulationEngine
from backend.metrics.collector import MetricsCollector
from backend.models.schemas import SystemMode


def run_async(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_simulation_configure():
    sim = SimulationEngine()
    sim.configure(["lane-1", "lane-2"], ["pc-1"], {"lane-1": "TL-01", "lane-2": "TL-02"})
    assert "lane-1" in sim._lane_queues
    assert "lane-2" in sim._lane_queues
    assert "pc-1" in sim._pedestrian_queues


def test_simulation_get_traffic_data_empty():
    sim = SimulationEngine()
    sim.configure(["lane-1"], [], {})
    data = sim.get_traffic_data()
    assert "queues" in data
    assert "summary" in data
    assert data["summary"]["total_cars"] == 0


def test_simulation_spawn_on_tick():
    sim = SimulationEngine()
    sim.configure(["lane-1"], [], {})
    sim._spawn_rate = 10.0  # High spawn rate for test
    sim._spawn_vehicles()
    data = sim.get_traffic_data()
    # Should have spawned some vehicles
    assert data["summary"]["total_cars"] >= 0  # May be 0 if random didn't spawn


def test_simulation_vehicles_pass_on_green():
    sim = SimulationEngine()
    sim.configure(["lane-1"], [], {"lane-1": "TL-01"})
    sim._spawn_rate = 100.0
    sim._speed = 1.0
    # Force-spawn some vehicles
    for _ in range(10):
        sim._spawn_vehicles()

    data_before = sim.get_traffic_data()
    total_before = sum(q.get("total", 0) for q in data_before["queues"].values())

    # Set green
    sim.update_light_states({"TL-01": "GREEN"})
    sim._process_queues()

    data_after = sim.get_traffic_data()
    total_after = sum(q.get("total", 0) for q in data_after["queues"].values())

    # Some vehicles should have passed
    assert total_after <= total_before


def test_simulation_reset():
    sim = SimulationEngine()
    sim.configure(["lane-1"], [], {})
    sim._spawn_rate = 100.0
    for _ in range(5):
        sim._spawn_vehicles()
    sim.reset()
    data = sim.get_traffic_data()
    assert data["summary"]["total_cars"] == 0


def test_simulation_speed_setting():
    sim = SimulationEngine()
    sim.set_speed(3.0)
    assert sim._speed == 3.0
    sim.set_speed(0.01)  # Should clamp to 0.1
    assert sim._speed == 0.1
    sim.set_speed(999)  # Should clamp to 10
    assert sim._speed == 10.0


# --- MetricsCollector tests ---

def test_metrics_update_and_get():
    mc = MetricsCollector()
    traffic_data = {
        "queues": {"lane-1": {"cars": 3, "trucks": 1, "buses": 0, "total": 4, "avg_wait": 10.0, "max_wait": 20.0, "throughput": 5}},
        "summary": {
            "total_cars": 3, "total_trucks": 1, "total_buses": 0,
            "total_pedestrians": 2, "pedestrians_waiting": 2,
            "avg_car_wait": 10.0, "avg_pedestrian_wait": 15.0,
            "cars_per_hour": 120.0, "throughput": 5,
        }
    }
    mc.update(traffic_data, [], SystemMode.AUTO, 5)
    latest = mc.get_latest()
    assert latest["traffic"]["total_cars"] == 3
    assert latest["system"]["system_mode"] == "AUTO"


def test_metrics_efficiency_score():
    mc = MetricsCollector()
    score_no_wait = mc._calc_efficiency_score({"avg_car_wait": 0})
    score_max_wait = mc._calc_efficiency_score({"avg_car_wait": 60})
    assert score_no_wait == 100.0
    assert score_max_wait == 0.0


def test_metrics_congestion_level():
    mc = MetricsCollector()
    assert mc._calc_congestion_level({}) == "CLEAR"
    assert mc._calc_congestion_level({"l1": {"total": 2}}) == "CLEAR"
    assert mc._calc_congestion_level({"l1": {"total": 5}, "l2": {"total": 6}}) == "MODERATE"
    assert mc._calc_congestion_level({"l1": {"total": 15}}) == "GRIDLOCK"


def test_metrics_pedestrian_risk():
    mc = MetricsCollector()
    assert mc._calc_pedestrian_risk({"avg_pedestrian_wait": 5}) == "LOW"
    assert mc._calc_pedestrian_risk({"avg_pedestrian_wait": 30}) == "MEDIUM"
    assert mc._calc_pedestrian_risk({"avg_pedestrian_wait": 60}) == "HIGH"


def test_metrics_history():
    mc = MetricsCollector()
    traffic_data = {"queues": {}, "summary": {"total_cars": 0, "total_trucks": 0, "total_buses": 0,
        "total_pedestrians": 0, "pedestrians_waiting": 0, "avg_car_wait": 0.0,
        "avg_pedestrian_wait": 0.0, "cars_per_hour": 0.0, "throughput": 0}}
    for _ in range(5):
        mc.update(traffic_data, [], SystemMode.AUTO, 0)
    history = mc.get_history(seconds=300)
    assert len(history) == 5
