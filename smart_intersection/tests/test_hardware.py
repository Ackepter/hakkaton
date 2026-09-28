"""
Physical mirror of the virtual traffic lights (task_files/traffic_light.py protocol, one UDP frame per light).

Direction under test throughout: the real signal only ever reflects a light's already-decided state — it can never
feed back into which phase is active. `light.send(state)` never touches the simulation; only `_apply_lights`
(the phase machine, driven by aggregated demand) may write `light.state`.
"""
import math
import socket
import struct

import pytest
import yaml

from fastapi.testclient import TestClient

from smart_intersection.engine.simulation import SimulationEngine, GREEN_BLINK_COUNT, GREEN_BLINK_HALF_S
from smart_intersection.hardware.config import load_light_hardware
from smart_intersection.hardware.udp_matrix import HEIGHT, RADIUS, WIDTH, UdpMatrixLight, _BLANK, _FRAMES, make_frame
from smart_intersection.layout import default_layout, presets
from smart_intersection.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c

FRAME_BYTES = WIDTH * HEIGHT * 3


def pixel(frame: bytes, x: int, y: int) -> tuple:
    p = (y * WIDTH + x) * 3
    return tuple(frame[p:p + 3])


# ----------------------------------------------------------------------------- frame contents

def test_frame_is_the_right_size_and_only_lists_lamps_light_up():
    assert len(make_frame()) == FRAME_BYTES == len(_BLANK)
    assert make_frame() == bytes(FRAME_BYTES)                       # nothing lit = all black
    red = make_frame("red")
    assert pixel(red, 10, HEIGHT // 2) == (255, 0, 0)                # centre of the red lamp
    assert pixel(red, 32, HEIGHT // 2) == (0, 0, 0)                  # yellow lamp untouched
    assert pixel(red, 53, HEIGHT // 2) == (0, 0, 0)                  # green lamp untouched
    both = make_frame("red", "green")
    assert pixel(both, 10, HEIGHT // 2) == (255, 0, 0) and pixel(both, 53, HEIGHT // 2) == (0, 255, 0)


def test_lamp_edges_are_dark_outside_the_radius():
    red = make_frame("red")
    assert pixel(red, 10 - RADIUS - 3, HEIGHT // 2) == (0, 0, 0)
    assert pixel(red, 10, HEIGHT // 2) != (0, 0, 0)


@pytest.mark.parametrize("state,lit_x", [("RED", 10), ("YELLOW", 32), ("GREEN", 53)])
def test_the_three_engine_states_map_to_the_three_lamps(state, lit_x):
    frame = _FRAMES[state]
    assert pixel(frame, lit_x, HEIGHT // 2) != (0, 0, 0)
    for other_x in {10, 32, 53} - {lit_x}:
        assert pixel(frame, other_x, HEIGHT // 2) == (0, 0, 0)


def test_an_unknown_state_shows_a_blank_frame():
    assert _FRAMES.get("PURPLE", _BLANK) == _BLANK


# ----------------------------------------------------------------------------- UdpMatrixLight wire protocol

@pytest.fixture
def udp_listener():
    """A real bound UDP socket standing in for the physical matrix."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    sock.settimeout(1.0)
    yield sock
    sock.close()


def test_send_delivers_the_matching_frame_with_the_wire_header(udp_listener):
    light = UdpMatrixLight("TL-N", ("127.0.0.1", udp_listener.getsockname()[1]))
    try:
        assert light.send("GREEN") is True
        data, _ = udp_listener.recvfrom(1 << 20)
        header, frame = data[:8], data[8:]
        assert struct.unpack("<II", header) == (0, FRAME_BYTES)
        assert frame == _FRAMES["GREEN"]
    finally:
        light.close()


def test_two_lights_are_independent_destinations(udp_listener):
    other = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    other.bind(("127.0.0.1", 0))
    other.settimeout(1.0)
    a = UdpMatrixLight("TL-N", ("127.0.0.1", udp_listener.getsockname()[1]))
    b = UdpMatrixLight("TL-E", ("127.0.0.1", other.getsockname()[1]))
    try:
        a.send("RED")
        b.send("GREEN")
        assert udp_listener.recvfrom(1 << 20)[0][8:] == _FRAMES["RED"]
        assert other.recvfrom(1 << 20)[0][8:] == _FRAMES["GREEN"]
    finally:
        a.close()
        b.close()
        other.close()


def test_an_unreachable_light_never_raises_and_recovers_once_it_answers_again(udp_listener):
    light = UdpMatrixLight("TL-N", ("127.0.0.1", udp_listener.getsockname()[1]))
    real_sock, calls = light._sock, []

    class Failing:
        def sendto(self, *a, **kw):
            calls.append(1)
            raise OSError("network is down")

    try:
        light._sock = Failing()
        assert light.send("RED") is False and light.send("RED") is False   # never raises, keeps ticking
        assert len(calls) == 2
        light._sock = real_sock
        assert light.send("GREEN") is True                                  # back to the real socket, works again
        assert udp_listener.recvfrom(1 << 20)[0][8:] == _FRAMES["GREEN"]
    finally:
        light.close()


# ----------------------------------------------------------------------------- config loading

def test_missing_or_empty_config_means_no_hardware(tmp_path):
    assert load_light_hardware(None) == {}
    assert load_light_hardware(str(tmp_path / "nope.yaml")) == {}
    empty = tmp_path / "empty.yaml"
    empty.write_text("lights: {}")
    assert load_light_hardware(str(empty)) == {}


def test_config_accepts_the_short_and_the_long_form(tmp_path):
    p = tmp_path / "lights.yaml"
    p.write_text(yaml.safe_dump({"lights": {"TL-N": {"ip": "10.0.0.1", "port": 9001}, "TL-E": "10.0.0.2"}}))
    hw = load_light_hardware(str(p))
    assert set(hw) == {"TL-N", "TL-E"}
    assert hw["TL-N"].address == ("10.0.0.1", 9001)
    assert hw["TL-E"].address == ("10.0.0.2", 9000)                        # default port
    for light in hw.values():
        light.close()


def test_config_rejects_a_malformed_lights_section(tmp_path):
    p = tmp_path / "lights.yaml"
    p.write_text(yaml.safe_dump({"lights": ["TL-N"]}))
    with pytest.raises(ValueError, match="mapping"):
        load_light_hardware(str(p))


# ----------------------------------------------------------------------------- wired into the engine

class RecordingLight:
    """Stands in for UdpMatrixLight: records every state it was asked to show, never touches the engine."""
    def __init__(self):
        self.sent = []

    def send(self, state):
        self.sent.append(state)
        return True


def test_configured_lights_receive_every_state_the_real_ones_show():
    hw = {"TL-N": RecordingLight(), "TL-E": RecordingLight()}
    e = SimulationEngine(seed=1, layout=default_layout(), light_hardware=hw)
    e.advance(20)
    # "OFF"/extra "GREEN"/"YELLOW" ticks are the real-signal-only edge effects (see _hw_state); never the light's own state
    assert hw["TL-N"].sent and hw["TL-N"].sent[-1] in (e._lights["TL-N"].state, "GREEN", "OFF", "YELLOW")
    assert hw["TL-E"].sent and hw["TL-E"].sent[-1] in (e._lights["TL-E"].state, "GREEN", "OFF", "YELLOW")
    assert set(hw["TL-N"].sent) <= {"RED", "YELLOW", "GREEN", "OFF"}
    assert len(hw["TL-N"].sent) == len(hw["TL-E"].sent) > 1                # ticked (and sent) more than once


def test_an_arm_with_no_hardware_entry_is_never_touched():
    hw = {"TL-N": RecordingLight()}                                        # TL-S / TL-E / TL-W left unconfigured
    e = SimulationEngine(seed=1, layout=default_layout(), light_hardware=hw)
    e.advance(20)
    assert hw["TL-N"].sent                                                 # only the configured one saw anything


def test_hardware_wiring_survives_a_layout_change_and_a_reset():
    hw = {"TL-N": RecordingLight()}
    e = SimulationEngine(seed=1, layout=default_layout(), light_hardware=hw)
    e.set_layout(presets()["T-junction"])                                  # still has a north arm / TL-N
    e.advance(10)
    assert hw["TL-N"].sent
    n_before = len(hw["TL-N"].sent)
    import asyncio
    asyncio.run(e.reset())
    e.advance(10)
    assert len(hw["TL-N"].sent) > n_before                                 # kept sending after reset, not dropped


def test_hardware_is_wired_for_a_roundabout_too():
    """A roundabout's entries are metered by real lights the same as a crossroads (see docs/junctions.md)."""
    hw = {"TL-N": RecordingLight()}
    e = SimulationEngine(seed=1, layout=presets()["Roundabout"], light_hardware=hw)
    e.advance(20)
    assert hw["TL-N"].sent and set(hw["TL-N"].sent) <= {"RED", "YELLOW", "GREEN", "OFF"}


def test_the_light_never_changes_the_simulations_own_state():
    """Attaching hardware must not change a single decision the phase machine makes."""
    def trace(seed, hw):
        e = SimulationEngine(seed=seed, layout=default_layout(), light_hardware=hw)
        e.configure(spawn_rate=30.0, ped_spawn_rate=10.0)
        out = []
        for _ in range(600):
            e._tick(0.1)
            out.append(tuple(sorted((l.id, l.state) for l in e._lights.values())))
        return out
    assert trace(7, {"TL-N": RecordingLight()}) == trace(7, {})


def test_green_blinks_once_then_yellow_fills_the_rest_of_the_window(monkeypatch):
    """A GREEN -> * edge must blink the real light GREEN_BLINK_COUNT times, then hold YELLOW for the remainder of
    GREEN_END_WINDOW_S, and only then show the new state — timed by wall clock so it never changes phase durations.
    Force the edge with a manual override so it fires on demand."""
    import smart_intersection.engine.simulation as sim_mod
    from smart_intersection.engine.simulation import GREEN_END_WINDOW_S

    clock = [1_000.0]
    monkeypatch.setattr(sim_mod.time, "monotonic", lambda: clock[0])
    hw = {"TL-N": RecordingLight()}
    e = SimulationEngine(seed=1, layout=default_layout(), light_hardware=hw)

    e.set_light_state("TL-N", "GREEN")
    e._tick(0.1)                                    # records GREEN as the last-seen state
    e.set_light_state("TL-N", "RED")                # GREEN -> RED edge, should start the blink
    hw["TL-N"].sent.clear()

    step = 0.3
    n = int(GREEN_END_WINDOW_S / step) + 3
    seen = []
    for _ in range(n):
        e._tick(0.1)
        seen.append(hw["TL-N"].sent[-1])
        clock[0] += step

    blink = seen[:GREEN_BLINK_COUNT * 2]
    assert blink == ["GREEN", "OFF"] * GREEN_BLINK_COUNT
    switched_at = next(i for i, s in enumerate(seen) if s == "RED")
    assert all(s == "YELLOW" for s in seen[GREEN_BLINK_COUNT * 2:switched_at])
    assert switched_at * step >= GREEN_END_WINDOW_S - step
    assert all(s == "RED" for s in seen[switched_at:])


def test_yellow_holds_for_a_couple_seconds_on_a_red_to_green_edge(monkeypatch):
    """A RED -> GREEN edge must hold YELLOW on the real signal for RED_TO_GREEN_YELLOW_S before actually going
    GREEN, timed by wall clock (not sim time) so it never changes phase durations."""
    import smart_intersection.engine.simulation as sim_mod
    from smart_intersection.engine.simulation import RED_TO_GREEN_YELLOW_S

    clock = [1_000.0]
    monkeypatch.setattr(sim_mod.time, "monotonic", lambda: clock[0])
    hw = {"TL-N": RecordingLight()}
    e = SimulationEngine(seed=1, layout=default_layout(), light_hardware=hw)

    e.set_light_state("TL-N", "RED")
    e._tick(0.1)                                    # default_layout starts TL-N GREEN, so this is a GREEN -> RED
    clock[0] += GREEN_BLINK_COUNT * 2 * GREEN_BLINK_HALF_S + 1.0  # drain that blink before starting the real test
    e._tick(0.1)                                    # now cleanly RED
    e.set_light_state("TL-N", "GREEN")              # RED -> GREEN edge, should hold YELLOW first
    hw["TL-N"].sent.clear()

    step = 0.5
    n = int(RED_TO_GREEN_YELLOW_S / step) + 3
    seen = []
    for _ in range(n):
        e._tick(0.1)
        seen.append(hw["TL-N"].sent[-1])
        clock[0] += step

    switched_at = next(i for i, s in enumerate(seen) if s == "GREEN")
    assert all(s == "YELLOW" for s in seen[:switched_at])
    assert switched_at * step >= RED_TO_GREEN_YELLOW_S - step
    assert all(s == "GREEN" for s in seen[switched_at:])


def test_no_hardware_configured_is_the_default_and_costs_nothing():
    e = SimulationEngine(seed=1)                                           # light_hardware omitted entirely
    e.advance(5)
    assert e._light_hw == {}


# ----------------------------------------------------------------------------- picking a light's IP from the layout

def test_the_layout_can_give_one_arm_its_own_physical_ip(udp_listener):
    l = default_layout()
    l.arms["north"].light_ip = udp_listener.getsockname()[0]
    l.arms["north"].light_port = udp_listener.getsockname()[1]
    e = SimulationEngine(seed=1, layout=l)
    assert "TL-N" in e._light_hw and "TL-S" not in e._light_hw            # only the arm that was given an IP
    e.advance(5)
    data, _ = udp_listener.recvfrom(1 << 20)
    assert data[8:] == _FRAMES[e._lights["TL-N"].state]
    e.close_hardware()


def test_a_layout_ip_overrides_the_config_file_default_for_the_same_light():
    l = default_layout()
    l.arms["north"].light_ip = "10.0.0.5"
    l.arms["north"].light_port = 1234
    e = SimulationEngine(seed=1, layout=l, light_hardware={"TL-N": RecordingLight(), "TL-S": RecordingLight()})
    assert e._light_hw["TL-N"].address == ("10.0.0.5", 1234)              # layout wins for TL-N
    assert isinstance(e._light_hw["TL-S"], RecordingLight)                # untouched default still applies to TL-S
    e.close_hardware()


def test_blank_or_whitespace_ip_means_virtual_only():
    from smart_intersection.layout import Arm
    assert Arm(light_ip="   ").light_ip is None
    assert Arm(light_ip="").light_ip is None
    assert Arm(light_ip="10.0.0.1").light_ip == "10.0.0.1"
    l = default_layout()
    l.arms["north"] = Arm(**{**l.arms["north"].model_dump(), "light_ip": "  "})
    assert l.arms["north"].light_ip is None
    e = SimulationEngine(seed=1, layout=l)
    assert "TL-N" not in e._light_hw


def test_changing_the_layout_ip_replaces_the_socket_and_closes_the_old_one():
    l = default_layout()
    l.arms["north"].light_ip, l.arms["north"].light_port = "127.0.0.1", 9600
    e = SimulationEngine(seed=1, layout=l)
    first = e._light_hw["TL-N"]
    l2 = default_layout()
    l2.arms["north"].light_ip, l2.arms["north"].light_port = "127.0.0.1", 9601
    e.set_layout(l2)
    assert e._light_hw["TL-N"] is not first and e._light_hw["TL-N"].address == ("127.0.0.1", 9601)
    assert first._sock is None                                            # the old socket was closed, not leaked
    e.close_hardware()


def test_close_hardware_only_closes_layout_owned_sockets():
    default = RecordingLight()
    l = default_layout()
    l.arms["north"].light_ip = "127.0.0.1"
    e = SimulationEngine(seed=1, layout=l, light_hardware={"TL-S": default})
    e.close_hardware()
    assert "TL-N" not in e._layout_light_hw                               # layout-owned socket closed and forgotten
    assert e._default_light_hw["TL-S"] is default                         # caller-owned one is untouched (caller closes it)


def test_the_api_round_trips_a_lights_ip(client):
    d = client.get("/layout").json()
    d["arms"]["north"]["light_ip"] = "192.168.1.198"
    d["arms"]["north"]["light_port"] = 9500
    r = client.put("/layout", json=d)
    assert r.status_code == 200
    assert client.get("/layout").json()["arms"]["north"]["light_ip"] == "192.168.1.198"
    assert client.get("/layout").json()["arms"]["north"]["light_port"] == 9500
