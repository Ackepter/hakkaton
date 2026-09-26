"""Traffic analysis: tracker, zones, waiting, flow, pedestrian priority, emergency, adapters."""
import pytest

from backend.metrics.collector import MetricsCollector
from backend.models.schemas import SystemMode
from backend.vision.analysis import (CentroidTracker, TrafficAnalyzer, merge_snapshots, perception_payload,
                                     to_traffic_data)
from backend.vision.config import Zone
from .vision_helpers import det

LANE_N = Zone("north-in", "lane", [(0.4, 0.0), (0.6, 0.0), (0.6, 0.5), (0.4, 0.5)], "north", capacity=4)
LANE_E = Zone("east-in", "lane", [(0.6, 0.5), (1.0, 0.5), (1.0, 0.6), (0.6, 0.6)], "east", capacity=4)
PED_N = Zone("PC-N", "pedestrian", [(0.0, 0.8), (1.0, 0.8), (1.0, 1.0), (0.0, 1.0)], "north", capacity=10)


def analyzer(threshold=3):
    return TrafficAnalyzer([LANE_N, LANE_E, PED_N], ped_priority_threshold=threshold)


# ---------------------------------------------------------------- tracker

def test_tracker_keeps_identity_of_a_moving_object_and_creates_new_ids_for_new_ones():
    tr = CentroidTracker()
    ids = []
    for i in range(5):
        d = [det("car", 0.5, 0.1 + 0.02 * i)]
        tr.update(d, now=i * 0.2)
        ids.append(d[0].track_id)
    assert len(set(ids)) == 1
    other = [det("car", 0.5, 0.22), det("car", 0.9, 0.9)]
    tr.update(other, now=1.2)
    assert other[1].track_id not in ids and other[0].track_id == ids[0]


def test_tracker_never_matches_a_person_to_a_vehicle():
    tr = CentroidTracker()
    a = [det("car", 0.5, 0.5)]
    tr.update(a, 0.0)
    b = [det("person", 0.5, 0.5)]
    tr.update(b, 0.1)
    assert a[0].track_id != b[0].track_id


def test_tracker_forgets_objects_after_max_age():
    tr = CentroidTracker(max_age_s=1.0)
    a = [det("car", 0.5, 0.5)]
    tr.update(a, 0.0)
    tr.update([], 2.0)
    assert tr.track(a[0].track_id) is None


def test_stationary_detection_needs_a_full_window_of_stillness():
    tr = CentroidTracker(still_window_s=1.0)
    still = None
    for i in range(12):
        d = [det("car", 0.5, 0.3)]
        tr.update(d, now=i * 0.2)
        still = tr.track(d[0].track_id).still_since
        if i < 4:
            assert still is None                          # not enough history yet
    assert still is not None
    d = [det("car", 0.5, 0.35)]                            # starts moving
    tr.update(d, now=2.6)
    assert tr.track(d[0].track_id).still_since is None


@pytest.mark.parametrize("step,expected", [((0.0, -0.02), "north"), ((0.0, 0.02), "south"),
                                           ((0.02, 0.0), "east"), ((-0.02, 0.0), "west")])
def test_heading_from_motion(step, expected):
    tr = CentroidTracker()
    x, y = 0.5, 0.5
    d = None
    for i in range(10):
        d = [det("car", x, y)]
        tr.update(d, now=i * 0.2)
        x, y = x + step[0], y + step[1]
    assert tr.heading(tr.track(d[0].track_id), now=1.8) == expected


def test_no_heading_for_a_standing_object():
    tr = CentroidTracker()
    for i in range(12):
        d = [det("car", 0.5, 0.3)]
        tr.update(d, now=i * 0.2)
    assert tr.heading(tr.track(d[0].track_id), now=2.2) is None


# ---------------------------------------------------------------- analyzer

def test_counts_zones_and_classes():
    a = analyzer()
    dets = [det("car", 0.5, 0.2), det("truck", 0.5, 0.35), det("car", 0.8, 0.55), det("person", 0.3, 0.9),
            det("person", 0.7, 0.9), det("car", 0.1, 0.1)]                  # last car is outside every zone
    s = a.analyze("CAM", dets, now=10.0)
    assert (s.vehicles, s.trucks, s.pedestrians) == (4, 1, 2)
    assert s.counts == {"car": 3, "truck": 1, "person": 2}
    assert s.zones["north-in"].count == 2 and s.zones["north-in"].by_class == {"car": 1, "truck": 1}
    assert s.zones["east-in"].count == 1 and s.zones["PC-N"].count == 2
    assert s.direction_counts == {"north": 2, "east": 1}
    assert [d.zone for d in dets] == ["north-in", "north-in", "east-in", "PC-N", "PC-N", None]


