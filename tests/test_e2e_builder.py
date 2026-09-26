"""
UI end-to-end: a real Chrome drives the constructor with mouse and keyboard against the real services
(SI :8001, backend :8000, Vite :5173 - the ports the frontend is written for). Skipped when Chrome, node or the ports
are unavailable.
"""
import json
import math
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
CHROME = next((p for p in [os.environ.get("CHROME_PATH", ""), r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                           r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                           r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                           shutil.which("google-chrome") or "", shutil.which("chromium") or ""] if p and os.path.exists(p)), None)
PORTS = (8000, 8001, 5173)


def port_free(p):
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", p)) != 0


pytestmark = pytest.mark.skipif(
    CHROME is None or shutil.which("node") is None or not (ROOT / "frontend" / "node_modules").exists()
    or not all(port_free(p) for p in PORTS), reason="needs Chrome, node_modules and free ports 8000/8001/5173")

websockets_sync = pytest.importorskip("websockets.sync.client")


def wait(cond, timeout=15.0, step=0.1):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            if cond():
                return True
        except Exception:
            pass
        time.sleep(step)
    try:
        return bool(cond())
    except Exception:
        return False


class Browser:
    def __init__(self, tmp):
        self.port = 9444
        self.proc = subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={self.port}",
                                      f"--user-data-dir={tmp / 'chrome'}", "--disable-gpu", "--use-angle=swiftshader",
                                      "--enable-unsafe-swiftshader", "--hide-scrollbars", "--window-size=1600,900",
                                      "--no-first-run", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ws = None
        for _ in range(100):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json", timeout=1))
                ws = [t for t in tabs if t["type"] == "page"][0]["webSocketDebuggerUrl"]
                break
            except Exception:
                time.sleep(0.2)
        assert ws, "chrome did not start"
        self.ws = websockets_sync.connect(ws, max_size=50_000_000)
        self.n = 0
        self.call("Page.enable")
        self.call("Emulation.setDeviceMetricsOverride", width=1600, height=900, deviceScaleFactor=1, mobile=False)

    def call(self, method, **params):
        self.n += 1
        i = self.n
        self.ws.send(json.dumps({"id": i, "method": method, "params": params}))
        while True:
            m = json.loads(self.ws.recv(timeout=30))
            if m.get("id") == i:
                if "error" in m:
                    raise RuntimeError(m["error"])
                return m.get("result", {})

    def js(self, expr):
        r = self.call("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
        return r.get("result", {}).get("value")

    def goto(self, url):
        self.call("Page.navigate", url=url)

    def exists(self, testid):
        return bool(self.js(f"!!document.querySelector('[data-testid=\"{testid}\"]')"))

    def click_testid(self, testid):
        assert wait(lambda: self.exists(testid), 10), f"missing {testid}"
        self.js(f"document.querySelector('[data-testid=\"{testid}\"]').click()")

    def set_input(self, testid, value):
        """React-controlled input / select / range: use the native setter and fire the event."""
        self.js("""(() => { const el = document.querySelector('[data-testid="%s"]');
          const proto = el.tagName === 'SELECT' ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
          Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, %s);
          el.dispatchEvent(new Event(el.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true })); })()""" % (testid, json.dumps(str(value))))

    def toggle(self, testid):
        self.click_testid(testid)

    def mouse(self, kind, x, y, buttons=1):
        self.call("Input.dispatchMouseEvent", type=kind, x=x, y=y, button="left" if kind != "mouseMoved" else "none",
                  buttons=buttons if kind != "mouseReleased" else 0, clickCount=1)

    def key(self, key, ctrl=False):
        mods = 2 if ctrl else 0
        code = {"z": 90, "y": 89, "Delete": 46, "Escape": 27}.get(key, ord(key.upper()) if len(key) == 1 else 0)
        for t in ("keyDown", "keyUp"):
            self.call("Input.dispatchKeyEvent", type=t, key=key, code=key, windowsVirtualKeyCode=code, modifiers=mods)

    def canvas_rect(self):
        return self.js("(() => { const r = document.querySelector('canvas').getBoundingClientRect(); return {x: r.x, y: r.y, w: r.width, h: r.height}; })()")

    def project(self, x, z, y=0.0):
        """World point -> screen pixel for the initial camera (0, 90, 90) looking at the origin, fov 45."""
        rect = self.canvas_rect()
        P = (0.0, 90.0, 90.0)
        n = math.sqrt(P[1] ** 2 + P[2] ** 2)
        f = (0.0, -P[1] / n, -P[2] / n)
        r = (1.0, 0.0, 0.0)                                           # f x up, normalised
        up = (0.0, -f[2], f[1])                                        # r x f
        d = (x - P[0], y - P[1], z - P[2])
        dot = lambda a, b: sum(p * q for p, q in zip(a, b))
        depth = dot(d, f)
        t = math.tan(math.radians(45) / 2)
        ndc_x = dot(d, r) / depth / (t * rect["w"] / rect["h"])
        ndc_y = dot(d, up) / depth / t
        return rect["x"] + (ndc_x + 1) / 2 * rect["w"], rect["y"] + (1 - ndc_y) / 2 * rect["h"]

    def click_world(self, x, z):
        px, py = self.project(x, z)
        self.mouse("mouseMoved", px, py, 0)
        time.sleep(0.15)
        self.mouse("mousePressed", px, py)
        self.mouse("mouseReleased", px, py)
        time.sleep(0.2)

    def drag_world(self, a, b):
        (x0, y0), (x1, y1) = self.project(*a, y=0.5), self.project(*b)
        self.mouse("mouseMoved", x0, y0, 0)
        time.sleep(0.15)
        self.mouse("mousePressed", x0, y0)
        for k in range(1, 9):
            self.mouse("mouseMoved", x0 + (x1 - x0) * k / 8, y0 + (y1 - y0) * k / 8)
            time.sleep(0.03)
        self.mouse("mouseReleased", x1, y1)
        time.sleep(0.3)

    def close(self):
        try:
            self.ws.close()
        finally:
            self.proc.terminate()


@pytest.fixture(scope="module")
def stack(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("ui")
    env = {**os.environ}
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        env.pop(k, None)
    procs = [
        subprocess.Popen([sys.executable, "-m", "uvicorn", "smart_intersection.main:app", "--port", "8001", "--log-level", "warning"],
                         cwd=ROOT, env=env, stdout=open(tmp / "si.log", "wb"), stderr=subprocess.STDOUT),
        subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.main:app", "--port", "8000", "--log-level", "warning"],
                         cwd=ROOT, env=env, stdout=open(tmp / "be.log", "wb"), stderr=subprocess.STDOUT),
        subprocess.Popen(["npm.cmd" if os.name == "nt" else "npm", "run", "dev", "--", "--port", "5173", "--strictPort", "--host", "127.0.0.1"],
                         cwd=ROOT / "frontend", env=env, stdout=open(tmp / "vite.log", "wb"), stderr=subprocess.STDOUT),
    ]
    si = httpx.Client(base_url="http://127.0.0.1:8001", trust_env=False, timeout=5)
    try:
        assert wait(lambda: si.get("/health").status_code == 200, 40)
        assert wait(lambda: httpx.get("http://127.0.0.1:8000/api/health", trust_env=False).status_code == 200, 40)
        assert wait(lambda: httpx.get("http://127.0.0.1:5173/", trust_env=False).status_code == 200, 40)
        browser = Browser(tmp)
        try:
            yield browser, si
        finally:
            browser.close()
    finally:
        for p in procs:                                   # npm spawns node: kill the whole tree or the port stays busy
            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
            else:
                p.terminate()
        for p in procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()


def server_layout(si):
    return si.get("/layout").json()


def enter_build(b):
    b.goto("http://127.0.0.1:5173/simulation")
    assert wait(lambda: b.exists("edit-city"), 30)
    time.sleep(1.5)
    b.click_testid("edit-city")
    assert wait(lambda: b.exists("builder-panel"))


def test_build_mode_opens_and_shows_the_default_city(stack):
    b, si = stack
    enter_build(b)
    assert b.js("document.querySelector('[data-testid=\"builder-panel\"]').innerText.includes('City builder')")
    assert b.exists("tool-select") and b.exists("tool-delete")
    assert b.canvas_rect()["w"] > 800


def test_placing_objects_moves_them_and_refuses_roads(stack):
    b, si = stack
    enter_build(b)
    before = len(server_layout(si)["scenery"])
    b.click_testid("tool-place-tree")
    b.click_world(30, 30)                                             # free grass
    b.click_world(0, -40)                                             # on the north road: must be refused
    b.click_testid("tool-place-kiosk")
    b.click_world(-40, 40)
    b.click_testid("apply")
    assert wait(lambda: len(server_layout(si)["scenery"]) == before + 2), server_layout(si)["scenery"][-3:]
    added = server_layout(si)["scenery"][-2:]
    kinds = {o["type"]: o for o in added}
    assert abs(kinds["tree"]["x"] - 30) <= 3 and abs(kinds["tree"]["z"] - 30) <= 3
    assert abs(kinds["kiosk"]["x"] + 40) <= 3 and abs(kinds["kiosk"]["z"] - 40) <= 3
    assert not b.exists("errors")                                     # the refused click added nothing invalid


def test_drag_moves_an_object_and_dropping_on_a_road_is_undone(stack):
    b, si = stack
    enter_build(b)
    b.click_testid("tool-place-house")
    b.click_world(50, -50)
    b.click_testid("tool-select")
    b.drag_world((50, -50), (60, -60))
    b.click_testid("apply")
    house = next(o for o in server_layout(si)["scenery"] if o["type"] == "house" and abs(o["x"] - 60) <= 3)
    assert abs(house["z"] + 60) <= 3
    enter_build(b)
    b.drag_world((60, -60), (0, -50))                                 # onto the north road
    b.click_testid("apply")
    time.sleep(0.5)
    assert any(o["type"] == "house" and abs(o["x"] - 60) <= 3 for o in server_layout(si)["scenery"])   # snapped back
    assert not any(o["type"] == "house" and abs(o["x"]) <= 3 and abs(o["z"] + 50) <= 3 for o in server_layout(si)["scenery"])


def test_delete_tool_undo_and_redo(stack):
    b, si = stack
    enter_build(b)
    base = len(server_layout(si)["scenery"])
    b.click_testid("tool-place-bench")
    b.click_world(-50, 20)
    b.click_testid("tool-delete")
    b.click_world(-50, 20)
    b.click_testid("apply")
    assert wait(lambda: len(server_layout(si)["scenery"]) == base)      # placed and deleted again
    enter_build(b)
    disabled = lambda tid: b.js(f"document.querySelector('[data-testid=\"{tid}\"]').disabled")
    assert disabled("undo") and disabled("redo")                       # a fresh draft has no history
    b.click_testid("tool-place-bench")
    b.click_world(-50, 20)
    assert wait(lambda: not disabled("undo"))
    b.key("z", ctrl=True)                                              # undo the placement
    assert wait(lambda: disabled("undo") and not disabled("redo"))
    b.key("y", ctrl=True)                                              # redo brings it back
    assert wait(lambda: not disabled("undo") and disabled("redo"))
    b.key("z", ctrl=True)
    b.key("z", ctrl=True)                                              # nothing left to undo: must not break anything
    b.click_testid("apply")
    time.sleep(0.5)
    assert len(server_layout(si)["scenery"]) == base                   # the undone bench never reached the server


def test_roads_signals_and_traffic_are_edited_and_applied(stack):
    b, si = stack
    enter_build(b)
    b.click_testid("tab-roads")
    b.toggle("arm-south-enabled")
    b.set_input("arm-north-lane", "bus")
    b.set_input("arm-east-length", "50")
    b.toggle("arm-west-crossing")
    b.click_testid("tab-signals")
    b.set_input("signal-mode", "fixed")
    assert wait(lambda: b.exists("phase-0"))
    b.set_input("phase-0-duration", "17")
    b.click_testid("phase-add")
    b.click_testid("tab-traffic")
    b.set_input("traffic-rate", "33")
    time.sleep(0.8)                                                    # live validation settles
    b.click_testid("apply")
    assert wait(lambda: server_layout(si)["signal"]["mode"] == "fixed")
    l = server_layout(si)
    assert l["arms"]["south"]["enabled"] is False and l["arms"]["north"]["lane_type"] == "bus"
    assert l["arms"]["east"]["length_m"] == 50 and l["arms"]["west"]["crossing"] is False
    assert l["signal"]["program"][0]["duration"] == 17 and len(l["signal"]["program"]) == 7
    assert l["traffic"]["spawn_rate"] == 33
    state = si.get("/simulation/state").json()
    assert {x["id"] for x in state["lights"]} == {"TL-N", "TL-E", "TL-W"} and state["signal_mode"] == "fixed"


def test_server_validation_errors_reach_the_user(stack):
    b, si = stack
    enter_build(b)
    b.click_testid("tab-signals")
    b.set_input("signal-mode", "fixed")
    assert wait(lambda: b.exists("phase-0"))
    b.click_testid("phase-0-ns-GREEN")
    b.click_testid("phase-0-ew-GREEN")                                 # both directions open: a collision
    assert wait(lambda: b.exists("errors"), 10)
    assert b.js("document.querySelector('[data-testid=\"errors\"]').innerText.includes('same time')")
    b.click_testid("apply")
    time.sleep(0.6)
    assert server_layout(si)["signal"]["program"][0]["ew"] != "GREEN" or server_layout(si)["signal"]["program"][0]["ns"] != "GREEN"


def test_save_load_and_presets_and_remembered_across_reload(stack):
    b, si = stack
    enter_build(b)
    b.click_testid("tab-layouts")
    b.click_testid("preset-T-junction")
    b.click_testid("apply")
    assert wait(lambda: server_layout(si)["name"] == "T-junction")
    b.click_testid("tab-layouts")
    b.set_input("layout-name", "UI city")
    b.click_testid("layout-save")
    assert wait(lambda: "UI city" in si.get("/layouts").json()["saved"])
    b.click_testid("preset-Crossroads")
    b.click_testid("apply")
    assert wait(lambda: server_layout(si)["name"] == "Crossroads")
    b.click_testid("tab-layouts")
    b.click_testid("load-UI city")
    b.click_testid("apply")
    assert wait(lambda: server_layout(si)["name"] == "UI city")
    b.goto("http://127.0.0.1:5173/simulation")
    assert wait(lambda: b.exists("edit-city"), 30)
    assert server_layout(si)["name"] == "UI city"


def test_play_spawn_tool_adds_a_vehicle_and_a_person(stack):
    b, si = stack
    si.put("/layout", json=si.get("/layouts/UI city").json() | {"name": "Crossroads"})
    si.post("/simulation/config", json={"spawn_rate": 0, "ped_spawn_rate": 0})
    b.goto("http://127.0.0.1:5173/simulation")
    assert wait(lambda: b.exists("edit-city"), 30)
    time.sleep(1.5)
    si.post("/simulation/start")
    b.click_testid("tool-spawn:car")
    b.click_world(0, -60)                                              # next to the north road
    assert wait(lambda: len(si.get("/simulation/state").json()["vehicles"]) == 1), si.get("/simulation/state").json()["vehicles"]
    assert si.get("/simulation/state").json()["vehicles"][0]["direction"] == "north"
    b.click_testid("tool-spawn:person")
    b.click_world(60, 5)
    assert wait(lambda: len(si.get("/simulation/state").json()["pedestrians"]) >= 1)


def test_play_button_applies_pending_changes_and_starts_the_simulation(stack):
    b, si = stack
    enter_build(b)
    b.click_testid("tab-traffic")
    b.set_input("traffic-rate", "40")
    time.sleep(0.6)
    b.click_testid("play")
    assert wait(lambda: server_layout(si)["traffic"]["spawn_rate"] == 40)
    assert wait(lambda: si.get("/simulation/state").json()["status"] == "running")
    assert wait(lambda: not b.exists("builder-panel"))
