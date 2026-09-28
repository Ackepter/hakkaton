"""The constructor's browser-side geometry must agree with the server on every ready-made junction."""
import json
import random
import shutil
import subprocess
from pathlib import Path

import pytest

from backend.vision.camera_model import CameraPose, PinholeCamera
from smart_intersection.geometry import light_pole
from smart_intersection.layout import (ARMS, Layout, SCENE_TYPES, box_half, default_layout, hits_road, is_split, min_arm_length,
                                       presets, stages, has_crossing)

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

RUNNER = """
import { hitsRoad, roadRects, boxHalf, stages, isSplit, minArmLength, lightPole, cameraFootprint, cameraAim, ARMS,
         SCENE_TYPES, snap, nearestArm, nextId, pedestrianLightPoles, hasCrossing } from './frontend/src/builder/geometry.js'
import fs from 'node:fs'
const data = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'))
const out = data.cases.map(c => ({ hits: hitsRoad(c.layout, c.x, c.z, c.r), rects: roadRects(c.layout).length }))
const meta = data.layouts.map(l => ({ box: boxHalf(l), stages: stages(l), split: isSplit(l), minLen: minArmLength(l),
  poles: ARMS.filter(a => l.arms[a].enabled).map(a => lightPole(l, a)),
  pedPoles: ARMS.filter(a => hasCrossing(l, a)).map(a => [a, pedestrianLightPoles(l, a)]) }))
const cams = data.cameras.map(c => ({ foot: cameraFootprint(c, 4 / 3), aim: cameraAim(c) }))
const radii = Object.fromEntries(Object.entries(SCENE_TYPES).map(([k, v]) => [k, v.radius]))
console.log(JSON.stringify({ out, meta, cams, radii, snap: [snap(3.1), snap(-3.1), snap(0.9), snap(1.0)],
  arms: [nearestArm(50, 3), nearestArm(-50, 3), nearestArm(3, 50), nearestArm(3, -50)],
  ids: [nextId({ scenery: [{ id: 'tree-1' }, { id: 'tree-2' }], cameras: [] }, 'tree'),
        nextId({ scenery: [], cameras: [{ id: 'cam-1' }] }, 'cam')] }))
"""

CAMERAS = [dict(id="a", x=-24, z=-24, height_m=14, fov_deg=70, radius_m=90, yaw_deg=None, pitch_deg=None),
           dict(id="b", x=0, z=0, height_m=45, fov_deg=100, radius_m=150, yaw_deg=None, pitch_deg=90),
           dict(id="c", x=30, z=-10, height_m=8, fov_deg=50, radius_m=60, yaw_deg=200, pitch_deg=25),
           dict(id="d", x=-40, z=35, height_m=20, fov_deg=110, radius_m=100, yaw_deg=None, pitch_deg=35)]


def layouts():
    out = list(presets().values())
    odd = default_layout()
    odd.arms["north"].length_m = 45
    odd.arms["east"].crossing = False
    odd.arms["west"].enabled = False
    out.append(odd)
    wide = default_layout()
    wide.arms["south"].lanes_in = 3
    wide.arms["south"].lanes_out = 1
    wide.arms["east"].lanes_out = 2
    out.append(wide)
    return out


def run_node(tmp_path, payload):
    (tmp_path / "cases.json").write_text(json.dumps(payload))
    script = ROOT / "_geometry_runner.mjs"          # the runner imports relative to the repo root
    script.write_text(RUNNER)
    try:
        r = subprocess.run(["node", str(script), str(tmp_path / "cases.json")], cwd=ROOT, capture_output=True, text=True,
                           timeout=60)
    finally:
        script.unlink(missing_ok=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def sample_cases(n=2500):
    rng = random.Random(7)
    ls = layouts()
    cases = []
    for _ in range(n):
        l = rng.choice(ls)
        r = rng.choice([0.6, 0.8, 1, 1.8, 2.5, 4, 5]) * rng.choice([1, 1.5, 3])
        cases.append({"layout": l.model_dump(), "x": rng.uniform(-110, 110), "z": rng.uniform(-110, 110), "r": r})
    # the tricky places: road edges, crosswalk bands, the box corners
    for x, z in [(4.0, -40), (4.5, -40), (5, -22), (9, -18.5), (9.5, -18.5), (16, 16), (16.2, 16.2), (0, -19.99), (0, -20.01)]:
        cases.append({"layout": default_layout().model_dump(), "x": x, "z": z, "r": 0.8})
    return cases


def payload(cases=None):
    return {"cases": cases if cases is not None else sample_cases(1), "layouts": [l.model_dump() for l in layouts()],
            "cameras": CAMERAS}


def test_browser_hit_test_equals_the_server_hit_test(tmp_path):
    cases = sample_cases()
    res = run_node(tmp_path, payload(cases))
    mismatches = [(c["x"], c["z"], c["r"], c["layout"]["name"]) for c, o in zip(cases, res["out"])
                  if o["hits"] != hits_road(Layout.model_validate(c["layout"]), c["x"], c["z"], c["r"])]
    assert not mismatches, mismatches[:5]
    assert any(o["hits"] for o in res["out"]) and not all(o["hits"] for o in res["out"])


def test_box_size_stages_and_light_poles_match():
    res = run_node(Path(__import__("tempfile").mkdtemp()), payload())
    for l, m in zip(layouts(), res["meta"]):
        assert m["box"] == box_half(l), l.name
        assert m["minLen"] == min_arm_length(l), l.name
        assert m["stages"] == [list(s) for s in stages(l)], l.name
        assert m["split"] == is_split(l), l.name
        assert [tuple(p) for p in m["poles"]] == [light_pole(l, a) for a in ARMS if l.arms[a].enabled], l.name


def test_each_crosswalk_has_two_pedestrian_signals_facing_inward():
    res = run_node(Path(__import__("tempfile").mkdtemp()), payload())
    for layout, meta in zip(layouts(), res["meta"]):
        expected = {a for a in ARMS if has_crossing(layout, a)}
        assert {a for a, _ in meta["pedPoles"]} == expected
        for arm, poles in meta["pedPoles"]:
            assert len(poles) == 2, (layout.name, arm)
            assert poles[0]["pos"] != poles[1]["pos"]


def test_camera_footprint_and_auto_aim_match_the_vision_module():
    res = run_node(Path(__import__("tempfile").mkdtemp()), payload())
    for c, o in zip(CAMERAS, res["cams"]):
        cam = PinholeCamera(CameraPose(x=c["x"], z=c["z"], height_m=c["height_m"], yaw_deg=c["yaw_deg"], pitch_deg=c["pitch_deg"],
                                       fov_deg=c["fov_deg"], range_m=c["radius_m"]), 640, 480)
        assert o["aim"] == pytest.approx([cam.yaw, cam.pitch], abs=1e-6), c["id"]
        flat = lambda pts: [v for p in pts for v in p]
        assert flat(o["foot"]) == pytest.approx(flat(cam.footprint(c["radius_m"])), abs=1e-4), c["id"]


def test_scene_type_footprints_match():
    res = run_node(Path(__import__("tempfile").mkdtemp()), payload())
    assert res["radii"] == SCENE_TYPES


def test_small_helpers():
    res = run_node(Path(__import__("tempfile").mkdtemp()), payload())
    assert res["snap"] == [4, -4, 0, 2]
    assert res["arms"] == ["east", "west", "south", "north"]
    assert res["ids"] == ["tree-3", "cam-2"]
