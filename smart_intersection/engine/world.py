"""
Intersection world built from a layout (lanes, lights, crossings). The numbers below describe the default
crossroads (one lane each way, 32 m box); wider layouts scale the box, see layout.box_half().

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


def build_world(layout=None):
    """Build lanes / lights / crossings for the arms enabled in `layout` (default: full 4-way crossroads)."""
    if layout is None:
        from ..layout import default_layout
        layout = default_layout()
    return _build_lanes(layout), _build_lights(layout), _build_crossings(layout)


def _build_lanes(layout):
    """
    Inbound lane `{arm}-in` (lane 0), `{arm}-in-1` ... and outbound `{arm}-out`, `{arm}-out-1` ... for every enabled arm.
    An inbound lane is the shared approach of all movements that start on it; the routes themselves are
    geometry.build_paths(layout). Lane.length_m is the longest route on the lane.
    """
    from ..geometry import build_paths, lane_id
    from ..layout import stop_dist
    paths = build_paths(layout)
    longest = {}
    for p in paths.values():
        longest[p.lane_id] = max(longest.get(p.lane_id, 0.0), p.length)
    lanes = {}
    for direction in ("north", "south", "east", "west"):
        arm = layout.arms[direction]
        if not arm.enabled:
            continue
        light = f"TL-{direction[0].upper()}"
        for i in range(arm.lanes_in):
            lid = lane_id(direction, i)
            lanes[lid] = Lane(
                id=lid, direction=direction, is_inbound=True, length_m=longest[lid],
                stop_line_m=ARM_LENGTH - stop_dist(layout), traffic_light_id=light,
                spawn_pos=ARM_LENGTH - arm.length_m, speed_limit=arm.speed_limit_mps, index=i,
            )
        for j in range(arm.lanes_out):
            lid = lane_id(direction, j, inbound=False)
            lanes[lid] = Lane(id=lid, direction=direction, is_inbound=False, length_m=ARM_LENGTH, index=j)
    return lanes


def _build_lights(layout):
    """One light per enabled arm, roundabout entries included: a stage machine meters every junction type the same way."""
    lights = {}
    from ..layout import stages
    first = set(stages(layout)[0]) if layout.enabled_arms() else set()
    for direction in ("north", "south", "east", "west"):
        if not layout.arms[direction].enabled:
            continue
        lid = f"TL-{direction[0].upper()}"
        lights[lid] = SimTrafficLight(
            id=lid, direction=direction, state="GREEN" if direction in first else "RED",
            phase_index=0, phase_start_time=0.0, phase_duration=30.0, phase_switches=0,
            lane_ids=[l for l in _lane_ids(layout, direction)],
        )
    return lights


def _lane_ids(layout, direction):
    from ..geometry import lane_id
    return [lane_id(direction, i) for i in range(layout.arms[direction].lanes_in)]


def _build_crossings(layout):
    """One pedestrian crossing per enabled arm that has one."""
    from ..geometry import crossing_geometry
    crossings = {}
    for direction in ("north", "south", "east", "west"):
        cg = crossing_geometry(layout, direction)
        if cg:
            cid = f"PC-{direction[0].upper()}"
            crossings[cid] = PedestrianCrossing(id=cid, direction=direction,
                                                traffic_light_id=f"TL-{direction[0].upper()}", geo=cg)
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