def test_pedestrians_are_only_assigned_to_crosswalk_zones_and_cars_only_to_lanes():
    a = analyzer()
    s = a.analyze("CAM", [det("person", 0.5, 0.2), det("car", 0.5, 0.9)], now=1.0)
    assert s.zones["north-in"].count == 0 and s.zones["PC-N"].count == 0


def test_density_is_count_over_capacity_and_capped_at_one():
    a = analyzer()
    s = a.analyze("CAM", [det("car", 0.5, 0.05 + 0.08 * i) for i in range(6)], now=1.0)
    assert s.zones["north-in"].density == 1.0
    s2 = analyzer().analyze("CAM", [det("car", 0.5, 0.2), det("car", 0.5, 0.3)], now=1.0)
    assert s2.zones["north-in"].density == 0.5


def test_waiting_vehicles_and_wait_time_come_from_stationary_tracks():
    a = analyzer()
    s = None
    for i in range(20):
        s = a.analyze("CAM", [det("car", 0.5, 0.3), det("car", 0.5, 0.1 + 0.01 * i)], now=i * 0.25)
    assert s.zones["north-in"].waiting == 1 and s.waiting_vehicles == 1
    assert s.zones["north-in"].max_wait_s > 3.0 and s.avg_wait_s == s.zones["north-in"].avg_wait_s > 0


def test_flow_counts_each_vehicle_once_per_minute_window():
    a = analyzer()
    s = None
    for i in range(40):                                    # 40 s: a new car enters the zone every 4 s
        cars = [det("car", 0.5, 0.05 + 0.09 * ((i * 0.25 + k * 4) % 8) / 2) for k in range(1)]
        s = a.analyze("CAM", [det("car", 0.5, 0.45 - 0.01 * (i % 4))] + cars, now=i * 1.0)
    assert s.zones["north-in"].flow_per_min > 0
    assert s.vehicles_per_hour == pytest.approx(s.flow_per_min * 60, abs=0.2)
    first = analyzer()
    only = first.analyze("CAM", [det("car", 0.5, 0.3)], now=0.0)
    again = first.analyze("CAM", [det("car", 0.5, 0.3)], now=1.0)
    assert again.zones["north-in"].flow_per_min == only.zones["north-in"].flow_per_min   # same car, counted once


def test_pedestrian_priority_uses_a_configurable_threshold():
    def waiting_crowd(n, threshold):
        a = analyzer(threshold)
        s = None
        for i in range(12):
            s = a.analyze("CAM", [det("person", 0.1 + 0.08 * k, 0.9) for k in range(n)], now=i * 0.25)
        return s
    assert waiting_crowd(4, threshold=5).ped_priority is False
    assert waiting_crowd(4, threshold=3).ped_priority is True
    s = waiting_crowd(4, threshold=3)
    assert s.pedestrians_waiting == 4 and s.ped_avg_wait_s > 0


def test_emergency_vehicle_is_reported_per_arm():
    s = analyzer().analyze("CAM", [det("emergency", 0.5, 0.2), det("car", 0.8, 0.55)], now=1.0)
    assert s.emergency == {"north": True}


def test_empty_frame_gives_a_zero_snapshot():
    s = analyzer().analyze("CAM", [], now=5.0)
    assert (s.vehicles, s.pedestrians, s.flow_per_min, s.density, s.ped_priority) == (0, 0, 0.0, 0.0, False)
    assert s.to_dict()["zones"]["north-in"]["count"] == 0


# ---------------------------------------------------------------- adapters

def test_traffic_data_has_the_shape_the_controller_and_metrics_expect():
    s = analyzer().analyze("CAM", [det("car", 0.5, 0.2), det("truck", 0.5, 0.35), det("person", 0.3, 0.9)], now=1.0)
    data = to_traffic_data(s)
    assert data["queues"]["north-in"]["cars"] == 1 and data["queues"]["north-in"]["trucks"] == 1
    assert data["queues"]["PC-N"]["pedestrians"] == 1
    assert data["summary"]["total_cars"] == 1 and data["summary"]["total_pedestrians"] == 1
    mc = MetricsCollector()
    mc.update(data, [], SystemMode.AUTO, phase_switches=0)              # must not raise, values are picked up
    assert mc.get_latest()["traffic"]["total_trucks"] == 1


