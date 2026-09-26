"""The constructor's browser-side geometry must agree with the server's validation on every point."""
import json
import random
import shutil
import subprocess
from pathlib import Path

import pytest

from smart_intersection.layout import SCENE_TYPES, default_layout, hits_road, presets

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

RUNNER = """
import { hitsRoad, roadRects, SCENE_TYPES, snap, nearestArm, nextId } from './frontend/src/builder/geometry.js'
import fs from 'node:fs'
const cases = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'))
const out = cases.map(c => ({
  hits: hitsRoad(c.layout, c.x, c.z, c.r), rects: roadRects(c.layout).length,
}))
const radii = Object.fromEntries(Object.entries(SCENE_TYPES).map(([k, v]) => [k, v.radius]))
console.log(JSON.stringify({ out, radii, snap: [snap(3.1), snap(-3.1), snap(0.9), snap(1.0)],
  arms: [nearestArm(50, 3), nearestArm(-50, 3), nearestArm(3, 50), nearestArm(3, -50)],
  ids: [nextId({ scenery: [{ id: 'tree-1' }, { id: 'tree-2' }], cameras: [] }, 'tree'),
        nextId({ scenery: [], cameras: [{ id: 'cam-1' }] }, 'cam')] }))
"""


def run_node(tmp_path, cases):
    (tmp_path / "cases.json").write_text(json.dumps(cases))
    (tmp_path / "run.mjs").write_text(RUNNER)
    # the runner imports relative to the repo root
    script = ROOT / "_geometry_runner.mjs"
    script.write_text(RUNNER)
    try:
        r = subprocess.run(["node", str(script), str(tmp_path / "cases.json")], cwd=ROOT, capture_output=True, text=True,
                           timeout=60)
    finally:
        script.unlink(missing_ok=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def sample_cases(n=1500):
    rng = random.Random(7)
    layouts = list(presets().values())
    odd = default_layout()
    odd.arms["north"].length_m = 45
    odd.arms["east"].crossing = False
    odd.arms["west"].enabled = False
    layouts.append(odd)
    cases = []
    for _ in range(n):
        l = rng.choice(layouts)
        r = rng.choice([0.6, 0.8, 1, 1.8, 2.5, 4, 5]) * rng.choice([1, 1.5, 3])
        cases.append({"layout": l.model_dump(), "x": rng.uniform(-100, 100), "z": rng.uniform(-100, 100), "r": r})
    # the tricky places: road edges, crosswalk bands, the box corners
    for x, z in [(4.0, -40), (4.5, -40), (5, -22), (9, -18.5), (9.5, -18.5), (16, 16), (16.2, 16.2), (0, -19.99), (0, -20.01)]:
        cases.append({"layout": default_layout().model_dump(), "x": x, "z": z, "r": 0.8})
    return cases


def test_browser_hit_test_equals_the_server_hit_test(tmp_path):
    cases = sample_cases()
    res = run_node(tmp_path, cases)
    mismatches = [(c["x"], c["z"], c["r"]) for c, o in zip(cases, res["out"])
                  if o["hits"] != hits_road(type(default_layout()).model_validate(c["layout"]), c["x"], c["z"], c["r"])]
    assert not mismatches, mismatches[:5]
    assert any(o["hits"] for o in res["out"]) and not all(o["hits"] for o in res["out"])


def test_scene_type_footprints_match():
    res = run_node(Path(__import__("tempfile").mkdtemp()), sample_cases(1))
    assert res["radii"] == SCENE_TYPES


def test_small_helpers():
    res = run_node(Path(__import__("tempfile").mkdtemp()), sample_cases(1))
    assert res["snap"] == [4, -4, 0, 2]
    assert res["arms"] == ["east", "west", "south", "north"]
    assert res["ids"] == ["tree-3", "cam-2"]
