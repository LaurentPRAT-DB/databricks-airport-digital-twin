"""Event recorder and output writer for simulation runs."""

import json
from datetime import datetime, timedelta
from typing import Any


class SimulationRecorder:
    """Collects simulation events and writes structured output."""

    def __init__(self) -> None:
        self.position_snapshots: list[dict[str, Any]] = []
        self.phase_transitions: list[dict[str, Any]] = []
        self.gate_events: list[dict[str, Any]] = []
        self.baggage_events: list[dict[str, Any]] = []
        self.weather_snapshots: list[dict[str, Any]] = []
        self.scenario_events: list[dict[str, Any]] = []
        self.schedule: list[dict[str, Any]] = []
        self.scenario_name: str | None = None

    def record_position(
        self,
        sim_time: datetime,
        icao24: str,
        callsign: str,
        latitude: float,
        longitude: float,
        altitude: float,
        velocity: float,
        heading: float,
        phase: str,
        on_ground: bool,
        aircraft_type: str,
        assigned_gate: str | None = None,
    ) -> None:
        self.position_snapshots.append({
            "time": sim_time.isoformat(),
            "icao24": icao24,
            "callsign": callsign,
            "latitude": latitude,
            "longitude": longitude,
            "altitude": altitude,
            "velocity": velocity,
            "heading": heading,
            "phase": phase,
            "on_ground": on_ground,
            "aircraft_type": aircraft_type,
            "assigned_gate": assigned_gate,
        })

    def record_phase_transition(
        self,
        sim_time: datetime,
        icao24: str,
        callsign: str,
        from_phase: str,
        to_phase: str,
        latitude: float,
        longitude: float,
        altitude: float,
        aircraft_type: str,
        assigned_gate: str | None = None,
    ) -> None:
        self.phase_transitions.append({
            "time": sim_time.isoformat(),
            "icao24": icao24,
            "callsign": callsign,
            "from_phase": from_phase,
            "to_phase": to_phase,
            "latitude": latitude,
            "longitude": longitude,
            "altitude": altitude,
            "aircraft_type": aircraft_type,
            "assigned_gate": assigned_gate,
        })

    def record_gate_event(
        self,
        sim_time: datetime,
        icao24: str,
        callsign: str,
        gate: str,
        event_type: str,
        aircraft_type: str,
    ) -> None:
        self.gate_events.append({
            "time": sim_time.isoformat(),
            "icao24": icao24,
            "callsign": callsign,
            "gate": gate,
            "event_type": event_type,
            "aircraft_type": aircraft_type,
        })

    def record_weather(self, sim_time: datetime, weather: dict[str, Any]) -> None:
        self.weather_snapshots.append({
            "time": sim_time.isoformat(),
            **weather,
        })

    def record_baggage(
        self, sim_time: datetime, flight_number: str, bags: list[dict[str, Any]]
    ) -> None:
        self.baggage_events.append({
            "time": sim_time.isoformat(),
            "flight_number": flight_number,
            "bag_count": len(bags),
            "bags": bags,
        })

    def record_scenario_event(
        self,
        sim_time: datetime,
        event_type: str,
        description: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.scenario_events.append({
            "time": sim_time.isoformat(),
            "event_type": event_type,
            "description": description,
            **(details or {}),
        })

    def compute_summary(self, config_dict: dict[str, Any]) -> dict[str, Any]:
        """Compute summary metrics from recorded events."""
        total_flights = len(self.schedule)
        arrivals = sum(1 for f in self.schedule if f.get("flight_type") == "arrival")
        departures = sum(1 for f in self.schedule if f.get("flight_type") == "departure")

        # Schedule-based average delay (backward compat)
        delays = [f["delay_minutes"] for f in self.schedule if f.get("delay_minutes", 0) > 0]
        avg_delay = sum(delays) / len(delays) if delays else 0.0

        # Scenario-caused delay: actual spawn time vs effective scheduled time
        capacity_delays: list[float] = []
        for f in self.schedule:
            if f.get("actual_spawn_time") and f.get("scheduled_time"):
                scheduled = datetime.fromisoformat(f["scheduled_time"])
                effective = scheduled + timedelta(minutes=f.get("delay_minutes", 0))
                actual = datetime.fromisoformat(f["actual_spawn_time"])
                hold_min = max(0, (actual - effective).total_seconds() / 60.0)
                capacity_delays.append(hold_min)

        avg_capacity_hold = sum(capacity_delays) / len(capacity_delays) if capacity_delays else 0.0
        max_capacity_hold = max(capacity_delays) if capacity_delays else 0.0

        # On-time % using actual spawn times (includes capacity hold)
        on_time_threshold = 15  # minutes
        on_time = 0
        for f in self.schedule:
            if f.get("actual_spawn_time"):
                scheduled = datetime.fromisoformat(f["scheduled_time"])
                effective = scheduled + timedelta(minutes=f.get("delay_minutes", 0))
                actual = datetime.fromisoformat(f["actual_spawn_time"])
                if (actual - effective).total_seconds() / 60.0 <= on_time_threshold:
                    on_time += 1
            # Non-spawned flights count as NOT on-time (don't increment)
        on_time_pct = (on_time / total_flights * 100) if total_flights > 0 else 0.0

        # Cancellation metrics
        spawned_count = sum(1 for f in self.schedule if f.get("spawned", True))
        not_spawned = total_flights - spawned_count
        cancellation_rate = (not_spawned / total_flights * 100) if total_flights > 0 else 0.0

        # Effective delay for non-spawned flights (how late they'd be at sim end)
        effective_delays: list[float] = []
        for f in self.schedule:
            if not f.get("spawned", True) and f.get("scheduled_time"):
                scheduled = datetime.fromisoformat(f["scheduled_time"])
                effective = scheduled + timedelta(minutes=f.get("delay_minutes", 0))
                if self.position_snapshots:
                    last_time = datetime.fromisoformat(self.position_snapshots[-1]["time"])
                else:
                    last_time = effective
                delay_min = max(0, (last_time - effective).total_seconds() / 60.0)
                effective_delays.append(delay_min)

        # Gate utilization: unique gates used / total gates available
        gates_used = {e["gate"] for e in self.gate_events if e["event_type"] == "occupy"}

        # Peak simultaneous flights from position snapshots
        from collections import Counter
        time_counts = Counter(s["time"] for s in self.position_snapshots)
        peak_simultaneous = max(time_counts.values()) if time_counts else 0

        # Average turnaround time from phase transitions
        parked_times: dict[str, str] = {}  # icao24 -> parked_time
        turnarounds: list[float] = []
        for pt in self.phase_transitions:
            if pt["to_phase"] == "parked":
                parked_times[pt["icao24"]] = pt["time"]
            elif pt["from_phase"] == "parked" and pt["icao24"] in parked_times:
                parked_at = datetime.fromisoformat(parked_times[pt["icao24"]])
                left_at = datetime.fromisoformat(pt["time"])
                turnarounds.append((left_at - parked_at).total_seconds() / 60.0)

        avg_turnaround = sum(turnarounds) / len(turnarounds) if turnarounds else 0.0

        # Scenario-specific metrics
        total_go_arounds = sum(
            1 for e in self.scenario_events if "go-around" in e.get("description", "").lower()
        )
        total_holdings = sum(
            1 for e in self.scenario_events if "hold" in e.get("description", "").lower()
        )

        result = {
            "total_flights": total_flights,
            "arrivals": arrivals,
            "departures": departures,
            "schedule_delay_min": round(avg_delay, 1),
            "avg_capacity_hold_min": round(avg_capacity_hold, 1),
            "max_capacity_hold_min": round(max_capacity_hold, 1),
            "gate_utilization_gates_used": len(gates_used),
            "avg_turnaround_min": round(avg_turnaround, 1),
            "on_time_pct": round(on_time_pct, 1),
            "spawned_count": spawned_count,
            "not_spawned_count": not_spawned,
            "cancellation_rate_pct": round(cancellation_rate, 1),
            "avg_effective_delay_not_spawned_min": round(
                sum(effective_delays) / len(effective_delays) if effective_delays else 0, 1
            ),
            "peak_simultaneous_flights": peak_simultaneous,
            "total_position_snapshots": len(self.position_snapshots),
            "total_phase_transitions": len(self.phase_transitions),
            "total_gate_events": len(self.gate_events),
            "total_baggage_events": len(self.baggage_events),
            "total_weather_snapshots": len(self.weather_snapshots),
            "total_scenario_events": len(self.scenario_events),
            "total_go_arounds": total_go_arounds,
            "total_holdings": total_holdings,
            "scenario_name": self.scenario_name,
        }
        return result

    def write_output(self, path: str, config_dict: dict[str, Any]) -> None:
        """Write all recorded events to a JSON file."""
        summary = self.compute_summary(config_dict)
        output = {
            "config": config_dict,
            "summary": summary,
            "schedule": self.schedule,
            "position_snapshots": self.position_snapshots,
            "phase_transitions": self.phase_transitions,
            "gate_events": self.gate_events,
            "baggage_events": self.baggage_events,
            "weather_snapshots": self.weather_snapshots,
            "scenario_events": self.scenario_events,
        }
        with open(path, "w") as f:
            json.dump(output, f, indent=2, default=str)
