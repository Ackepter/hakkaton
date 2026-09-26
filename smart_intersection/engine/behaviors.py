"""
Vehicle and Pedestrian FSM behaviors.
Pure logic — no I/O, no asyncio.
"""
import logging
from typing import List, Optional
from .models import Vehicle, Pedestrian, SimTrafficLight, Lane

logger = logging.getLogger(__name__)

SAFE_GAP_S = 2.0        # seconds of headway
MIN_GAP_M = 1.0         # minimum gap (meters) regardless of speed
APPROACH_DIST_M = 35.0  # meters before stop line to start checking light


def update_vehicle(
    vehicle: Vehicle,
    dt: float,
    lane: Lane,
    light_state: str,
    vehicles_ahead: List[Vehicle],
) -> Optional[str]:
    """
    Update vehicle position and state for one tick.
    Returns 'finished' if vehicle should be removed, else None.
    """
    if vehicle.state == "finished":
        return "finished"

    # Determine if we are near the stop line
    stop_line = lane.stop_line_m if lane.is_inbound else float("inf")
    dist_to_stop = stop_line - vehicle.position_m
    in_approach = lane.is_inbound and 0 < dist_to_stop < APPROACH_DIST_M

    # Lead vehicle constraint
    lead_gap = _lead_gap(vehicle, vehicles_ahead)

    # ---------- FSM transitions ----------

    if vehicle.state == "driving":
        if in_approach and light_state in ("RED", "YELLOW"):
            vehicle.state = "decelerating"
        elif not lane.is_inbound and vehicle.position_m >= lane.length_m:
            vehicle.state = "finished"
            vehicle.passed_intersection = True

    elif vehicle.state == "decelerating":
        if not in_approach or light_state == "GREEN":
            vehicle.state = "driving"
        elif dist_to_stop <= 0.5 and vehicle.speed_mps < 0.5:
            vehicle.speed_mps = 0.0
            vehicle.state = "waiting"
            return None

    elif vehicle.state == "waiting":
        if light_state == "GREEN":
            vehicle.state = "passing"
        else:
            vehicle.wait_time += dt
            return None

    elif vehicle.state == "passing":
        if vehicle.position_m >= lane.length_m * 0.6:
            # Through the intersection, transition to outbound
            vehicle.state = "finished"
            vehicle.passed_intersection = True

    # ---------- Speed update ----------

    target_speed = _target_speed(vehicle, dist_to_stop, light_state, lead_gap, in_approach)
    _apply_acceleration(vehicle, target_speed, dt)

    # ---------- Position update ----------
    vehicle.position_m += vehicle.speed_mps * dt

    # Remove if past end
    if vehicle.position_m >= lane.length_m + 10.0:
        vehicle.state = "finished"
        return "finished"

    return None


def _target_speed(vehicle: Vehicle, dist_to_stop: float, light_state: str, lead_gap: float, in_approach: bool) -> float:
    """Calculate target speed given constraints."""
    target = vehicle.max_speed

    # Lead vehicle constraint
    if lead_gap is not None:
        safe_dist = SAFE_GAP_S * vehicle.speed_mps + MIN_GAP_M + vehicle.length_m / 2
        if lead_gap < safe_dist:
            ratio = max(0.0, lead_gap / safe_dist)
            target = min(target, vehicle.max_speed * ratio)

    # Stop line constraint
    if in_approach and light_state in ("RED", "YELLOW") and dist_to_stop > 0:
        # Gradual deceleration: v² = 2·a·d → target_speed = sqrt(2·decel·dist)
        stop_speed = (2 * vehicle.decel * dist_to_stop) ** 0.5
        target = min(target, stop_speed)
        if dist_to_stop < 1.0:
            target = 0.0

    return max(0.0, target)


def _apply_acceleration(vehicle: Vehicle, target: float, dt: float) -> None:
    """Smoothly accelerate/decelerate toward target speed."""
    diff = target - vehicle.speed_mps
    if diff > 0:
        vehicle.speed_mps += min(vehicle.accel * dt, diff)
    else:
        vehicle.speed_mps += max(-vehicle.decel * dt, diff)
    vehicle.speed_mps = max(0.0, vehicle.speed_mps)


def _lead_gap(vehicle: Vehicle, vehicles_ahead: List[Vehicle]) -> Optional[float]:
    """Find distance to the nearest vehicle ahead in the same lane."""
    if not vehicles_ahead:
        return None
    # vehicles_ahead sorted by position descending (closest ahead first)
    for ahead in sorted(vehicles_ahead, key=lambda v: v.position_m):
        if ahead.position_m > vehicle.position_m:
            return ahead.position_m - vehicle.position_m - vehicle.length_m
    return None


def update_pedestrian(
    ped: Pedestrian,
    dt: float,
    ped_light_state: str,  # state of the pedestrian signal (same TL as lane)
) -> Optional[str]:
    """
    Update pedestrian state and position.
    Returns 'finished' if should be removed.
    """
    if ped.state == "finished":
        return "finished"

    if ped.state == "walking_to_crossing":
        # Instantly reach the crossing for simplicity
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