def test_perception_payload_is_what_the_simulation_needs():
    a = analyzer()
    s = None
    for i in range(12):
        s = a.analyze("CAM", [det("car", 0.5, 0.2), det("emergency", 0.5, 0.3), det("person", 0.5, 0.9)], now=i * 0.25)
    p = perception_payload(s, camera_ok=True)
    assert p["camera_ok"] is True and p["vehicles"] == {"north": 2, "east": 0}
    assert p["pedestrians_waiting"] == {"PC-N": 1} and p["emergency"] == {"north": True}
    assert perception_payload(s, camera_ok=False) == {"camera_ok": False, "vehicles": {}, "pedestrians_waiting": {},
                                                      "ped_priority": {}, "emergency": {}}
    assert perception_payload(None, camera_ok=True)["camera_ok"] is False


def test_merge_snapshots_sums_cameras():
    a1 = TrafficAnalyzer([LANE_N], 3).analyze("A", [det("car", 0.5, 0.2)], now=1.0)
    a2 = TrafficAnalyzer([LANE_E, PED_N], 3).analyze("B", [det("truck", 0.8, 0.55), det("person", 0.5, 0.9)], now=1.0)
    m = merge_snapshots([a1, a2])
    assert m.cameras == ["A", "B"] and (m.vehicles, m.trucks, m.pedestrians) == (2, 1, 1)
    assert set(m.zones) == {"north-in", "east-in", "PC-N"} and m.direction_counts == {"north": 1, "east": 1}
    assert merge_snapshots([a1]) is a1


def test_ped_priority_is_reported_per_crosswalk_and_reaches_the_perception_payload():
    a = analyzer(threshold=3)
    s = None
    for i in range(12):
        s = a.analyze("CAM", [det("person", 0.1 + 0.08 * k, 0.9) for k in range(4)], now=i * 0.25)
    assert s.ped_priority_zones == {"PC-N": True}
    assert perception_payload(s, True)["ped_priority"] == {"PC-N": True}
    assert perception_payload(s, False)["ped_priority"] == {}


# ---------------------------------------------------------------- source identities and clocks

def test_source_ids_keep_tracks_stable_however_far_objects_jump():
    tr = CentroidTracker()
    ids = []
    for i in range(6):
        d = [det("car", 0.1 + 0.15 * i, 0.5)]           # 0.15 per frame: far beyond the matching distance
        d[0].source_id = "sim-car-7"
        tr.update(d, now=float(i))
        ids.append(d[0].track_id)
    assert len(set(ids)) == 1
    other = [det("car", 0.1, 0.5)]
    other[0].source_id = "sim-car-8"
    tr.update(other, now=6.0)
    assert other[0].track_id != ids[0]


def test_source_ids_are_forgotten_with_their_track():
    tr = CentroidTracker(max_age_s=1.0)
    d = [det("car")]
    d[0].source_id = "x"
    tr.update(d, 0.0)
    tr.update([], 5.0)
    assert tr._by_source == {}
    d2 = [det("car")]
    d2[0].source_id = "x"
    tr.update(d2, 6.0)
    assert d2[0].track_id != d[0].track_id


def test_analyzer_restarts_when_the_clock_goes_backwards():
    a = analyzer()
    for i in range(30):
        s = a.analyze("CAM", [det("car", 0.5, 0.3)], now=1000.0 + i)
    assert s.zones["north-in"].waiting == 1
    s = a.analyze("CAM", [det("car", 0.5, 0.3)], now=3.0)                 # simulation was reset
    assert s.zones["north-in"].waiting == 0 and s.zones["north-in"].flow_per_min > 0


def test_flow_of_a_fast_forwarded_simulation_is_not_inflated_by_track_churn():
    """5x speed = one frame per 1 s of simulation time; every car moves ~14 m between frames."""
    from backend.vision.sim_view import SimView
    from backend.xml_parser.parser import XmlParser
    from smart_intersection.engine.simulation import SimulationEngine
    from smart_intersection.xml_export.exporter import SimStateExporter
    e = SimulationEngine(seed=42)
    e.configure(spawn_rate=20.0, ped_spawn_rate=0.0)
    view = SimView()
    an = TrafficAnalyzer(view.default_zones(), 5)
    entered = set()
    snap = None
    for _ in range(90):
        e.advance(1.0)
        data = XmlParser.parse(SimStateExporter.to_xml(e.get_state()), validate=False)
        dets = view.detections(data)
        snap = an.analyze("CAM", dets, now=data.simulation.sim_time)
        entered |= {d.source_id for d in dets if d.zone and d.zone.endswith("-in")}
    assert len(an.tracker._tracks) <= len(entered) + 5
    truth_per_min = len(entered) * 60.0 / 90.0
    assert snap.flow_per_min == pytest.approx(truth_per_min, rel=0.35)         # no 5-10x inflation
