"""
The virtual camera (main project) and the simulation (separate service) share only data: XML + the road geometry
JSON. These tests check the camera model itself (pinhole projection, field of view, range), that its constants agree
with the simulation, and that picture, detections and zones all come from the same projection.
"""
import math
from types import SimpleNamespace

import pytest

from backend.vision import sim_view as sv
from backend.vision.camera_model import CameraPose, PinholeCamera
from backend.vision.sim_view import SimView, default_geometry
from backend.xml_parser.parser import XmlParser
from smart_intersection.engine.models import VEHICLE_DEFAULTS
from smart_intersection.geometry import scene_geometry
from smart_intersection.layout import Layout, default_layout, presets
from smart_intersection.tests.helpers import make_engine
from smart_intersection.xml_export.exporter import SimStateExporter
from .vision_helpers import sim_xml

GRASS = (63, 125, 63)


def parsed(engine):
    return XmlParser.parse(SimStateExporter.to_xml(engine.get_state()), validate=False)


def empty_state(lights=()):
    return SimpleNamespace(vehicles=[], pedestrians=[], lights=list(lights), simulation=SimpleNamespace(sim_time=0.0))


def top_down(height=60.0, fov=100.0, rng=200.0, w=640, h=640, geometry=None):
    return SimView(w, h, CameraPose(x=0, z=0, height_m=height, yaw_deg=0, pitch_deg=90, fov_deg=fov, range_m=rng), geometry)


# ------------------------------------------------------------------------------------------ constants vs. simulation

def test_default_geometry_matches_the_simulation_geometry():
    """The camera falls back to this before the simulation answered; it must be the default crossroads of the simulation."""
    assert default_geometry() == scene_geometry(default_layout())


@pytest.mark.parametrize("vtype", sorted(VEHICLE_DEFAULTS))
def test_vehicle_sizes_match_the_simulation(vtype):
    d = VEHICLE_DEFAULTS[vtype]
    assert sv.VEHICLE_SIZE[vtype][:2] == (d["length_m"], d["width_m"])


# ------------------------------------------------------------------------------------------ the pinhole model

def test_a_camera_aimed_at_a_point_puts_it_in_the_middle_of_the_picture():
    for pose in (CameraPose(x=-24, z=-24, height_m=14), CameraPose(x=30, z=10, height_m=8), CameraPose(x=0, z=-40, height_m=20)):
        cam = PinholeCamera(pose, 640, 480)
        px, py, depth = cam.project(0, 0, 0)
        assert (px, py) == pytest.approx((320, 240), abs=1e-6) and depth > 0


def test_compass_yaw_and_downward_tilt():
    cam = PinholeCamera(CameraPose(x=0, z=0, height_m=10, yaw_deg=90, pitch_deg=30, fov_deg=60), 640, 480)
    assert cam.yaw == 90 and cam.pitch == 30
    ahead = cam.project(30, 0, 0)                          # east of the mast = in front
    left = cam.project(30, 0, -20)                         # north of it = to the left when looking east
    behind = cam.project(-30, 0, 0)
    assert ahead is not None and ahead[0] == pytest.approx(320, abs=1.0)
    assert left[0] < ahead[0] and behind is None


def test_field_of_view_limits_what_is_in_frame():
    narrow = PinholeCamera(CameraPose(x=0, z=0, height_m=10, yaw_deg=0, pitch_deg=20, fov_deg=40), 640, 480)
    wide = PinholeCamera(CameraPose(x=0, z=0, height_m=10, yaw_deg=0, pitch_deg=20, fov_deg=110), 640, 480)
    point = (-25.0, 0.0, -30.0)                            # 40 degrees to the left of the axis
    for cam, inside in ((narrow, False), (wide, True)):
        px, py, _ = cam.project(*point)
        assert (0 <= px <= 640) is inside


def test_horizontal_fov_is_what_the_configuration_says():
    cam = PinholeCamera(CameraPose(x=0, z=0, height_m=1.0, yaw_deg=0, pitch_deg=1.0, fov_deg=90), 800, 600)
    edge = cam.project(-40, 1.0 - 40 * math.tan(math.radians(1.0)), -40)       # 45 degrees left, on the optical axis height
    assert edge[0] == pytest.approx(0, abs=2.0)


def test_footprint_is_the_area_on_the_ground_the_camera_covers():
    cam = PinholeCamera(CameraPose(x=0, z=0, height_m=30, yaw_deg=0, pitch_deg=90, fov_deg=90), 640, 640)
    xs = [p[0] for p in cam.footprint(500)]
    zs = [p[1] for p in cam.footprint(500)]
    assert min(xs) == pytest.approx(-30, abs=0.5) and max(xs) == pytest.approx(30, abs=0.5)
    assert min(zs) == pytest.approx(-30, abs=0.5) and max(zs) == pytest.approx(30, abs=0.5)


