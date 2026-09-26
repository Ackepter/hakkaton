"""
Metrics engine — computes intersection KPIs from simulation state.
"""
from collections import deque
from typing import Dict, List


class MetricsEngine:
    def __init__(self, history_len: int = 300):
        self._history = deque(maxlen=history_len)
        self._passed_total = 0
        self._peds_crossed_total = 0
        self._phase_switches_total = 0
        self._session_start_time = 0.0

    def reset(self):
        self._history.clear()
        self._passed_total = 0
        self._peds_crossed_total = 0
        self._phase_switches_total = 0

    def update(
        self,
        sim_time: float,
        vehicles: list,
        pedestrians: list,
        lights: list,
        lanes: dict,
        newly_passed: int,
        newly_crossed: int,
    ) -> dict:
        self._passed_total += newly_passed
        self._peds_crossed_total += newly_crossed

        lane_queues = {}
        lane_waits = {}
        for lane_id, lane in lanes.items():
            if not lane.is_inbound:
                continue
            lane_vehicles = [v for v in vehicles if v.lane_id == lane_id]
            waiting = [v for v in lane_vehicles if v.state in ("waiting", "decelerating")]
            lane_queues[lane_id] = len(waiting)
            waits = [v.wait_time for v in waiting]
            lane_waits[lane_id] = sum(waits) / len(waits) if waits else 0.0

        total_waiting = sum(lane_queues.values())
        all_waits = [v.wait_time for v in vehicles if v.state == "waiting"]
        avg_wait = sum(all_waits) / len(all_waits) if all_waits else 0.0
        max_wait = max(all_waits) if all_waits else 0.0

        # Throughput: vehicles passed in last 60 sim-seconds
        recent = [s for s in self._history if sim_time - s["sim_time"] <= 60.0]
        recent_passed = sum(s.get("newly_passed", 0) for s in recent) + newly_passed
        throughput_per_min = recent_passed  # approximation over last minute

        # Pedestrian wait time
        ped_waits = [p.wait_time for p in pedestrians if p.state == "waiting_for_green"]
        avg_ped_wait = sum(ped_waits) / len(ped_waits) if ped_waits else 0.0

        # Phase switches
        phase_switches = sum(l.phase_switches for l in lights)

        # Congestion index (0-100)
        max_queue = max(lane_queues.values()) if lane_queues else 0
        congestion = min(100.0, (max_queue / 10.0) * 100.0)

        # Efficiency (0-100): inversely proportional to average wait
        efficiency = max(0.0, 100.0 - min(100.0, avg_wait * 2.0))

        snapshot = {
            "sim_time": sim_time,
            "newly_passed": newly_passed,
            "vehicles_active": len(vehicles),
            "vehicles_waiting": total_waiting,
            "pedestrians_waiting": len([p for p in pedestrians if p.state == "waiting_for_green"]),
            "pedestrians_crossing": len([p for p in pedestrians if p.state == "crossing"]),
            "avg_wait_s": round(avg_wait, 2),
            "max_wait_s": round(max_wait, 2),
            "avg_ped_wait_s": round(avg_ped_wait, 2),
            "throughput_per_min": throughput_per_min,
            "passed_total": self._passed_total,
            "peds_crossed_total": self._peds_crossed_total,
            "lane_queues": lane_queues,
            "congestion_pct": round(congestion, 1),
            "efficiency_pct": round(efficiency, 1),
            "phase_switches": phase_switches,
        }
        self._history.append(snapshot)
        return snapshot

    def get_history(self) -> list:
        return list(self._history)

    def get_summary(self) -> dict:
        if not self._history:
            return {}
        last = self._history[-1]
        throughputs = [s["throughput_per_min"] for s in self._history]
        return {
            **last,
            "avg_throughput_per_min": sum(throughputs) / len(throughputs),
        }
