import pytest
import asyncio
import time
from backend.traffic.light import TrafficLight
from backend.traffic.controller import TrafficController
from backend.hardware.mock_gpio import MockGPIO
from backend.models.schemas import LightState, SystemMode, IntersectionConfig, TrafficLightConfig, GridPosition


def make_controller():
    gpio = MockGPIO()
    gpio.initialize()
    return TrafficController(gpio)


def make_light(light_id="TL-01", phases=None):
    return TrafficLight(light_id=light_id, phases=phases)


# --- TrafficLight tests ---

def test_light_initial_state():
    light = make_light()
    assert light.state == LightState.RED
    assert light.phase_index == 0


def test_light_default_phases():
    light = make_light()
    # Default first phase is RED
    assert light.state == LightState.RED


def test_light_force_state():
    light = make_light()
    light.force_state(LightState.GREEN)
    assert light.state == LightState.GREEN


def test_light_phase_advance():
    phases = [{"state": "RED", "duration": 0.05}, {"state": "GREEN", "duration": 0.05}]
    light = make_light(phases=phases)
    assert light.state == LightState.RED
    time.sleep(0.1)
    changed = light.tick()
    assert changed
    assert light.state == LightState.GREEN


def test_light_set_phases():
    light = make_light()
    new_phases = [{"state": "GREEN", "duration": 10}, {"state": "RED", "duration": 20}]
    light.set_phases(new_phases)
    assert light.state == LightState.GREEN
    assert light.phase_index == 0


def test_light_to_dict():
    light = make_light("TL-99")
    d = light.to_dict()
    assert d["id"] == "TL-99"
    assert "state" in d
    assert "time_remaining" in d


# --- TrafficController tests ---

def test_controller_initial_mode():
    ctrl = make_controller()
    assert ctrl.mode == SystemMode.AUTO


def test_controller_set_manual():
    ctrl = make_controller()
    ctrl.set_mode(SystemMode.MANUAL)
    assert ctrl.mode == SystemMode.MANUAL


def test_controller_set_failsafe():
    ctrl = make_controller()
    ctrl.trigger_failsafe("Camera offline")
    assert ctrl.mode == SystemMode.FAILSAFE
    assert ctrl.failsafe_reason == "Camera offline"


def test_controller_recover_from_failsafe():
    ctrl = make_controller()
    ctrl.trigger_failsafe("Test")
    ctrl.recover_from_failsafe()
    assert ctrl.mode == SystemMode.AUTO
    assert ctrl.failsafe_reason is None


def test_controller_manual_requires_manual_mode():
    ctrl = make_controller()
    config = IntersectionConfig(traffic_lights=[
        TrafficLightConfig(id="TL-01", position=GridPosition(col=5, row=5))
    ])
    ctrl.load_config(config)
    # In AUTO mode, manual control should be rejected
    ok = ctrl.manual_set_light("TL-01", LightState.GREEN)
    assert not ok


def test_controller_manual_in_manual_mode():
    ctrl = make_controller()
    config = IntersectionConfig(traffic_lights=[
        TrafficLightConfig(id="TL-01", position=GridPosition(col=5, row=5))
    ])
    ctrl.load_config(config)
    ctrl.set_mode(SystemMode.MANUAL)
    ok = ctrl.manual_set_light("TL-01", LightState.GREEN)
    assert ok
    lights = ctrl.get_lights()
    assert lights["TL-01"].state == LightState.GREEN


def test_controller_load_config():
    ctrl = make_controller()
    config = IntersectionConfig(traffic_lights=[
        TrafficLightConfig(id="TL-01", position=GridPosition(col=5, row=5)),
        TrafficLightConfig(id="TL-02", position=GridPosition(col=10, row=5)),
    ])
    ctrl.load_config(config)
    assert len(ctrl.get_lights()) == 2


def test_controller_failsafe_applies_fixed_timing():
    ctrl = make_controller()
    config = IntersectionConfig(traffic_lights=[
        TrafficLightConfig(id="TL-01", position=GridPosition(col=5, row=5))
    ])
    ctrl.load_config(config)
    ctrl.trigger_failsafe("Test failsafe")
    # Light should have failsafe phases applied
    light = ctrl.get_lights()["TL-01"]
    # In failsafe, first phase should still be RED (failsafe default)
    assert light.state == LightState.RED


# --- MockGPIO tests ---

def test_mock_gpio_set_and_get():
    gpio = MockGPIO()
    gpio.initialize()
    gpio.set_light("TL-01", red=True, yellow=False, green=False)
    state = gpio.get_light_state("TL-01")
    assert state["red"] is True
    assert state["yellow"] is False
    assert state["green"] is False


def test_mock_gpio_cleanup():
    gpio = MockGPIO()
    gpio.initialize()
    gpio.set_light("TL-01", red=True, yellow=False, green=False)
    gpio.cleanup()
    state = gpio.get_light_state("TL-01")
    assert state["red"] is False


def test_mock_gpio_all_states():
    gpio = MockGPIO()
    gpio.initialize()
    gpio.set_light("TL-01", red=True, yellow=False, green=False)
    gpio.set_light("TL-02", red=False, yellow=False, green=True)
    states = gpio.get_all_states()
    assert "TL-01" in states
    assert "TL-02" in states