# ------------------------------------------------------------------------------------------ detections

def test_virtual_detections_match_ground_truth_of_the_running_simulation():
    e = make_engine("heavy")
    e.advance(80)
    view = top_down(height=45, fov=110, rng=200)
    dets = view.detections(parsed(e))
    vehicles = [d for d in dets if d.cls != "person"]
    truth = {(round(v.x, 2), round(v.z, 2)) for v in e._vehicles.values()}
    in_frame = {(round(v.x, 2), round(v.z, 2)) for v in e._vehicles.values() if view.sees(v.x, v.z)}
    seen = {d.world for d in vehicles}
    assert seen <= truth and len(vehicles) >= 0.9 * len(in_frame) > 5           # only fully hidden ones may be missing
    assert sum(1 for d in dets if d.cls == "person") == sum(1 for p in e._pedestrians.values() if p.state != "finished")
    for d in dets:
        assert 0 <= d.x <= 1 and 0 <= d.y <= 1 and 0 < d.w <= 1 and 0 < d.h <= 1
        assert d.foot is not None and 0 <= d.foot[0] <= 1


def test_detection_box_is_the_projection_of_the_vehicle():
    e = make_engine("heavy")
    e.advance(60)
    view = top_down(height=80, fov=100)
    data = parsed(e)
    for d in view.detections(data):
        if d.cls == "person":
            continue
        length, width, _ = sv.VEHICLE_SIZE[d.cls if d.cls != "car" else "car"] if d.cls in sv.VEHICLE_SIZE else (4.5, 2.0, 1.5)
        cx, cy = view.to_norm(*d.world, y=0.75)
        assert d.x == pytest.approx(cx, abs=0.06) and d.y == pytest.approx(cy, abs=0.06)
        assert d.foot == pytest.approx(view.to_norm(*d.world), abs=1e-6)


def test_objects_farther_than_the_range_are_not_detected():
    e = make_engine("heavy")
    e.advance(80)
    data = parsed(e)
    wide = top_down(height=90, fov=110, rng=200).detections(data)
    near = top_down(height=90, fov=110, rng=30).detections(data)
    assert 0 < len(near) < len(wide)
    assert all(math.hypot(*d.world) <= 30 for d in near)


def test_a_narrow_field_of_view_sees_fewer_objects():
    e = make_engine("heavy")
    e.advance(80)
    data = parsed(e)
    pose = dict(x=-24, z=-24, height_m=14, range_m=200)
    wide = SimView(640, 480, CameraPose(fov_deg=110, **pose)).detections(data)
    narrow = SimView(640, 480, CameraPose(fov_deg=30, **pose)).detections(data)
    assert 0 < len(narrow) < len(wide)


def test_a_vehicle_hidden_behind_a_nearer_one_is_not_reported():
    v = lambda i, x: SimpleNamespace(id=i, vehicle_type="truck", lane_id="x", direction="north", position_m=0, speed_mps=0,
                                     state="waiting", wait_time=0, x=x, z=0.0, heading=math.pi / 2, movement="straight")
    view = SimView(640, 480, CameraPose(x=0, z=-40, height_m=2.5, yaw_deg=180, pitch_deg=5, fov_deg=70, range_m=200))
    data = SimpleNamespace(vehicles=[v("near", 0.0)], pedestrians=[])
    both = SimpleNamespace(vehicles=[v("near", 0.0), SimpleNamespace(**{**v("far", 0.0).__dict__, "z": 20.0})], pedestrians=[])
    assert {d.source_id for d in view.detections(data)} == {"near"}
    assert {d.source_id for d in view.detections(both)} == {"near"}            # the far truck is completely behind it


# ------------------------------------------------------------------------------------------ zones

def test_zones_follow_the_camera_view():
    g = scene_geometry(default_layout())
    everything = {z.id for z in top_down(90, 110, 300, geometry=g).zones()}
    assert everything == {f"{a}-in" for a in ("north", "south", "east", "west")} | {f"PC-{a}" for a in "NSEW"}
    looking_away = SimView(640, 480, CameraPose(x=0, z=40, height_m=12, yaw_deg=180, pitch_deg=20, fov_deg=70), g).zones()
    assert looking_away == [] or {z.id for z in looking_away}.isdisjoint({"south-in", "PC-S"})
    ids = {z.id for z in SimView(640, 480, CameraPose(x=-24, z=-24, height_m=14, fov_deg=40, range_m=90), g).zones()}
    assert ids and ids < everything                                            # a narrow lens sees only part of the junction


