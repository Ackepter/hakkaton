"""
The virtual camera (main project) and the simulation (separate service) must agree on geometry. The two never import
each other at runtime, so this test is the only thing that keeps their constants from drifting apart.
"""
import pytest

from backend.vision import sim_view as sv
from backend.vision.sim_view import SimView, vehicle_world, pedestrian_world
from backend.xml_parser.parser import XmlParser
from smart_intersection.engine import world as W
from smart_intersection.engine.models import VEHICLE_DEFAULTS, Pedestrian
from smart_intersection.tests.helpers import world_xz, make_engine
from smart_intersection.xml_export.exporter import SimStateExporter
from .vision_helpers import sim_xml


def test_constants_match_the_simulation_world():
    assert sv.ARM_LENGTH == W.ARM_LENGTH
    assert sv.HALF == W.INTERSECTION_HALF
    assert sv.LANE_WIDTH == W.LANE_WIDTH
    assert sv.STOP_DIST == W.STOP_LINE_DIST
    assert sv.CROSS_CENTER == W.CROSSWALK_CENTER
    assert sv.CROSS_DEPTH == W.CROSSWALK_DEPTH
    assert sv.CROSS_WIDTH == Pedestrian("p", "PC-N", "crossing", 0, 0).crossing_width


@pytest.mark.parametrize("vtype", sorted(VEHICLE_DEFAULTS))
def test_vehicle_sizes_match_the_simulation(vtype):
    assert sv.VEHICLE_SIZE[vtype][0] == VEHICLE_DEFAULTS[vtype]["length_m"]


@pytest.mark.parametrize("direction", ["north", "south", "east", "west"])
@pytest.mark.parametrize("pos", [0.0, 30.0, 59.0, 80.0, 120.0, 160.0])
def test_vehicle_projection_matches_the_simulation_helpers(direction, pos):
    V = type("V", (), {"position_m": pos, "direction": direction})   # what the simulation test-helper expects
    assert vehicle_world(direction, pos) == pytest.approx(world_xz(V))
    assert vehicle_world(direction, pos)[0] == pytest.approx(W.get_vehicle_3d_position(f"{direction}-in", pos)[0])
    assert vehicle_world(direction, pos)[1] == pytest.approx(W.get_vehicle_3d_position(f"{direction}-in", pos)[2])


def test_pedestrian_lanes_stay_inside_the_crosswalk_zones():
    view = SimView()
    zones = {z.id: z for z in view.default_zones()}
    for cid in ("PC-N", "PC-S", "PC-E", "PC-W"):
        for direction in (1, -1):
            for offset in (-1.2, 0.3, 1.2):
                for pos in (-2.5, 0.0, 6.0, 12.0):
                    x, z = pedestrian_world(cid, pos, direction, offset)
                    assert zones[cid].contains(*view.to_norm(x, z)), (cid, direction, offset, pos)


def test_stop_line_is_where_the_lane_zone_starts():
    zones = {z.id: z for z in SimView().default_zones()}
    view = SimView()
    for arm in ("north", "south", "east", "west"):
        wait_pos = W.ARM_LENGTH - W.STOP_LINE_DIST - 2.25       # centre of a stopped car whose bumper is on the line
        assert zones[f"{arm}-in"].contains(*view.to_norm(*vehicle_world(arm, wait_pos)))
        assert not zones[f"{arm}-in"].contains(*view.to_norm(*vehicle_world(arm, W.ARM_LENGTH - 5)))  # in the box


def test_virtual_detections_match_ground_truth_of_the_running_simulation():
    e = make_engine("heavy")
    e.advance(80)
    data = XmlParser.parse(SimStateExporter.to_xml(e.get_state()), validate=False)
    view = SimView(640, 640)
    dets = view.detections(data)
    vehicles = [d for d in dets if d.cls != "person"]
    truth = {(round(world_xz(v)[0], 2), round(world_xz(v)[1], 2)) for v in e._vehicles.values()
             if abs(world_xz(v)[0]) <= 64 and abs(world_xz(v)[1]) <= 64}
    assert {d.world for d in vehicles} == truth and len(vehicles) > 5
    assert sum(1 for d in dets if d.cls == "person") == sum(
        1 for p in e._pedestrians.values() if p.state != "finished")
    for d in dets:
        assert 0 <= d.x <= 1 and 0 <= d.y <= 1 and 0 < d.w < 1 and 0 < d.h < 1


def test_render_has_requested_size_and_paints_vehicles():
    data = XmlParser.parse(sim_xml(80), validate=False)
    img = SimView(640, 480).render(data)
    assert img.size == (640, 480)
    colours = {c for _, c in img.getcolors(maxcolors=1_000_000)}
    assert (59, 130, 246) in colours                       # a blue car is somewhere in the picture
