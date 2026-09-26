"""
Metrics engine — computes intersection KPIs from simulation state.
"""
from collections import deque
from typing import List, Optional

HISTORY_INTERVAL_S = 1.0     # one history sample per simulated second
THROUGHPUT_WINDOW_S = 60.0


class MetricsEngine:
    def __init__(self, history_len: int = 300):
        self._history = deque(maxlen=history_len)
        self._events = deque()          # (sim_time, vehicles_passed) inside the throughput window
        self._latest: dict = {}
        self._passed_total = 0
        self._peds_crossed_total = 0
        self._trip_wait_sum = 0.0
        self._last_sample_time = -HISTORY_INTERVAL_S

    def reset(self):
        self._history.clear()
        self._events.clear()
        self._latest = {}
        self._passed_total = 0
        self._peds_crossed_total = 0
        self._trip_wait_sum = 0.0
        self._last_sample_time = -HISTORY_INTERVAL_S

    @staticmethod
    def empty_snapshot() -> dict:
        return {
            "sim_time": 0.0, "newly_passed": 0, "vehicles_active": 0, "vehicles_waiting": 0,
            "pedestrians_waiting": 0, "pedestrians_crossing": 0, "avg_wait_s": 0.0, "max_wait_s": 0.0,
            "avg_ped_wait_s": 0.0, "avg_trip_wait_s": 0.0, "throughput_per_min": 0.0, "passed_total": 0,
            "peds_crossed_total": 0, "lane_queues": {}, "congestion_pct": 0.0, "efficiency_pct": 100.0,
            "phase_switches": 0,
        }

    def update(
        self,
        sim_time: float,
        vehicles: list,
        pedestrians: list,
        lights: list,
        lanes: dict,
        newly_passed: int,
        newly_crossed: int,
        finished_waits: Optional[List[float]] = None,
    ) -> dict:
        self._passed_total += newly_passed
        self._peds_crossed_total += newly_crossed
        self._trip_wait_sum += sum(finished_waits or [])
        if newly_passed:
            self._events.append((sim_time, newly_passed))
        while self._events and sim_time - self._events[0][0] > THROUGHPUT_WINDOW_S:
            self._events.popleft()

        lane_queues = {}
        for lane_id, lane in lanes.items():
            if not lane.is_inbound:
                continue
            lane_queues[lane_id] = sum(
                1 for v in vehicles if v.lane_id == lane_id and v.state in ("waiting", "decelerating")
            )

        waiting = [v for v in vehicles if v.state == "waiting"]
        avg_wait = sum(v.wait_time for v in waiting) / len(waiting) if waiting else 0.0
        max_wait = max((v.wait_time for v in waiting), default=0.0)

        ped_waits = [p.wait_time for p in pedestrians if p.state == "waiting_for_green"]
        avg_ped_wait = sum(ped_waits) / len(ped_waits) if ped_waits else 0.0

        window = min(THROUGHPUT_WINDOW_S, max(sim_time, 10.0))
        throughput = sum(n for _, n in self._events) * 60.0 / window

        max_queue = max(lane_queues.values(), default=0)
        congestion = min(100.0, max_queue / 10.0 * 100.0)
        efficiency = max(0.0, 100.0 - min(100.0, avg_wait * 2.0))

        snapshot = {
            "sim_time": round(sim_time, 2),
            "newly_passed": newly_passed,
            "vehicles_active": len(vehicles),
            "vehicles_waiting": sum(lane_queues.values()),
            "pedestrians_waiting": sum(1 for p in pedestrians if p.state == "waiting_for_green"),
            "pedestrians_crossing": sum(1 for p in pedestrians if p.state == "crossing"),
            "avg_wait_s": round(avg_wait, 2),
            "max_wait_s": round(max_wait, 2),
            "avg_ped_wait_s": round(avg_ped_wait, 2),
            "avg_trip_wait_s": round(self._trip_wait_sum / self._passed_total, 2) if self._passed_total else 0.0,
            "throughput_per_min": round(throughput, 2),
            "passed_total": self._passed_total,
            "peds_crossed_total": self._peds_crossed_total,
            "lane_queues": lane_queues,
            "congestion_pct": round(congestion, 1),
            "efficiency_pct": round(efficiency, 1),
            "phase_switches": sum(l.phase_switches for l in lights),
        }
        self._latest = snapshot
        if sim_time - self._last_sample_time >= HISTORY_INTERVAL_S:
            self._history.append(snapshot)
            self._last_sample_time = sim_time
        return snapshot

    def get_history(self) -> list:
        return list(self._history)

    def get_summary(self) -> dict:
        if not self._latest:
            return {}
        rates = [s["throughput_per_min"] for s in self._history] or [self._latest["throughput_per_min"]]
        return {**self._latest, "avg_throughput_per_min": round(sum(rates) / len(rates), 2)}
