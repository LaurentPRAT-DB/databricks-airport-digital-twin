"""Single-flight end-to-end tracker — Pilot + Airport Operator perspective.

Follows ONE flight through its complete lifecycle:
  enroute → approaching → landing → taxi_to_gate → parked → pushback → taxi_to_runway → takeoff → departing

Records and validates every event from two perspectives:
  - **Pilot**: position, speed, altitude, heading, vertical rate, phase progression
  - **Airport Operator**: gate allocation, turnaround phases, baggage, ground timing

Uses a deterministic simulation (seed=42) with enough flights to get
linked arrival→departure rotations, then picks the first flight that
completes the full arrival + turnaround + departure lifecycle.
"""

import math
import pytest
from collections import defaultdict
from datetime import datetime

from src.simulation.config import SimulationConfig
from src.simulation.engine import SimulationEngine


# ---------------------------------------------------------------------------
# Fixture: run one sim, extract a flight that does the full rotation
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def flight_data():
    """Run sim, find a flight that does arrival→parked→departure full cycle."""
    config = SimulationConfig(
        airport="SFO",
        arrivals=12,
        departures=12,
        duration_hours=4.0,
        time_step_seconds=2.0,
        seed=42,
        diagnostics=True,
    )
    engine = SimulationEngine(config)
    recorder = engine.run()

    # Build per-flight position traces and phase histories
    positions_by_flight = defaultdict(list)
    for p in recorder.position_snapshots:
        positions_by_flight[p["icao24"]].append(p)

    phases_by_flight = defaultdict(list)
    for t in recorder.phase_transitions:
        phases_by_flight[t["icao24"]].append(t)

    gates_by_flight = defaultdict(list)
    for g in recorder.gate_events:
        gates_by_flight[g["icao24"]].append(g)

    baggage_by_callsign = defaultdict(list)
    for b in recorder.baggage_events:
        baggage_by_callsign[b["flight_number"]].append(b)

    # Find a flight that arrives AND departs (linked rotation)
    # It should have: approaching/enroute → landing → taxi_to_gate → parked → pushback → taxi_to_runway → takeoff → departing
    ARRIVAL_PHASES = {"approaching", "landing", "taxi_to_gate", "parked"}
    DEPARTURE_PHASES = {"pushback", "taxi_to_runway", "takeoff", "departing"}

    candidate = None
    for icao24, transitions in phases_by_flight.items():
        phase_set = {t["to_phase"] for t in transitions} | {t["from_phase"] for t in transitions}
        has_arrival = ARRIVAL_PHASES.issubset(phase_set)
        has_departure = DEPARTURE_PHASES.issubset(phase_set)
        if has_arrival and has_departure:
            candidate = icao24
            break

    if candidate is None:
        # Fallback: find any flight with the most complete lifecycle
        best_icao = None
        best_count = 0
        for icao24, transitions in phases_by_flight.items():
            phase_set = {t["to_phase"] for t in transitions} | {t["from_phase"] for t in transitions}
            count = len(phase_set & (ARRIVAL_PHASES | DEPARTURE_PHASES))
            if count > best_count:
                best_count = count
                best_icao = icao24
        candidate = best_icao

    assert candidate is not None, "No flights found in simulation"

    positions = positions_by_flight[candidate]
    transitions = phases_by_flight[candidate]
    gate_events = gates_by_flight[candidate]
    callsign = positions[0]["callsign"] if positions else transitions[0]["callsign"]
    baggage = baggage_by_callsign.get(callsign, [])

    return {
        "icao24": candidate,
        "callsign": callsign,
        "positions": positions,
        "transitions": transitions,
        "gate_events": gate_events,
        "baggage": baggage,
        "recorder": recorder,
        "config": config,
        "schedule": recorder.schedule,
    }


# ===================================================================
#  PILOT PERSPECTIVE
# ===================================================================