def test_lane_zone_starts_at_the_stop_line_and_a_waiting_car_is_inside():
    g = scene_geometry(default_layout())
    view = top_down(90, 110, 300, geometry=g)
    zones = {z.id: z for z in view.zones()}
    inbound = {"north": (-2, -22.5), "south": (2, 22.5), "east": (22.5, -2), "west": (-22.5, 2)}
    box = {"north": (-2, -10), "south": (2, 10), "east": (10, -2), "west": (-10, 2)}
    for arm, (x, z) in inbound.items():
        assert zones[f"{arm}-in"].contains(*view.to_norm(x, z))
        assert not zones[f"{arm}-in"].contains(*view.to_norm(*box[arm]))


def test_every_lane_of_a_wide_road_gets_its_own_zone():
    l = presets()["Boulevard"]
    zones = {z.id for z in top_down(120, 120, 300, geometry=scene_geometry(l)).zones()}
    assert {"east-in", "east-in-1", "east-in-2", "west-in-2", "north-in-1"} <= zones
    assert not {"north-in-2"} & zones


def test_a_pedestrian_on_a_crosswalk_is_inside_its_zone_on_every_layout():
    for name in ("Crossroads", "Avenue with U-turn", "Grand junction"):
        e = make_engine("pedestrian_rush") if name == "Crossroads" else None
        l = presets()[name]
        g = scene_geometry(l)
        view = top_down(150, 120, 400, geometry=g)
        zones = {z.id: z for z in view.zones()}
        for cg in g["crossings"]:
            for direction in (1, -1):
                for offset in (-1.2, 0.3, 1.2):
                    for pos in (-2.5, 0.0, cg["width"] / 2, cg["width"]):
                        from smart_intersection.geometry import pedestrian_xz
                        x, z = pedestrian_xz(cg, pos, direction, offset)
                        assert zones[cg["id"]].contains(*view.to_norm(x, z)), (name, cg["id"], direction, offset, pos)


# ------------------------------------------------------------------------------------------ picture

def test_render_has_requested_size_and_paints_vehicles():
    data = XmlParser.parse(sim_xml(80), validate=False)
    view = SimView(640, 480, CameraPose(x=-24, z=-24, height_m=14, fov_deg=100, range_m=200))
    img = view.render(data)
    assert img.size == (640, 480)
    colours = {c for _, c in img.getcolors(maxcolors=1_000_000)}
    assert (59, 130, 246) in colours or any(c[2] > 200 > c[0] for c in colours)   # a blue car (shaded) is in the picture


def _pixel(view, img, x, z):
    p = view.cam.project(x, 0.0, z)
    return img.getpixel((int(p[0]), int(p[1])))


def test_the_picture_shows_the_road_of_the_layout_only():
    full = default_layout()
    cut = default_layout()
    cut.arms["east"].enabled = False
    v_full = top_down(80, 100, 300, geometry=scene_geometry(full))
    v_cut = top_down(80, 100, 300, geometry=scene_geometry(cut))
    assert _pixel(v_full, v_full.render(empty_state()), 40, 2) != GRASS            # east road exists
    assert _pixel(v_cut, v_cut.render(empty_state()), 40, 2) == GRASS              # removed in the layout -> grass


def test_lane_dividers_and_arms_of_a_wide_road_are_drawn():
    l = presets()["Boulevard"]
    view = top_down(120, 110, 300, geometry=scene_geometry(l))
    img = view.render(empty_state())
    road = _pixel(view, img, 60, 2.0)                       # a lane centre
    assert road != GRASS and road[0] < 120
    wide = _pixel(view, img, 60, 11.0)                      # 3rd lane of the east arm (asphalt), grass on a 1-lane road
    assert wide != GRASS
    plain = top_down(120, 110, 300, geometry=scene_geometry(default_layout()))
    assert _pixel(plain, plain.render(empty_state()), 60, 11.0) == GRASS


def test_the_roundabout_island_is_drawn():
    view = top_down(80, 100, 300, geometry=scene_geometry(presets()["Roundabout"]))
    img = view.render(empty_state())
    assert _pixel(view, img, 0, 0) == (86, 140, 80)


def test_stop_lines_are_on_the_inbound_lane_of_every_arm():
    view = top_down(90, 110, 300, geometry=scene_geometry(default_layout()))
    img = view.render(empty_state())
    line = (235, 235, 235)
    inbound = {"north": (-2, -21), "south": (2, 21), "east": (21, -2), "west": (-21, 2)}
    outbound = {"north": (2, -21), "south": (-2, 21), "east": (21, 2), "west": (-21, -2)}
    for arm in inbound:
        assert _pixel(view, img, *inbound[arm]) == line, arm
        assert _pixel(view, img, *outbound[arm]) != line, arm


def test_pose_text_and_traffic_light_bulbs_are_drawn():
    view = SimView(640, 480, CameraPose(x=-24, z=-24, height_m=14, fov_deg=90))
    tl = SimpleNamespace(id="TL-N", direction="north", state="GREEN", phase_index=0, phase_switches=0)
    img = view.render(empty_state([tl]))
    assert (40, 255, 90) in {c for _, c in img.getcolors(maxcolors=1_000_000)}
