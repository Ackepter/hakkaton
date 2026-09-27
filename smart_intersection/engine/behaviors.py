"""
Vehicle and Pedestrian FSM behaviors.
Pure logic — no I/O, no asyncio.

Vehicle FSM:  driving -> decelerating -> waiting -> passing -> driving -> finished
Pedestrian FSM: walking_to_crossing -> waiting_for_green -> crossing -> finished

position_m is the vehicle CENTRE along its path; the bumper (front) is position_m + length/2.
Lane.stop_line_m is the coordinate the FRONT bumper must not cross on red.
"""
import math
from typing import List, Optional
from .models import Vehicle, Pedestrian, Lane

SAFE_GAP_S = 1.2         # desired time headway to the leader
MIN_GAP_M = 1.5          # bumper-to-bumper gap kept when stopped
APPROACH_DIST_M = 45.0   # start reacting to a non-green light this far from the stop line
STOP_TOLERANCE_M = 0.3
BRAKE_FACTOR = 0.8       # planned braking as a fraction of max decel (leaves a safety margin)
CAN_STOP_FACTOR = 0.95   # vehicle may still stop if required decel <= this * max decel
PASSING_ZONE_M = 42.0    # length of the box + crosswalks after the stop line, for the "passing" label
YIELD_HOLD_M = MIN_GAP_M + 1.0     # a stopped vehicle this close to an obstacle counts as waiting (yield_rule)
YIELD_RELEASE_M = MIN_GAP_M + 2.5  # ... and starts again once the obstacle is this far


def update_vehicle(
    vehicle: Vehicle,
    dt: float,
    lane: Lane,
    light_state: str,
    vehicles_ahead: List[Vehicle],
    path=None,
    extra_gap: Optional[float] = None,
    yield_rule: bool = False,
) -> Optional[str]:
    """
    Advance one vehicle by dt. Returns 'finished' when it has left the map.

    path       the route (geometry.Path): bends limit the speed, its length ends the trip
    extra_gap  distance to something that is not a leader in the lane but blocks the way (reserved conflict cells, a
               vehicle about to merge, pedestrians on the exit crosswalk); treated like a stopped leader
    yield_rule mark vehicles held by such obstacles as waiting (accumulate wait time) instead of leaving them 'driving'
    """
    if vehicle.state == "finished":
        return "finished"

    half = vehicle.length_m / 2
    inbound = lane.is_inbound
    dist = lane.stop_line_m - (vehicle.position_m + half) if inbound else float("inf")
    before_line = inbound and dist > -0.5
    stop_light = light_state in ("RED", "YELLOW")
    lead_gap = _lead_gap(vehicle, vehicles_ahead)
    if extra_gap is not None:
        lead_gap = extra_gap if lead_gap is None else min(lead_gap, extra_gap)
    approaching_stop = before_line and stop_light and dist < APPROACH_DIST_M
    end = path.length if path is not None else lane.length_m
    passing_zone = path.passing_len if path is not None else PASSING_ZONE_M

    # ---------- held by a merge / crossing / leader (not a red light): wait, then go ----------
    if approaching_stop:
        vehicle.yielding = False                       # the red light takes over
    elif yield_rule:
        if vehicle.yielding:
            if lead_gap is None or lead_gap > YIELD_RELEASE_M:
                vehicle.yielding = False
                vehicle.state = "driving"
            else:
                vehicle.wait_time += dt
                vehicle.speed_mps = 0.0
                return None
        elif vehicle.speed_mps < 0.3 and lead_gap is not None and lead_gap < YIELD_HOLD_M and vehicle.state != "waiting":
            vehicle.yielding = True
            vehicle.state = "waiting"
            vehicle.speed_mps = 0.0
            return None

    # ---------- FSM transitions ----------
    if vehicle.state == "waiting":
        if light_state == "GREEN":
            vehicle.state = "passing"
        else:
            vehicle.wait_time += dt
            vehicle.speed_mps = 0.0
            return None
    elif approaching_stop:
        if vehicle.state in ("driving", "passing"):
            if _can_stop(vehicle, dist):
                vehicle.state = "decelerating"
            # otherwise the driver is committed and keeps going through the yellow
        if (vehicle.state == "decelerating" and vehicle.speed_mps < 0.3
                and (dist <= 0.8 or (lead_gap is not None and lead_gap < MIN_GAP_M + 1.0))):
            vehicle.state = "waiting"
            vehicle.speed_mps = 0.0
            return None
    else:
        if vehicle.state == "decelerating":
            vehicle.state = "driving"

    if inbound:
        if vehicle.state == "driving" and -passing_zone < dist <= 0:
            vehicle.state = "passing"
        elif vehicle.state == "passing" and dist <= -passing_zone:
            vehicle.state = "driving"

    # ---------- speed ----------
    target = vehicle.max_speed
    if lead_gap is not None:
        target = min(target, _follow_speed(vehicle, lead_gap, dt))
    if vehicle.state == "decelerating" and before_line:
        if dist <= STOP_TOLERANCE_M:
            target = 0.0
        else:
            target = min(target, math.sqrt(2 * BRAKE_FACTOR * vehicle.decel * max(dist - 0.2, 0.0)))
    if path is not None and path.speed_cap < target:               # slow down for the bend, before it starts
        to_bend = path.box_entry_s - (vehicle.position_m + half)
        if vehicle.position_m - half < path.box_exit_s:
            cap = path.speed_cap if to_bend <= 0 else math.sqrt(path.speed_cap ** 2 + 2 * BRAKE_FACTOR * vehicle.decel * to_bend)
            target = min(target, cap)
    _apply_acceleration(vehicle, target, dt)

    vehicle.position_m += vehicle.speed_mps * dt

    if vehicle.position_m - half >= end:
        vehicle.state = "finished"
        vehicle.passed_intersection = True
        return "finished"
    return None