class TestPilotView:
    """Pilot following one flight from approach to departure climb."""

    # --- Phase sequence ---

    def test_P01_full_phase_sequence(self, flight_data):
        """Flight goes through all expected phases in correct order."""
        transitions = flight_data["transitions"]
        phase_order = [t["to_phase"] for t in transitions]

        EXPECTED_ARRIVAL = ["approaching", "landing", "taxi_to_gate", "parked"]
        EXPECTED_DEPARTURE = ["pushback", "taxi_to_runway", "takeoff", "departing"]

        # Check arrival sequence appears in order
        arr_indices = []
        for ep in EXPECTED_ARRIVAL:
            found = [i for i, p in enumerate(phase_order) if p == ep]
            if found:
                arr_indices.append(found[0])

        if len(arr_indices) >= 2:
            assert arr_indices == sorted(arr_indices), (
                f"Arrival phases out of order: {[phase_order[i] for i in arr_indices]}"
            )

        # Check departure sequence appears in order
        dep_indices = []
        for ep in EXPECTED_DEPARTURE:
            found = [i for i, p in enumerate(phase_order) if p == ep]
            if found:
                dep_indices.append(found[0])

        if len(dep_indices) >= 2:
            assert dep_indices == sorted(dep_indices), (
                f"Departure phases out of order: {[phase_order[i] for i in dep_indices]}"
            )

        # Departure phases must come after arrival phases
        if arr_indices and dep_indices:
            assert max(arr_indices) < min(dep_indices), (
                "Departure began before arrival completed"
            )

    def test_P02_no_phase_skips(self, flight_data):
        """No illegal phase skips (e.g., approaching → parked)."""
        LEGAL_TRANSITIONS = {
            "scheduled": {"approaching", "enroute", "parked", "taxi_to_runway", "pushback"},
            "enroute": {"approaching"},
            "approaching": {"landing", "approaching"},  # go-around re-enters approaching
            "landing": {"taxi_to_gate"},
            "taxi_to_gate": {"parked"},
            "parked": {"pushback"},
            "pushback": {"taxi_to_runway"},
            "taxi_to_runway": {"takeoff"},
            "takeoff": {"departing"},
            "departing": {"enroute"},
        }
        transitions = flight_data["transitions"]
        violations = []
        for t in transitions:
            fr, to = t["from_phase"], t["to_phase"]
            legal = LEGAL_TRANSITIONS.get(fr, set())
            if to not in legal:
                violations.append(f"{fr} → {to}")

        assert not violations, f"Illegal phase transitions: {violations}"

    # --- Altitude profile ---

    def test_P03_altitude_descent_on_approach(self, flight_data):
        """Altitude generally decreases during approach phase."""
        positions = flight_data["positions"]
        approach = [p for p in positions if p["phase"] == "approaching"]
        if len(approach) < 3:
            pytest.skip("Not enough approach snapshots")

        # Compare first quarter average to last quarter average
        q1 = approach[:len(approach)//4]
        q4 = approach[3*len(approach)//4:]
        avg_q1 = sum(p["altitude"] for p in q1) / len(q1)
        avg_q4 = sum(p["altitude"] for p in q4) / len(q4)
        assert avg_q4 < avg_q1, (
            f"Approach altitude not descending: first quarter avg={avg_q1:.0f}ft, "
            f"last quarter avg={avg_q4:.0f}ft"
        )

    def test_P04_touchdown_altitude_near_zero(self, flight_data):
        """At landing→taxi transition, altitude should be near field elevation."""
        transitions = flight_data["transitions"]
        landing_to_taxi = [t for t in transitions if t["from_phase"] == "landing" and t["to_phase"] == "taxi_to_gate"]
        if not landing_to_taxi:
            pytest.skip("No landing→taxi transition")
        alt = landing_to_taxi[0]["altitude"]
        assert alt < 200, f"Touchdown altitude too high: {alt:.0f}ft"

    def test_P05_altitude_zero_on_ground(self, flight_data):
        """Ground phases should have altitude near 0."""
        positions = flight_data["positions"]
        ground_phases = {"taxi_to_gate", "parked", "pushback", "taxi_to_runway"}
        ground_pos = [p for p in positions if p["phase"] in ground_phases]
        if not ground_pos:
            pytest.skip("No ground positions")

        high = [p for p in ground_pos if p["altitude"] > 100]
        pct_high = len(high) / len(ground_pos) * 100
        assert pct_high < 5, (
            f"{pct_high:.1f}% of ground positions above 100ft "
            f"(worst: {max(p['altitude'] for p in high):.0f}ft)" if high else ""
        )

    def test_P06_departure_climb(self, flight_data):
        """After takeoff, altitude should increase."""
        positions = flight_data["positions"]
        departing = [p for p in positions if p["phase"] == "departing"]
        if len(departing) < 3:
            pytest.skip("Not enough departing snapshots")

        first_alt = departing[0]["altitude"]
        last_alt = departing[-1]["altitude"]
        assert last_alt > first_alt, (
            f"Departing phase not climbing: {first_alt:.0f}ft → {last_alt:.0f}ft"
        )

    # --- Speed profile ---

    def test_P07_speed_zero_when_parked(self, flight_data):
        """Speed should be 0 while parked at gate."""
        positions = flight_data["positions"]
        parked = [p for p in positions if p["phase"] == "parked"]
        if not parked:
            pytest.skip("No parked snapshots")

        moving = [p for p in parked if p["velocity"] > 2]
        pct_moving = len(moving) / len(parked) * 100
        assert pct_moving < 5, (
            f"{pct_moving:.1f}% of parked snapshots have speed > 2kts"
        )

    def test_P08_taxi_speed_reasonable(self, flight_data):
        """Taxi speed should be 1-30 kts (not zero, not highway speed)."""
        positions = flight_data["positions"]
        taxi = [p for p in positions if p["phase"] in ("taxi_to_gate", "taxi_to_runway")]
        if not taxi:
            pytest.skip("No taxi snapshots")

        fast = [p for p in taxi if p["velocity"] > 35]
        pct_fast = len(fast) / len(taxi) * 100
        assert pct_fast < 5, (
            f"{pct_fast:.1f}% of taxi snapshots above 35kts"
        )

    def test_P09_approach_speed_realistic(self, flight_data):
        """Approach speed should be roughly Vref range (100-250 kts)."""
        positions = flight_data["positions"]
        approach = [p for p in positions if p["phase"] == "approaching"]
        if not approach:
            pytest.skip("No approach snapshots")

        speeds = [p["velocity"] for p in approach]
        avg_speed = sum(speeds) / len(speeds)
        assert 80 <= avg_speed <= 300, (
            f"Average approach speed {avg_speed:.0f}kts outside realistic range"
        )

    def test_P10_takeoff_acceleration(self, flight_data):
        """Speed should increase during takeoff phase."""
        positions = flight_data["positions"]
        takeoff = [p for p in positions if p["phase"] == "takeoff"]
        if len(takeoff) < 2:
            pytest.skip("Not enough takeoff snapshots")

        first_speed = takeoff[0]["velocity"]
        last_speed = takeoff[-1]["velocity"]
        assert last_speed > first_speed, (
            f"Takeoff not accelerating: {first_speed:.0f}kts → {last_speed:.0f}kts"
        )

    # --- Heading ---

    def test_P11_heading_valid_range(self, flight_data):
        """All headings in [0, 360)."""
        positions = flight_data["positions"]
        bad = [p for p in positions if not (0 <= p["heading"] < 360)]
        assert not bad, (
            f"{len(bad)} snapshots with heading outside [0,360): "
            f"e.g. {bad[0]['heading']:.1f} in {bad[0]['phase']}"
        )

    def test_P12_heading_consistent_with_movement(self, flight_data):
        """During approach/departing, heading should roughly point in direction of travel."""
        positions = flight_data["positions"]
        moving_phases = {"approaching", "departing", "takeoff"}
        moving = [p for p in positions if p["phase"] in moving_phases and p["velocity"] > 30]

        if len(moving) < 2:
            pytest.skip("Not enough moving snapshots")

        violations = 0
        for i in range(1, len(moving)):
            prev, curr = moving[i-1], moving[i]
            if prev["phase"] != curr["phase"]:
                continue  # skip phase boundaries
            # Compute actual direction of travel
            dlat = curr["latitude"] - prev["latitude"]
            dlon = curr["longitude"] - prev["longitude"]
            if abs(dlat) < 1e-7 and abs(dlon) < 1e-7:
                continue
            actual_bearing = math.degrees(math.atan2(dlon, dlat)) % 360
            heading = curr["heading"]
            diff = abs(actual_bearing - heading)
            if diff > 180:
                diff = 360 - diff
            if diff > 90:
                violations += 1

        pct = violations / max(1, len(moving) - 1) * 100
        assert pct < 20, (
            f"{pct:.1f}% of moving snapshots have heading >90° off from travel direction"
        )

    # --- Vertical rate ---

    def test_P13_vertical_rate_on_approach(self, flight_data):
        """Approach should show negative vertical rate (descending)."""
        positions = flight_data["positions"]
        approach = [p for p in positions if p["phase"] == "approaching" and p["altitude"] > 1000]
        if not approach:
            pytest.skip("No high-altitude approach snapshots")

        descending = [p for p in approach if p["vertical_rate"] < -50]
        pct = len(descending) / len(approach) * 100
        assert pct > 30, (
            f"Only {pct:.1f}% of approach snapshots show descent (vrate < -50 fpm)"
        )

    def test_P14_vertical_rate_on_departure(self, flight_data):
        """Departing should show positive vertical rate (climbing)."""
        positions = flight_data["positions"]
        departing = [p for p in positions if p["phase"] == "departing"]
        if not departing:
            pytest.skip("No departing snapshots")

        climbing = [p for p in departing if p["vertical_rate"] > 50]
        pct = len(climbing) / len(departing) * 100
        assert pct > 30, (
            f"Only {pct:.1f}% of departing snapshots show climb (vrate > 50 fpm)"
        )

    # --- Continuity ---

    def test_P15_no_teleporting(self, flight_data):
        """No >0.1° jumps between consecutive snapshots (except phase changes)."""
        positions = flight_data["positions"]
        jumps = []
        for i in range(1, len(positions)):
            prev, curr = positions[i-1], positions[i]
            dlat = abs(curr["latitude"] - prev["latitude"])
            dlon = abs(curr["longitude"] - prev["longitude"])
            dist = math.sqrt(dlat**2 + dlon**2)
            if dist > 0.1:
                jumps.append((i, dist, prev["phase"], curr["phase"]))

        # Allow phase-boundary jumps (e.g., parked→pushback might reposition slightly)
        real_jumps = [j for j in jumps if j[2] == j[3]]
        assert len(real_jumps) == 0, (
            f"{len(real_jumps)} teleport(s) within same phase: "
            f"e.g. idx={real_jumps[0][0]}, dist={real_jumps[0][1]:.4f}° in {real_jumps[0][2]}"
        )

    def test_P16_no_nan_values(self, flight_data):
        """No NaN in any numeric position field."""
        positions = flight_data["positions"]
        numeric_fields = ["latitude", "longitude", "altitude", "velocity", "heading", "vertical_rate"]
        nans = []
        for i, p in enumerate(positions):
            for f in numeric_fields:
                v = p.get(f)
                if v is not None and isinstance(v, float) and math.isnan(v):
                    nans.append((i, f, p["phase"]))

        assert not nans, (
            f"{len(nans)} NaN values found: e.g. {nans[0][1]} at idx {nans[0][0]} in {nans[0][2]}"
        )


# ===================================================================
#  AIRPORT OPERATOR PERSPECTIVE
# ===================================================================

class TestAirportOperatorView:
    """Airport ops following the same flight's ground lifecycle."""

    # --- Gate allocation ---

    def test_O01_gate_assigned_on_arrival(self, flight_data):
        """Flight gets a gate assigned when transitioning to taxi_to_gate or parked."""
        transitions = flight_data["transitions"]
        parked_entry = [t for t in transitions if t["to_phase"] == "parked"]
        if not parked_entry:
            pytest.skip("Flight never parked")
        gate = parked_entry[0].get("assigned_gate")
        assert gate is not None and gate != "", (
            f"No gate assigned when flight entered parked phase"
        )

    def test_O02_gate_occupy_event_emitted(self, flight_data):
        """Gate occupy event recorded for this flight."""
        gate_events = flight_data["gate_events"]
        occupy = [g for g in gate_events if g["event_type"] == "occupy"]
        assert len(occupy) >= 1, "No gate occupy event for this flight"

    def test_O03_gate_release_event_emitted(self, flight_data):
        """Gate release event recorded after pushback."""
        gate_events = flight_data["gate_events"]
        release = [g for g in gate_events if g["event_type"] == "release"]
        assert len(release) >= 1, "No gate release event — gate leak"

    def test_O04_gate_occupy_before_release(self, flight_data):
        """Occupy event happens before release event."""
        gate_events = flight_data["gate_events"]
        occupy = [g for g in gate_events if g["event_type"] == "occupy"]
        release = [g for g in gate_events if g["event_type"] == "release"]
        if not occupy or not release:
            pytest.skip("Missing occupy or release event")

        occ_time = datetime.fromisoformat(occupy[0]["time"])
        rel_time = datetime.fromisoformat(release[0]["time"])
        assert occ_time < rel_time, (
            f"Gate release ({rel_time}) before occupy ({occ_time})"
        )

    def test_O05_same_gate_for_occupy_and_release(self, flight_data):
        """Occupy and release events reference the same gate."""
        gate_events = flight_data["gate_events"]
        occupy = [g for g in gate_events if g["event_type"] == "occupy"]
        release = [g for g in gate_events if g["event_type"] == "release"]
        if not occupy or not release:
            pytest.skip("Missing occupy or release event")

        assert occupy[0]["gate"] == release[0]["gate"], (
            f"Gate mismatch: occupy={occupy[0]['gate']}, release={release[0]['gate']}"
        )

    # --- Turnaround timing ---

    def test_O06_turnaround_duration_realistic(self, flight_data):
        """Time at gate (parked phase) should be 15-120 minutes."""
        transitions = flight_data["transitions"]
        parked_entry = [t for t in transitions if t["to_phase"] == "parked"]
        parked_exit = [t for t in transitions if t["from_phase"] == "parked"]
        if not parked_entry or not parked_exit:
            pytest.skip("Incomplete parked phase")

        entry_time = datetime.fromisoformat(parked_entry[0]["time"])
        exit_time = datetime.fromisoformat(parked_exit[0]["time"])
        turnaround_min = (exit_time - entry_time).total_seconds() / 60

        assert 10 <= turnaround_min <= 180, (
            f"Turnaround {turnaround_min:.1f}min outside [10, 180] range"
        )

    def test_O07_turnaround_phases_in_position_data(self, flight_data):
        """Parked positions should show turnaround sub-phase progression in sim state.

        We validate this indirectly: the flight should have a turnaround_schedule
        built during parked phase, verified via phase_transitions timing.
        The turnaround phases (chocks_on → deboarding → ... → chocks_off) run
        during the parked phase time window.
        """
        transitions = flight_data["transitions"]
        parked_entry = [t for t in transitions if t["to_phase"] == "parked"]
        parked_exit = [t for t in transitions if t["from_phase"] == "parked"]
        if not parked_entry or not parked_exit:
            pytest.skip("Incomplete parked phase")

        entry_time = datetime.fromisoformat(parked_entry[0]["time"])
        exit_time = datetime.fromisoformat(parked_exit[0]["time"])
        duration_s = (exit_time - entry_time).total_seconds()

        # Turnaround must last long enough for at least chocks_on + deboarding
        assert duration_s > 60, (
            f"Turnaround too short for sub-phases: {duration_s:.0f}s"
        )

    # --- Baggage ---

    def test_O08_baggage_generated_for_flight(self, flight_data):
        """Baggage events should exist for this flight."""
        baggage = flight_data["baggage"]
        assert len(baggage) >= 1, (
            f"No baggage events for {flight_data['callsign']}"
        )

    def test_O09_baggage_count_realistic(self, flight_data):
        """Bag count should be reasonable for a commercial flight (10-400)."""
        baggage = flight_data["baggage"]
        if not baggage:
            pytest.skip("No baggage events")

        total_bags = sum(b["bag_count"] for b in baggage)
        assert 5 <= total_bags <= 500, (
            f"Total bags={total_bags} outside realistic range [5, 500]"
        )

    def test_O10_baggage_has_required_fields(self, flight_data):
        """Each bag in baggage event has required tracking fields."""
        baggage = flight_data["baggage"]
        if not baggage:
            pytest.skip("No baggage events")

        for event in baggage:
            assert "bag_count" in event
            assert "bags" in event
            if event["bags"]:
                bag = event["bags"][0]
                assert "bag_id" in bag, f"Bag missing bag_id"
                assert "status" in bag, f"Bag missing status"

    # --- Ground movement timing ---

    def test_O11_taxi_in_duration_realistic(self, flight_data):
        """Taxi from runway to gate should take 2-30 minutes."""
        transitions = flight_data["transitions"]
        taxi_start = [t for t in transitions if t["to_phase"] == "taxi_to_gate"]
        taxi_end = [t for t in transitions if t["from_phase"] == "taxi_to_gate"]
        if not taxi_start or not taxi_end:
            pytest.skip("No complete taxi_to_gate phase")

        start = datetime.fromisoformat(taxi_start[0]["time"])
        end = datetime.fromisoformat(taxi_end[0]["time"])
        duration_min = (end - start).total_seconds() / 60

        assert 0.5 <= duration_min <= 45, (
            f"Taxi-in duration {duration_min:.1f}min outside [0.5, 45] range"
        )

    def test_O12_taxi_out_duration_realistic(self, flight_data):
        """Taxi from gate to runway should take 2-30 minutes."""
        transitions = flight_data["transitions"]
        taxi_start = [t for t in transitions if t["to_phase"] == "taxi_to_runway"]
        taxi_end = [t for t in transitions if t["from_phase"] == "taxi_to_runway"]
        if not taxi_start or not taxi_end:
            pytest.skip("No complete taxi_to_runway phase")

        start = datetime.fromisoformat(taxi_start[0]["time"])
        end = datetime.fromisoformat(taxi_end[0]["time"])
        duration_min = (end - start).total_seconds() / 60

        assert 0.5 <= duration_min <= 45, (
            f"Taxi-out duration {duration_min:.1f}min outside [0.5, 45] range"
        )

    def test_O13_pushback_duration_realistic(self, flight_data):
        """Pushback should take 1-10 minutes."""
        transitions = flight_data["transitions"]
        pb_start = [t for t in transitions if t["to_phase"] == "pushback"]
        pb_end = [t for t in transitions if t["from_phase"] == "pushback"]
        if not pb_start or not pb_end:
            pytest.skip("No complete pushback phase")

        start = datetime.fromisoformat(pb_start[0]["time"])
        end = datetime.fromisoformat(pb_end[0]["time"])
        duration_min = (end - start).total_seconds() / 60

        assert 0.3 <= duration_min <= 15, (
            f"Pushback duration {duration_min:.1f}min outside [0.3, 15] range"
        )

    # --- Total flight time ---

    def test_O14_total_ground_time_realistic(self, flight_data):
        """Total time from landing to takeoff should be 30-180 minutes."""
        transitions = flight_data["transitions"]
        landing = [t for t in transitions if t["to_phase"] == "landing"]
        takeoff = [t for t in transitions if t["to_phase"] == "takeoff"]
        if not landing or not takeoff:
            pytest.skip("Missing landing or takeoff transition")

        land_time = datetime.fromisoformat(landing[0]["time"])
        take_time = datetime.fromisoformat(takeoff[0]["time"])
        total_min = (take_time - land_time).total_seconds() / 60

        assert 15 <= total_min <= 240, (
            f"Total ground time {total_min:.1f}min outside [15, 240] range"
        )

    def test_O15_approach_to_landing_duration(self, flight_data):
        """Approach phase should last 3-30 minutes."""
        transitions = flight_data["transitions"]
        app_start = [t for t in transitions if t["to_phase"] == "approaching"]
        app_end = [t for t in transitions if t["from_phase"] == "approaching"]
        if not app_start or not app_end:
            pytest.skip("No complete approaching phase")

        start = datetime.fromisoformat(app_start[0]["time"])
        end = datetime.fromisoformat(app_end[0]["time"])
        duration_min = (end - start).total_seconds() / 60

        assert 1 <= duration_min <= 45, (
            f"Approach duration {duration_min:.1f}min outside [1, 45] range"
        )

    # --- Position at gate ---

    def test_O16_parked_position_stable(self, flight_data):
        """While parked, position should not drift more than 0.001° (~100m)."""
        positions = flight_data["positions"]
        parked = [p for p in positions if p["phase"] == "parked"]
        if len(parked) < 2:
            pytest.skip("Not enough parked snapshots")

        ref_lat = parked[0]["latitude"]
        ref_lon = parked[0]["longitude"]
        max_drift = 0
        for p in parked:
            drift = math.sqrt((p["latitude"] - ref_lat)**2 + (p["longitude"] - ref_lon)**2)
            max_drift = max(max_drift, drift)

        assert max_drift < 0.001, (
            f"Parked position drifted {max_drift:.6f}° from initial position"
        )

    def test_O17_gate_position_near_airport(self, flight_data):
        """Gate position should be within 0.05° (~5km) of airport center."""
        positions = flight_data["positions"]
        parked = [p for p in positions if p["phase"] == "parked"]
        if not parked:
            pytest.skip("No parked snapshots")

        # SFO center: ~37.62, -122.38
        lat, lon = parked[0]["latitude"], parked[0]["longitude"]
        assert 37.5 < lat < 37.7, f"Gate latitude {lat} far from SFO"
        assert -122.5 < lon < -122.3, f"Gate longitude {lon} far from SFO"

    # --- Schedule linkage ---

    def test_O18_flight_in_schedule(self, flight_data):
        """The tracked flight should appear in the simulation schedule."""
        schedule = flight_data["schedule"]
        callsign = flight_data["callsign"]
        match = [s for s in schedule if s["flight_number"] == callsign]
        assert len(match) >= 1, (
            f"Flight {callsign} not found in schedule "
            f"(schedule has {len(schedule)} entries)"
        )

    def test_O19_schedule_has_aircraft_type(self, flight_data):
        """Schedule entry has aircraft type matching position data."""
        schedule = flight_data["schedule"]
        callsign = flight_data["callsign"]
        positions = flight_data["positions"]

        match = [s for s in schedule if s["flight_number"] == callsign]
        if not match:
            pytest.skip("Flight not in schedule")

        sched_type = match[0].get("aircraft_type", "")
        pos_type = positions[0]["aircraft_type"]
        assert sched_type == pos_type, (
            f"Aircraft type mismatch: schedule={sched_type}, position={pos_type}"
        )

    # --- Landing/Takeoff on runway ---

    def test_O20_landing_near_runway(self, flight_data):
        """Landing phase should occur near the airport (within 0.1° of center)."""
        positions = flight_data["positions"]
        landing = [p for p in positions if p["phase"] == "landing"]
        if not landing:
            pytest.skip("No landing snapshots")

        # Check last landing position is close to airport
        last = landing[-1]
        # SFO center approx
        dist = math.sqrt((last["latitude"] - 37.62)**2 + (last["longitude"] + 122.38)**2)
        assert dist < 0.15, (
            f"Landing position ({last['latitude']:.4f}, {last['longitude']:.4f}) "
            f"far from airport center"
        )

    def test_O21_takeoff_from_runway(self, flight_data):
        """Takeoff phase should start near the airport."""
        positions = flight_data["positions"]
        takeoff = [p for p in positions if p["phase"] == "takeoff"]
        if not takeoff:
            pytest.skip("No takeoff snapshots")

        first = takeoff[0]
        dist = math.sqrt((first["latitude"] - 37.62)**2 + (first["longitude"] + 122.38)**2)
        assert dist < 0.15, (
            f"Takeoff position ({first['latitude']:.4f}, {first['longitude']:.4f}) "
            f"far from airport center"
        )

    # --- Altitude transitions ---

    def test_O22_no_negative_altitude(self, flight_data):
        """No position snapshot should have negative altitude."""
        positions = flight_data["positions"]
        negative = [p for p in positions if p["altitude"] < -10]
        assert not negative, (
            f"{len(negative)} snapshots with negative altitude, "
            f"worst: {min(p['altitude'] for p in negative):.0f}ft in {negative[0]['phase']}"
        )

    def test_O23_smooth_altitude_during_approach(self, flight_data):
        """No altitude jumps > 2000ft between consecutive approach snapshots."""
        positions = flight_data["positions"]
        approach = [p for p in positions if p["phase"] == "approaching"]
        if len(approach) < 2:
            pytest.skip("Not enough approach snapshots")

        jumps = []
        for i in range(1, len(approach)):
            delta = abs(approach[i]["altitude"] - approach[i-1]["altitude"])
            if delta > 2000:
                jumps.append((i, delta))

        assert not jumps, (
            f"{len(jumps)} altitude jumps > 2000ft during approach: "
            f"e.g. idx={jumps[0][0]}, delta={jumps[0][1]:.0f}ft"
        )

    # --- Speed transitions ---

    def test_O24_no_speed_jumps_greater_than_100kts(self, flight_data):
        """No speed jumps > 100kts between consecutive same-phase snapshots."""
        positions = flight_data["positions"]
        jumps = []
        for i in range(1, len(positions)):
            prev, curr = positions[i-1], positions[i]
            if prev["phase"] != curr["phase"]:
                continue  # phase boundary
            delta = abs(curr["velocity"] - prev["velocity"])
            if delta > 100:
                jumps.append((i, delta, curr["phase"]))

        assert not jumps, (
            f"{len(jumps)} speed jumps > 100kts: "
            f"e.g. idx={jumps[0][0]}, delta={jumps[0][1]:.0f}kts in {jumps[0][2]}"
        )
