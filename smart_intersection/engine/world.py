"""
Fixed 4-way intersection world layout.

Coordinate system (top view):
  - X axis: West → East
  - Z axis: North → South
  - Y axis: up (3D height)

Intersection center: (0, 0)
Road arms: North, South, East, West
Each arm has 2 inbound lanes + 2 outbound lanes
Lane width: 4m
Road arm length: 80m (total)

         NORTH
    | N-in-1 | N-in-0 | N-out-0 | N-out-1 |
────┼─────────────────────────────────────────────
 W  |         [  INTERSECTION  ]         | E
────┼─────────────────────────────────────────────
    | S-out-1 | S-out-0 | S-in-0 | S-in-1 |
         SOUTH
"""
from .models import Lane, SimTrafficLight, PedestrianCrossing

# Road geometry constants
LANE_WIDTH = 4.0
ARM_LENGTH = 80.0          # meters from intersection edge
INTERSECTION_HALF = 16.0   # half-width of intersection box (4 lanes × 4m)
STOP_LINE_OFFSET = 2.0     # meters before intersection edge
PATH_LENGTH = 2 * ARM_LENGTH      # inbound path runs straight through the box to the far end
CROSSWALK_CENTER = INTERSECTION_HALF + 2.5   # crosswalk band centre, meters from centre
CROSSWALK_DEPTH = 3.0
STOP_LINE_DIST = CROSSWALK_CENTER + CROSSWALK_DEPTH / 2 + 1.0  # front bumper must stop here (meters from centre)


def build_world():
    """Build the fixed 4-way intersection world."""
    lanes = _build_lanes()
    lights = _build_lights()
    crossings = _build_crossings()
    return lanes, lights, crossings


def _build_lanes():
    """
    8 inbound lanes (one per direction, but 2 lanes per arm, so actually 8 total):
    north-in, south-in, east-in, west-in  (approaching)
    north-out, south-out, east-out, west-out  (leaving)

    For simplicity: 1 primary inbound lane per direction (queuing) + outbound
    """
    lanes = {}
    for direction in ("north", "south", "east", "west"):
        # Inbound: vehicles approach intersection
        lane_in = Lane(
            id=f"{direction}-in",
            direction=direction,
            is_inbound=True,
            length_m=PATH_LENGTH,
            stop_line_m=ARM_LENGTH - STOP_LINE_DIST,
            traffic_light_id=f"TL-{direction[0].upper()}",
        )
        # Outbound: vehicles leave intersection
        lane_out = Lane(
            id=f"{direction}-out",
            direction=direction,
            is_inbound=False,
            length_m=ARM_LENGTH,
        )
        lanes[lane_in.id] = lane_in
        lanes[lane_out.id] = lane_out
    return lanes


def _build_lights():
    """
    4 traffic lights. Phase groups:
    Group A (NS): TL-N + TL-S = GREEN, TL-E + TL-W = RED
    Group B (EW): TL-N + TL-S = RED, TL-E + TL-W = GREEN

    Default phases at t=0: Group A active (NS green)
    """
    import time as _time
    t = 0.0  # initial sim time

    lights = {}
    for direction, group, initial_state in [
        ("north", "ns", "GREEN"),
        ("south", "ns", "GREEN"),
        ("east",  "ew", "RED"),
        ("west",  "ew", "RED"),
    ]:
        lid = f"TL-{direction[0].upper()}"
        duration = 30.0 if initial_state == "GREEN" else 30.0
        lane_ids = [f"{direction}-in"]

        light = SimTrafficLight(
            id=lid,
            direction=direction,
            state=initial_state,
            phase_index=0,
            phase_start_time=t,
            phase_duration=duration,
            phase_switches=0,
            lane_ids=lane_ids,
        )
        lights[lid] = light
    return lights


def _build_crossings():
    """4 pedestrian crossings — one per road arm."""
    crossings = {}
    for direction in ("north", "south", "east", "west"):
        cid = f"PC-{direction[0].upper()}"
        crossings[cid] = PedestrianCrossing(
            id=cid,
            direction=direction,
            traffic_light_id=f"TL-{direction[0].upper()}",
        )
    return crossings


# -------- 3D position helpers (used by renderer) --------

def get_vehicle_3d_position(lane_id: str, position_m: float):
    """
    Convert (lane_id, position_m) to world (x, z) coordinates.
    position_m=0 is the spawn point (far end), increasing toward intersection.
    """
    direction = lane_id.split("-")[0]
    is_in = "in" in lane_id

    # Lane center offset from road centerline
    # Inbound: right lane (relative to direction of travel)
    # Outbound: left lane (relative to direction of travel)
    half = LANE_WIDTH / 2 + LANE_WIDTH / 2  # center of inbound lane

    if direction == "north":
        # inbound: travels +Z straight through the box (position_m - ARM_LENGTH is signed distance from centre)
        z = (position_m - ARM_LENGTH) if is_in else -(position_m + INTERSECTION_HALF)
        x = -LANE_WIDTH / 2 if is_in else LANE_WIDTH / 2
        return (x, 0.75, z)

    elif direction == "south":
        z = (ARM_LENGTH - position_m) if is_in else (position_m + INTERSECTION_HALF)
        x = LANE_WIDTH / 2 if is_in else -LANE_WIDTH / 2
        return (x, 0.75, z)

    elif direction == "east":
        x = (ARM_LENGTH - position_m) if is_in else (position_m + INTERSECTION_HALF)
        z = -LANE_WIDTH / 2 if is_in else LANE_WIDTH / 2
        return (x, 0.75, z)

    elif direction == "west":
        x = (position_m - ARM_LENGTH) if is_in else -(position_m + INTERSECTION_HALF)
        z = LANE_WIDTH / 2 if is_in else -LANE_WIDTH / 2
        return (x, 0.75, z)

    return (0, 0.75, 0)


def get_light_3d_position(direction: str):
    """3D position for traffic light pole."""
    offset = INTERSECTION_HALF + 3.0
    positions = {
        "north": (-LANE_WIDTH * 1.5, 0, -offset),
        "south": (LANE_WIDTH * 1.5,  0,  offset),
        "east":  (offset,  0,  LANE_WIDTH * 1.5),
        "west":  (-offset, 0, -LANE_WIDTH * 1.5),
    }
    return positions.get(direction, (0, 0, 0))


def get_crossing_3d_position(direction: str):
    """3D position for pedestrian crossing center."""
    offset = INTERSECTION_HALF + 1.0
    positions = {
        "north": (0, 0, -offset),
        "south": (0, 0,  offset),
        "east":  (offset, 0, 0),
        "west":  (-offset, 0, 0),
    }
    return positions.get(direction, (0, 0, 0))
