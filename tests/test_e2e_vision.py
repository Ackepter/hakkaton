r"""
End-to-end: two REAL processes (Smart Intersection service + main backend) connected only through HTTP/XML,
exactly like start.bat runs them.

    SI -> virtual camera -> detections -> analysis -> perception -> SI signals
                                       \-> Dashboard metrics / FAILSAFE
"""
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def http(base):
    return httpx.Client(base_url=base, timeout=5.0, trust_env=False)


def wait(cond, timeout=10.0, step=0.1):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            if cond():
                return True
        except (httpx.HTTPError, KeyError, TypeError):
            pass
        time.sleep(step)
    try:
        return bool(cond())
    except (httpx.HTTPError, KeyError, TypeError):
        return False


class Proc:
    def __init__(self, args, env, log):
        self.args, self.env, self.log = args, env, log
        self.p = None

    def start(self):
        self.p = subprocess.Popen([sys.executable, "-m", "uvicorn", *self.args], cwd=ROOT, env=self.env,
                                  stdout=open(self.log, "ab"), stderr=subprocess.STDOUT)

    def stop(self):
        if self.p and self.p.poll() is None:
            self.p.terminate()
            try:
                self.p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.p.kill()


@pytest.fixture(scope="module")
def system(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("e2e")
    si_port, be_port = free_port(), free_port()
    cams = tmp / "cameras.yaml"
    cams.write_text(yaml.safe_dump({"cameras": [{
        "id": "CAM-01", "source": "simulation", "uri": f"http://127.0.0.1:{si_port}", "detector": "virtual",
        "fps": 10, "width": 640, "height": 640, "timeout_s": 1.5, "reconnect_s": 0.5}]}))
    env = {**os.environ, "VISION_CONFIG_PATH": str(cams), "SI_BASE_URL": f"http://127.0.0.1:{si_port}",
           "HOST": "127.0.0.1", "PORT": str(be_port)}
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        env.pop(k, None)
    si = Proc(["smart_intersection.main:app", "--port", str(si_port), "--log-level", "warning"], env, tmp / "si.log")
    be = Proc(["backend.main:app", "--port", str(be_port), "--log-level", "warning"], env, tmp / "be.log")
    si.start()
    be.start()
    si_url, be_url = f"http://127.0.0.1:{si_port}", f"http://127.0.0.1:{be_port}"
    try:
        assert wait(lambda: http(si_url).get("/health").status_code == 200, 30), (tmp / "si.log").read_text()
        assert wait(lambda: http(be_url).get("/api/health").status_code == 200, 30), (tmp / "be.log").read_text()
        yield si, be, si_url, be_url
    finally:
        be.stop()
        si.stop()
        print((tmp / "be.log").read_text(errors="ignore")[-1500:])


@pytest.fixture
def running_sim(system):
    """Start a busy scenario and reset camera / failure switches afterwards."""
    si, be, si_url, be_url = system
    s, b = http(si_url), http(be_url)
    s.post("/scenario/start", json={"scenario_id": "heavy"})
    s.post("/simulation/config", json={"time_scale": 5})
    s.post("/simulation/camera-failure", json={"active": False})
    b.post("/api/vision/cameras/CAM-01/connect")
    assert wait(lambda: b.get("/api/vision/cameras").json()["healthy"], 15)
    yield s, b, si_url, be_url
    s.post("/simulation/camera-failure", json={"active": False})
    b.post("/api/vision/cameras/CAM-01/connect")
    s.post("/simulation/stop")


def mode(b):
    return b.get("/api/control/status").json()["mode"]


def test_camera_sees_the_simulation(running_sim):
    s, b, *_ = running_sim
    assert wait(lambda: b.get("/api/vision/cameras/CAM-01/detections").json()["detections"], 15)
    cam = b.get("/api/vision/cameras/CAM-01").json()
    assert cam["state"] == "connected" and cam["fps"] > 2 and cam["detector"]["name"] == "virtual"
    assert wait(lambda: b.get("/api/vision/analysis").json()["vehicles"] > 0, 15)


def test_camera_counts_match_the_simulation_ground_truth(running_sim):
    """The detections come from the XML the simulation published, so per-arm counts must track the real queues."""
    s, b, *_ = running_sim
    time.sleep(6)
    diffs = []
    for _ in range(8):
        truth = s.get("/simulation/state").json()
        seen = b.get("/api/vision/analysis").json()
        assert seen is not None
        veh_in_view = [v for v in truth["vehicles"] if abs(v["position_m"] - 80) <= 64]
        diffs.append(abs(len(veh_in_view) - seen["vehicles"]))
        time.sleep(0.5)
    assert min(diffs) <= 2 and sum(diffs) / len(diffs) <= 6      # a few frames of latency at 5x speed, no more


def test_mjpeg_stream_delivers_real_jpeg_frames(running_sim):
    *_, be_url = running_sim
    got = []
    with httpx.stream("GET", f"{be_url}/api/vision/cameras/CAM-01/stream", timeout=10, trust_env=False) as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("multipart/x-mixed-replace")
        buf = b""
        for chunk in r.iter_bytes():
            buf += chunk
            got = buf.split(b"--frame")
            if len(got) >= 4:
                break
    frames = [g.split(b"\r\n\r\n", 1)[1].rstrip(b"\r\n") for g in got[1:-1] if b"\r\n\r\n" in g]
    assert len(frames) >= 2 and all(f[:2] == b"\xff\xd8" and f[-2:] == b"\xff\xd9" for f in frames)


def test_snapshot_shows_the_simulated_scene(running_sim):
    from PIL import Image
    import io
    s, b, *_ = running_sim
    img = Image.open(io.BytesIO(b.get("/api/vision/cameras/CAM-01/snapshot.jpg").content)).convert("RGB")
    assert img.size == (640, 640)
    assert len(img.getcolors(maxcolors=200_000)) > 50           # a real picture, not a placeholder


def test_simulation_signals_are_driven_by_the_camera(running_sim):
    s, b, *_ = running_sim
    assert wait(lambda: s.get("/simulation/state").json()["perception"] == {"active": True, "camera_ok": True,
                                                                              "stale": False}, 15)
    assert s.get("/simulation/state").json()["failsafe_reason"] is None
    assert mode(b) == "AUTO"


def test_virtual_camera_failure_puts_both_sides_in_failsafe_and_recovers(running_sim):
    s, b, *_ = running_sim
    assert wait(lambda: s.get("/simulation/state").json()["perception"]["active"], 15)
    s.post("/simulation/camera-failure", json={"active": True})                  # scenario 8: detection lost
    assert wait(lambda: mode(b) == "FAILSAFE", 15)
    assert wait(lambda: s.get("/simulation/state").json()["failsafe_reason"] == "camera failure", 5)
    assert b.get("/api/health").status_code == 200                                # Dashboard backend keeps running
    st = b.get("/api/vision/cameras").json()
    assert st["healthy"] is False and st["cameras"][0]["state"] in ("no_signal", "error", "connecting")
    s.post("/simulation/camera-failure", json={"active": False})
    assert wait(lambda: mode(b) == "AUTO", 15)
    assert wait(lambda: s.get("/simulation/state").json()["failsafe_reason"] is None, 10)


def test_disconnecting_the_camera_in_the_backend_switches_the_simulation_to_failsafe(running_sim):
    s, b, *_ = running_sim
    assert wait(lambda: s.get("/simulation/state").json()["perception"]["camera_ok"], 15)
    b.post("/api/vision/cameras/CAM-01/disconnect")
    assert mode(b) == "FAILSAFE"
    assert wait(lambda: s.get("/simulation/state").json()["failsafe_reason"] == "camera unavailable", 5)
    b.post("/api/vision/cameras/CAM-01/connect")
    assert wait(lambda: mode(b) == "AUTO", 15)
    assert wait(lambda: s.get("/simulation/state").json()["failsafe_reason"] is None, 10)


def test_fixed_timing_is_really_used_during_the_outage(running_sim):
    """In FAILSAFE the simulation's greens are exactly 20 s of simulation time."""
    s, b, *_ = running_sim
    s.post("/simulation/config", json={"time_scale": 5})
    assert wait(lambda: s.get("/simulation/state").json()["perception"]["active"], 15)
    s.post("/simulation/camera-failure", json={"active": True})
    seen, last, start = [], None, None
    end = time.monotonic() + 60
    while time.monotonic() < end and len(seen) < 2:
        st = s.get("/simulation/state").json()
        idx, t = st["phase"]["index"], st["sim_time"]
        if last is not None and idx != last and last in (0, 3) and start is not None:
            seen.append(t - start)
        if idx != last:
            last, start = idx, t
        time.sleep(0.02)
    assert seen, "no complete green phase observed"
    assert all(19.0 <= g <= 22.0 for g in seen), seen                               # 20 s +- polling error at 5x


def test_backend_and_dashboard_survive_the_simulation_dying_and_recover_when_it_returns(system):
    si, be, si_url, be_url = system
    s, b = http(si_url), http(be_url)
    s.post("/scenario/start", json={"scenario_id": "normal"})
    b.post("/api/vision/cameras/CAM-01/connect")
    assert wait(lambda: b.get("/api/vision/cameras").json()["healthy"], 15)
    si.stop()                                                                      # Smart Intersection crashes
    assert wait(lambda: mode(b) == "FAILSAFE", 15)
    assert b.get("/api/health").status_code == 200
    ws_ok = b.get("/api/vision/cameras").json()
    assert ws_ok["active"] and not ws_ok["healthy"]                                 # reported, not raised
    assert b.get("/api/vision/cameras/CAM-01/snapshot.jpg").status_code == 200      # placeholder picture
    si.start()                                                                      # ... and comes back
    assert wait(lambda: http(si_url).get("/health").status_code == 200, 30)
    http(si_url).post("/scenario/start", json={"scenario_id": "normal"})
    assert wait(lambda: mode(b) == "AUTO", 30)
    assert wait(lambda: b.get("/api/vision/analysis").json() is not None, 10)


def test_dashboard_websocket_carries_camera_state(system):
    from websockets.sync.client import connect
    _, _, _, be_url = system
    with connect(be_url.replace("http", "ws") + "/ws", open_timeout=5) as ws:
        for _ in range(6):
            msg = json.loads(ws.recv(timeout=5))
            if msg.get("type") == "state_update":
                break
    assert msg["vision"]["active"] is True and msg["vision"]["cameras"][0]["id"] == "CAM-01"
    assert "camera_status" in msg["metrics"]["system"]
