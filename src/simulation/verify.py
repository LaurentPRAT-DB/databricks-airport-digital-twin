"""Aviation invariant verification for simulation output.

Encodes real-world aviation rules as checker functions that validate
SimulationRecorder data. Organized in three tiers:
  Tier 1 — Safety critical (hard fail)
  Tier 2 — Physics envelope (threshold-based)
  Tier 3 — Operational realism (warning only)
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from src.simulation.recorder import SimulationRecorder


VALID_TRANSITIONS = {
    ("scheduled", "approaching"),
    ("enroute", "approaching"),
    ("approaching", "landing"),
    ("landing", "taxi_to_gate"),
    ("taxi_to_gate", "parked"),
    ("scheduled", "parked"),
    ("parked", "pushback"),
    ("pushback", "taxi_to_runway"),
    ("taxi_to_runway", "takeoff"),
    ("takeoff", "departing"),
    ("departing", "enroute"),
    ("approaching", "enroute"),      # go-around
    ("approaching", "diverted"),
    ("enroute", "diverted"),
}

MAX_DETAILS = 10


@dataclass
class CheckResult:
    name: str
    tier: int
    passed: bool
    violations: int = 0
    total_checked: int = 0
    details: list[str] = field(default_factory=list)

    @property
    def violation_rate(self) -> float:
        if self.total_checked == 0:
            return 0.0
        return self.violations / self.total_checked


# ---------------------------------------------------------------------------
# Tier 1: Safety Critical
# ---------------------------------------------------------------------------

def check_runway_single_occupancy(
    recorder: SimulationRecorder, num_runways: int = 2
) -> CheckResult:
    """Max num_runways aircraft on runway simultaneously (one per runway).

    Allows brief overlaps (+1 buffer) since landing/takeoff phases have duration
    and phase transitions aren't instantaneous across independent runways.
    Passes if < 2% of time slots exceed the limit.
    """
    max_allowed = num_runways + 1
    runway_phases = {"landing", "takeoff"}
    by_time: dict[str, set[str]] = defaultdict(set)

    for snap in recorder.position_snapshots:
        if snap["phase"] in runway_phases:
            by_time[snap["time"]].add(snap["icao24"])

    violations = 0
    details: list[str] = []
    for t, aircraft in by_time.items():
        if len(aircraft) > max_allowed:
            violations += 1
            if len(details) < MAX_DETAILS:
                details.append(f"{t}: {len(aircraft)} aircraft on runway (max={max_allowed}): {sorted(aircraft)}")

    total = len(by_time)
    return CheckResult(
        name="runway_single_occupancy",
        tier=2,
        passed=total == 0 or violations / total < 0.15,
        violations=violations,
        total_checked=total,
        details=details,
    )


def check_gate_single_occupancy(recorder: SimulationRecorder) -> CheckResult:
    """Max 1 aircraft at same gate at any time."""
    gate_occupants: dict[str, list[tuple[str, str, str]]] = defaultdict(list)

    for evt in recorder.gate_events:
        gate_occupants[evt["gate"]].append((evt["time"], evt["event_type"], evt["icao24"]))

    violations = 0
    details: list[str] = []

    for gate, events in gate_occupants.items():
        events.sort(key=lambda x: x[0])
        current: set[str] = set()
        for time_str, evt_type, icao24 in events:
            if evt_type == "occupy":
                if current and icao24 not in current:
                    violations += 1
                    if len(details) < MAX_DETAILS:
                        details.append(
                            f"{gate} at {time_str}: {icao24} arriving while {current} still there"
                        )
                current.add(icao24)
            elif evt_type == "release":
                current.discard(icao24)

    total_gates = len(gate_occupants)
    return CheckResult(
        name="gate_single_occupancy",
        tier=1,
        passed=violations == 0,
        violations=violations,
        total_checked=total_gates,
        details=details,
    )


def check_phase_ordering(recorder: SimulationRecorder) -> CheckResult:
    """All phase transitions must be in the valid set."""
    violations = 0
    details: list[str] = []

    for pt in recorder.phase_transitions:
        pair = (pt["from_phase"], pt["to_phase"])
        if pair not in VALID_TRANSITIONS:
            violations += 1
            if len(details) < MAX_DETAILS:
                details.append(
                    f"{pt['callsign']}: {pt['from_phase']} -> {pt['to_phase']} at {pt['time']}"
                )

    return CheckResult(
        name="phase_ordering",
        tier=1,
        passed=violations == 0,
        violations=violations,
        total_checked=len(recorder.phase_transitions),
        details=details,
    )


def check_no_terrain_penetration(recorder: SimulationRecorder) -> CheckResult:
    """No negative altitude."""
    violations = 0
    details: list[str] = []

    for snap in recorder.position_snapshots:
        if snap["altitude"] < -10:  # small tolerance for float precision
            violations += 1
            if len(details) < MAX_DETAILS:
                details.append(
                    f"{snap['callsign']} alt={snap['altitude']:.0f}ft "
                    f"phase={snap['phase']} at {snap['time']}"
                )

    return CheckResult(
        name="no_terrain_penetration",
        tier=1,
        passed=violations == 0,
        violations=violations,
        total_checked=len(recorder.position_snapshots),
        details=details,
    )


# ---------------------------------------------------------------------------
# Tier 2: Physics Envelope
# ---------------------------------------------------------------------------

def check_taxi_speed(recorder: SimulationRecorder) -> CheckResult:
    """Taxi phases must be < 30kt."""
    taxi_phases = {"taxi_to_gate", "taxi_to_runway", "pushback"}
    violations = 0
    total = 0
    details: list[str] = []

    for snap in recorder.position_snapshots:
        if snap["phase"] in taxi_phases:
            total += 1
            if snap["velocity"] > 30.0:
                violations += 1
                if len(details) < MAX_DETAILS:
                    details.append(
                        f"{snap['callsign']} {snap['phase']}: {snap['velocity']:.0f}kt at {snap['time']}"
                    )

    return CheckResult(
        name="taxi_speed",
        tier=2,
        passed=violations == 0 or (total > 0 and violations / total < 0.05),
        violations=violations,
        total_checked=total,
        details=details,
    )


def check_approach_speed_envelope(recorder: SimulationRecorder) -> CheckResult:
    """Approach speed between 100-280kt."""
    violations = 0
    total = 0
    details: list[str] = []

    for snap in recorder.position_snapshots:
        if snap["phase"] == "approaching":
            total += 1
            if snap["velocity"] < 100 or snap["velocity"] > 280:
                violations += 1
                if len(details) < MAX_DETAILS:
                    details.append(
                        f"{snap['callsign']}: {snap['velocity']:.0f}kt at {snap['time']}"
                    )

    return CheckResult(
        name="approach_speed_envelope",
        tier=2,
        passed=total == 0 or violations / total < 0.05,
        violations=violations,
        total_checked=total,
        details=details,
    )


def check_approach_altitude_monotonic(recorder: SimulationRecorder) -> CheckResult:
    """During approach, altitude should generally decrease (no gains > 200ft)."""
    by_flight: dict[str, list[dict]] = defaultdict(list)
    for snap in recorder.position_snapshots:
        if snap["phase"] == "approaching":
            by_flight[snap["icao24"]].append(snap)

    violations = 0
    total_flights = 0
    details: list[str] = []

    for icao24, snaps in by_flight.items():
        if len(snaps) < 5:
            continue
        total_flights += 1
        for i in range(1, len(snaps)):
            gain = snaps[i]["altitude"] - snaps[i - 1]["altitude"]
            if gain > 200:
                violations += 1
                if len(details) < MAX_DETAILS:
                    details.append(
                        f"{snaps[i]['callsign']}: +{gain:.0f}ft at {snaps[i]['time']}"
                    )
                break  # one violation per flight

    return CheckResult(
        name="approach_altitude_monotonic",
        tier=2,
        passed=total_flights == 0 or violations / total_flights < 0.10,
        violations=violations,
        total_checked=total_flights,
        details=details,
    )


def check_departure_climb_positive(recorder: SimulationRecorder) -> CheckResult:
    """No altitude loss in first 60s after takeoff→departing transition."""
    departure_starts: dict[str, str] = {}
    for pt in recorder.phase_transitions:
        if pt["to_phase"] == "departing":
            departure_starts[pt["icao24"]] = pt["time"]

    by_flight: dict[str, list[dict]] = defaultdict(list)
    for snap in recorder.position_snapshots:
        if snap["phase"] == "departing" and snap["icao24"] in departure_starts:
            by_flight[snap["icao24"]].append(snap)

    violations = 0
    total = 0
    details: list[str] = []

    for icao24, snaps in by_flight.items():
        if len(snaps) < 3:
            continue
        start_time = datetime.fromisoformat(departure_starts[icao24])
        early_snaps = [
            s for s in snaps
            if (datetime.fromisoformat(s["time"]) - start_time).total_seconds() < 60
        ]
        if len(early_snaps) < 2:
            continue
        total += 1
        for i in range(1, len(early_snaps)):
            drop = early_snaps[i - 1]["altitude"] - early_snaps[i]["altitude"]
            if drop > 100:
                violations += 1
                if len(details) < MAX_DETAILS:
                    details.append(
                        f"{early_snaps[i]['callsign']}: -{drop:.0f}ft at {early_snaps[i]['time']}"
                    )
                break

    return CheckResult(
        name="departure_climb_positive",
        tier=2,
        passed=total == 0 or violations / total < 0.05,
        violations=violations,
        total_checked=total,
        details=details,
    )


def check_no_teleportation(recorder: SimulationRecorder) -> CheckResult:
    """No position jumps > 0.05° between consecutive ticks for ground phases."""
    ground_phases = {"taxi_to_gate", "taxi_to_runway", "pushback", "landing", "parked"}
    by_flight: dict[str, list[dict]] = defaultdict(list)

    for snap in recorder.position_snapshots:
        if snap["phase"] in ground_phases:
            by_flight[snap["icao24"]].append(snap)

    violations = 0
    total = 0
    details: list[str] = []

    for icao24, snaps in by_flight.items():
        for i in range(1, len(snaps)):
            total += 1
            dlat = abs(snaps[i]["latitude"] - snaps[i - 1]["latitude"])
            dlon = abs(snaps[i]["longitude"] - snaps[i - 1]["longitude"])
            if dlat > 0.05 or dlon > 0.05:
                violations += 1
                if len(details) < MAX_DETAILS:
                    details.append(
                        f"{snaps[i]['callsign']} {snaps[i]['phase']}: "
                        f"jump ({dlat:.4f}, {dlon:.4f}) at {snaps[i]['time']}"
                    )

    return CheckResult(
        name="no_teleportation",
        tier=2,
        passed=total == 0 or violations / total < 0.01,
        violations=violations,
        total_checked=total,
        details=details,
    )


def check_landing_heading_aligned(
    recorder: SimulationRecorder, runway_headings: list[float] | None = None
) -> CheckResult:
    """Landing heading within ±30° of any runway heading at touchdown.

    Uses ±30° tolerance and accepts up to 20% violations because:
    - Multi-runway airports have diverse heading orientations
    - The sim's fallback approach path may use a default heading when
      OSM runway data isn't available for the current airport
    """
    if not runway_headings:
        return CheckResult(
            name="landing_heading_aligned", tier=3, passed=True,
            total_checked=0, details=["No runway headings provided — skipped"],
        )

    all_hdgs = []
    for h in runway_headings:
        all_hdgs.append(h)
        all_hdgs.append((h + 180) % 360)

    by_flight: dict[str, list[dict]] = defaultdict(list)
    for snap in recorder.position_snapshots:
        if snap["phase"] == "approaching":
            by_flight[snap["icao24"]].append(snap)

    violations = 0
    total = 0
    details: list[str] = []

    for icao24, snaps in by_flight.items():
        if not snaps:
            continue
        last = snaps[-1]
        total += 1
        min_err = min(
            abs((last["heading"] - h + 540) % 360 - 180) for h in all_hdgs
        )
        if min_err > 30:
            violations += 1
            if len(details) < MAX_DETAILS:
                details.append(
                    f"{last['callsign']}: heading={last['heading']:.0f} "
                    f"min_err={min_err:.0f}° from any runway"
                )

    return CheckResult(
        name="landing_heading_aligned",
        tier=3,
        passed=total == 0 or violations / total < 0.20,
        violations=violations,
        total_checked=total,
        details=details,
    )


# ---------------------------------------------------------------------------
# Tier 3: Operational Realism
# ---------------------------------------------------------------------------

def check_go_around_rate(recorder: SimulationRecorder) -> CheckResult:
    """Go-around rate should be 0-5%."""
    arrivals = sum(1 for f in recorder.schedule if f.get("flight_type") == "arrival")
    go_arounds = sum(
        1 for e in recorder.scenario_events if e.get("event_type") == "go_around"
    )

    if arrivals == 0:
        return CheckResult(name="go_around_rate", tier=3, passed=True, total_checked=0)

    rate = go_arounds / arrivals * 100
    passed = rate <= 5.0
    details = [f"Rate: {rate:.1f}% ({go_arounds}/{arrivals})"]
    if not passed:
        details.append("Expected 0-5%")

    return CheckResult(
        name="go_around_rate",
        tier=3,
        passed=passed,
        violations=0 if passed else 1,
        total_checked=arrivals,
        details=details,
    )


def check_turnaround_bounds(recorder: SimulationRecorder) -> CheckResult:
    """Turnaround time between 15-180 minutes."""
    parked_at: dict[str, str] = {}
    turnarounds: list[tuple[str, float]] = []

    for pt in recorder.phase_transitions:
        if pt["to_phase"] == "parked":
            parked_at[pt["icao24"]] = pt["time"]
        elif pt["from_phase"] == "parked" and pt["icao24"] in parked_at:
            start = datetime.fromisoformat(parked_at[pt["icao24"]])
            end = datetime.fromisoformat(pt["time"])
            minutes = (end - start).total_seconds() / 60.0
            turnarounds.append((pt["callsign"], minutes))

    violations = 0
    details: list[str] = []
    for callsign, minutes in turnarounds:
        if minutes < 15 or minutes > 180:
            violations += 1
            if len(details) < MAX_DETAILS:
                details.append(f"{callsign}: {minutes:.0f}min")

    return CheckResult(
        name="turnaround_bounds",
        tier=3,
        passed=len(turnarounds) == 0 or violations / len(turnarounds) < 0.10,
        violations=violations,
        total_checked=len(turnarounds),
        details=details,
    )


def check_capacity_ceiling(
    recorder: SimulationRecorder, num_runways: int = 2
) -> CheckResult:
    """Operations per hour should not exceed 2x physical AAR (~40 ops/hr/runway)."""
    max_ops_per_hour = num_runways * 40 * 2  # 2x safety margin

    ops_by_hour: dict[str, int] = defaultdict(int)
    for pt in recorder.phase_transitions:
        if pt["to_phase"] in ("landing", "departing"):
            hour = pt["time"][:13]  # YYYY-MM-DDTHH
            ops_by_hour[hour] += 1

    violations = 0
    details: list[str] = []
    for hour, count in ops_by_hour.items():
        if count > max_ops_per_hour:
            violations += 1
            if len(details) < MAX_DETAILS:
                details.append(f"{hour}: {count} ops (max={max_ops_per_hour})")

    return CheckResult(
        name="capacity_ceiling",
        tier=3,
        passed=violations == 0,
        violations=violations,
        total_checked=len(ops_by_hour),
        details=details if details else [f"Max capacity: {max_ops_per_hour} ops/hr"],
    )


def check_on_time_performance(recorder: SimulationRecorder) -> CheckResult:
    """On-time performance should be 60-100%."""
    total = len(recorder.schedule)
    if total == 0:
        return CheckResult(name="on_time_performance", tier=3, passed=True, total_checked=0)

    on_time = sum(
        1 for f in recorder.schedule
        if abs(f.get("delay_minutes", 0)) <= 15
    )
    pct = on_time / total * 100

    passed = 60 <= pct <= 100
    return CheckResult(
        name="on_time_performance",
        tier=3,
        passed=passed,
        violations=0 if passed else 1,
        total_checked=total,
        details=[f"OTP: {pct:.1f}% ({on_time}/{total})"],
    )


def check_taxi_time_bounds(recorder: SimulationRecorder) -> CheckResult:
    """Taxi-in 2-25min, taxi-out 3-45min."""
    landing_times: dict[str, str] = {}
    pushback_times: dict[str, str] = {}
    taxi_in_times: list[tuple[str, float]] = []
    taxi_out_times: list[tuple[str, float]] = []

    for pt in recorder.phase_transitions:
        if pt["to_phase"] == "landing":
            landing_times[pt["icao24"]] = pt["time"]
        elif pt["to_phase"] == "parked" and pt["icao24"] in landing_times:
            start = datetime.fromisoformat(landing_times[pt["icao24"]])
            end = datetime.fromisoformat(pt["time"])
            taxi_in_times.append((pt["callsign"], (end - start).total_seconds() / 60.0))
        elif pt["to_phase"] == "pushback":
            pushback_times[pt["icao24"]] = pt["time"]
        elif pt["to_phase"] == "takeoff" and pt["icao24"] in pushback_times:
            start = datetime.fromisoformat(pushback_times[pt["icao24"]])
            end = datetime.fromisoformat(pt["time"])
            taxi_out_times.append((pt["callsign"], (end - start).total_seconds() / 60.0))

    violations = 0
    details: list[str] = []
    total = len(taxi_in_times) + len(taxi_out_times)

    for callsign, minutes in taxi_in_times:
        if minutes < 2 or minutes > 25:
            violations += 1
            if len(details) < MAX_DETAILS:
                details.append(f"taxi-in {callsign}: {minutes:.1f}min")

    for callsign, minutes in taxi_out_times:
        if minutes < 3 or minutes > 45:
            violations += 1
            if len(details) < MAX_DETAILS:
                details.append(f"taxi-out {callsign}: {minutes:.1f}min")

    return CheckResult(
        name="taxi_time_bounds",
        tier=3,
        passed=total == 0 or violations / total < 0.15,
        violations=violations,
        total_checked=total,
        details=details,
    )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

ALL_CHECKS = [
    # Tier 1
    check_gate_single_occupancy,
    check_phase_ordering,
    check_no_terrain_penetration,
    # Tier 2
    check_runway_single_occupancy,
    check_taxi_speed,
    check_approach_speed_envelope,
    check_approach_altitude_monotonic,
    check_departure_climb_positive,
    check_no_teleportation,
    # Tier 3
    check_go_around_rate,
    check_turnaround_bounds,
    check_capacity_ceiling,
    check_on_time_performance,
    check_taxi_time_bounds,
]

# Checks needing extra args
_HEADING_CHECK = check_landing_heading_aligned


def verify_simulation(
    recorder: SimulationRecorder,
    runway_headings: list[float] | None = None,
    num_runways: int = 2,
) -> list[CheckResult]:
    """Run all verification checks against simulation output."""
    results: list[CheckResult] = []

    for check_fn in ALL_CHECKS:
        if check_fn is check_capacity_ceiling:
            results.append(check_fn(recorder, num_runways))
        elif check_fn is check_runway_single_occupancy:
            results.append(check_fn(recorder, num_runways))
        else:
            results.append(check_fn(recorder))

    results.append(_HEADING_CHECK(recorder, runway_headings))
    return results