def _can_stop(vehicle: Vehicle, dist: float) -> bool:
    """True if the vehicle can still stop before the stop line with comfortable braking."""
    if dist <= STOP_TOLERANCE_M:
        return dist > -0.5
    required = vehicle.speed_mps ** 2 / (2 * dist)
    return required <= vehicle.decel * CAN_STOP_FACTOR


def _follow_speed(vehicle: Vehicle, gap: float, dt: float) -> float:
    """Max speed that keeps a safe distance to the leader (assumes the leader may stop instantly)."""
    usable = gap - MIN_GAP_M - vehicle.speed_mps * dt
    if usable <= 0:
        return 0.0
    v_brake = math.sqrt(2 * 0.7 * vehicle.decel * usable)
    v_time = usable / SAFE_GAP_S
    return min(v_brake, v_time)


def _apply_acceleration(vehicle: Vehicle, target: float, dt: float) -> None:
    diff = target - vehicle.speed_mps
    if diff > 0:
        vehicle.speed_mps += min(vehicle.accel * dt, diff)
    else:
        vehicle.speed_mps += max(-vehicle.decel * dt, diff)
    vehicle.speed_mps = max(0.0, vehicle.speed_mps)


def _lead_gap(vehicle: Vehicle, vehicles_ahead: List[Vehicle]) -> Optional[float]:
    """Bumper-to-bumper distance to the nearest vehicle ahead in the same lane."""
    best = None
    for ahead in vehicles_ahead:
        if ahead.position_m <= vehicle.position_m:
            continue
        gap = (ahead.position_m - ahead.length_m / 2) - (vehicle.position_m + vehicle.length_m / 2)
        if best is None or gap < best:
            best = gap
    return best


def update_pedestrian(ped: Pedestrian, dt: float, ped_light_state: str) -> Optional[str]:
    """Advance one pedestrian. Returns 'finished' when the far side is reached."""
    if ped.state == "finished":
        return "finished"

    if ped.state == "walking_to_crossing":
        ped.position_m = min(ped.stand_position, ped.position_m + ped.speed_mps * dt)
        if ped.position_m >= ped.stand_position:
            ped.state = "waiting_for_green"

    elif ped.state == "waiting_for_green":
        if ped_light_state == "GREEN":
            ped.state = "crossing"
        else:
            ped.wait_time += dt

    elif ped.state == "crossing":
        ped.position_m += ped.speed_mps * dt
        if ped.position_m >= ped.crossing_width:
            ped.state = "finished"
            return "finished"

    return None
