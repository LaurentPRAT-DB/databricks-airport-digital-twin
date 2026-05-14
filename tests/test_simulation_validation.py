"""Comprehensive simulation output validation suite.

Downloads simulation data from Databricks UC Volume (via scripts/download_simulation_data.py),
then validates flight behavior, phase transitions, go-arounds, diversions, routes, and physics
for all 33 airports.

Run:
  uv run pytest tests/test_simulation_validation.py -v --tb=short
  uv run pytest tests/test_simulation_validation.py -k "sfo" -v   # single airport
"""

import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pytest

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "cache" / "simulations"

AIRPORTS = [
    "ams", "atl", "bos", "cdg", "clt", "den", "dfw", "dtw", "dxb", "ewr",
    "fra", "gru", "hkg", "iah", "icn", "jfk", "jnb", "las", "lax", "lhr",
    "mco", "mia", "msp", "nrt", "ord", "pdx", "phl", "phx", "san", "sea",
    "sfo", "sin", "syd",
]

VALID_PHASES = {
    "scheduled", "enroute", "approaching", "landing", "taxi_to_gate", "parked",
    "pushback", "taxi_to_runway", "takeoff", "departing", "departed", "diverted",
}

VALID_TRANSITIONS = {
    # Arrival lifecycle
    ("scheduled", "approaching"),     # arrival spawn
    ("enroute", "approaching"),       # re-approach after go-around
    ("approaching", "landing"),
    ("landing", "taxi_to_gate"),
    ("taxi_to_gate", "parked"),
    # Departure lifecycle
    ("scheduled", "parked"),          # departure spawn at gate
    ("parked", "pushback"),
    ("pushback", "taxi_to_runway"),
    ("taxi_to_runway", "takeoff"),
    ("takeoff", "departing"),
    ("departing", "enroute"),         # climb to cruise
    # Go-around / diversion
    ("approaching", "enroute"),       # go-around
    ("approaching", "diverted"),      # diversion from approach
    ("enroute", "diverted"),          # diversion from enroute
}

_data_cache: dict[str, dict] = {}


def _load_simulation(airport: str) -> dict | None:
    """Load simulation JSON for an airport (cached)."""
    if airport in _data_cache:
        return _data_cache[airport]

    path = DATA_DIR / f"cal_{airport}_normal_d1.json"
    if not path.exists():
        return None

    with open(path) as f:
        data = json.load(f)
    _data_cache[airport] = data
    return data


def _available_airports() -> list[str]:
    """Return airports that have downloaded data."""
    available = []
    for airport in AIRPORTS:
        path = DATA_DIR / f"cal_{airport}_normal_d1.json"
        if path.exists():
            available.append(airport)
    return available


def _get_airport_ids():
    """Generate pytest parametrize IDs for available airports."""
    available = _available_airports()
    if not available:
        pytest.skip("No simulation data downloaded. Run: uv run python scripts/download_simulation_data.py")
    return available


# ---------------------------------------------------------------------------
# A. Structural Integrity
# ---------------------------------------------------------------------------

class TestStructuralIntegrity:
    @pytest.fixture(params=_available_airports() or ["_skip_"], ids=lambda x: x)
    def sim(self, request):
        if request.param == "_skip_":
            pytest.skip("No simulation data downloaded")
        data = _load_simulation(request.param)
        if data is None:
            pytest.skip(f"No data for {request.param}")
        return data

    def test_top_level_keys(self, sim):
        required = {"config", "summary", "schedule", "position_snapshots",
                    "phase_transitions", "gate_events", "scenario_events"}
        assert required.issubset(set(sim.keys()))

    def test_flight_count_consistency(self, sim):
        summary = sim["summary"]
        assert summary["total_flights"] == summary["arrivals"] + summary["departures"]

    def test_position_timestamps_ordered(self, sim):
        snapshots = sim["position_snapshots"]
        if len(snapshots) < 2:
            return
        times = [s["time"] for s in snapshots]
        for i in range(1, min(len(times), 1000)):
            assert times[i] >= times[i - 1], f"Timestamp out of order at index {i}"

    def test_icao24_format(self, sim):
        icao_pattern = re.compile(r"^sim\d{5}$")
        sample = sim["position_snapshots"][:500]
        for s in sample:
            assert icao_pattern.match(s["icao24"]), f"Invalid icao24: {s['icao24']}"

    def test_schedule_entries_have_required_fields(self, sim):
        required_fields = {"flight_number", "flight_type", "scheduled_time", "aircraft_type"}
        for entry in sim["schedule"][:50]:
            missing = required_fields - set(entry.keys())
            assert not missing, f"Schedule entry missing: {missing}"

    def test_position_snapshots_have_coordinates(self, sim):
        for s in sim["position_snapshots"][:100]:
            assert -90 <= s["latitude"] <= 90, f"Invalid lat: {s['latitude']}"
            assert -180 <= s["longitude"] <= 180, f"Invalid lon: {s['longitude']}"
            assert s["altitude"] >= 0, f"Negative altitude: {s['altitude']}"


# ---------------------------------------------------------------------------
# B. Phase Transition Validity
# ---------------------------------------------------------------------------

class TestPhaseTransitions:
    @pytest.fixture(params=_available_airports() or ["_skip_"], ids=lambda x: x)
    def sim(self, request):
        if request.param == "_skip_":
            pytest.skip("No simulation data downloaded")
        data = _load_simulation(request.param)
        if data is None:
            pytest.skip(f"No data for {request.param}")
        return data

    def test_all_phases_are_valid(self, sim):
        for pt in sim["phase_transitions"]:
            assert pt["from_phase"] in VALID_PHASES, f"Invalid from_phase: {pt['from_phase']}"
            assert pt["to_phase"] in VALID_PHASES, f"Invalid to_phase: {pt['to_phase']}"

    def test_no_impossible_transitions(self, sim):
        impossible = {
            ("parked", "approaching"),
            ("parked", "landing"),
            ("takeoff", "parked"),
            ("departed", "approaching"),
            ("departed", "parked"),
            ("taxi_to_gate", "takeoff"),
        }
        for pt in sim["phase_transitions"]:
            pair = (pt["from_phase"], pt["to_phase"])
            assert pair not in impossible, (
                f"Impossible transition {pair} for {pt['icao24']} at {pt['time']}"
            )

    def test_transitions_are_known(self, sim):
        unknown = []
        for pt in sim["phase_transitions"]:
            pair = (pt["from_phase"], pt["to_phase"])
            if pair not in VALID_TRANSITIONS:
                unknown.append(f"{pt['icao24']}: {pair}")

        if unknown:
            # Allow up to 1% unknown transitions (edge cases from force_advance)
            ratio = len(unknown) / max(len(sim["phase_transitions"]), 1)
            assert ratio < 0.01, (
                f"{len(unknown)} unknown transitions ({ratio:.1%}): {unknown[:5]}"
            )

    def test_completed_arrivals_reach_parked(self, sim):
        """Arrivals that reached taxi_to_gate should eventually appear as parked in snapshots."""
        transitions_by_flight = defaultdict(list)
        for pt in sim["phase_transitions"]:
            transitions_by_flight[pt["icao24"]].append(pt)

        reached_taxi = set()
        for icao24, pts in transitions_by_flight.items():
            if any(pt["to_phase"] == "taxi_to_gate" for pt in pts):
                reached_taxi.add(icao24)

        if not reached_taxi:
            pytest.skip("No arrivals reached taxi_to_gate")

        # Check snapshots for parked phase (transition records are inconsistent)
        parked_in_snapshots = set()
        for s in sim["position_snapshots"]:
            if s["phase"] == "parked" and s["icao24"] in reached_taxi:
                parked_in_snapshots.add(s["icao24"])

        ratio = len(parked_in_snapshots) / len(reached_taxi)
        assert ratio > 0.5, (
            f"Only {len(parked_in_snapshots)}/{len(reached_taxi)} arrivals that taxied appear parked"
        )

    def test_completed_departures_reach_departing(self, sim):
        """Departures that reached takeoff should eventually reach departing/enroute."""
        transitions_by_flight = defaultdict(list)
        for pt in sim["phase_transitions"]:
            transitions_by_flight[pt["icao24"]].append(pt)

        reached_takeoff = []
        reached_departing = []
        for icao24, pts in transitions_by_flight.items():
            if any(pt["to_phase"] == "takeoff" for pt in pts):
                reached_takeoff.append(icao24)
                if any(pt["to_phase"] in ("departing", "enroute") for pt in pts):
                    reached_departing.append(icao24)

        if not reached_takeoff:
            pytest.skip("No departures reached takeoff")

        ratio = len(reached_departing) / len(reached_takeoff)
        assert ratio > 0.8, (
            f"Only {len(reached_departing)}/{len(reached_takeoff)} departures that took off reached departing"
        )


# ---------------------------------------------------------------------------
# C. Go-Around Behavior
# ---------------------------------------------------------------------------

class TestGoAroundBehavior:
    @pytest.fixture(params=_available_airports() or ["_skip_"], ids=lambda x: x)
    def sim(self, request):
        if request.param == "_skip_":
            pytest.skip("No simulation data downloaded")
        data = _load_simulation(request.param)
        if data is None:
            pytest.skip(f"No data for {request.param}")
        return data

    def test_go_around_events_have_evidence_in_transitions(self, sim):
        """Go-around flights should show evidence of re-approach (multiple approach→landing)
        or an explicit approaching→enroute transition."""
        ga_events = [e for e in sim["scenario_events"] if e.get("event_type") == "go_around"]
        if not ga_events:
            pytest.skip("No go-arounds in this simulation")

        transitions_by_flight = defaultdict(list)
        for pt in sim["phase_transitions"]:
            transitions_by_flight[pt["icao24"]].append(pt)

        unmatched = []
        for event in ga_events:
            icao24 = event.get("icao24")
            if not icao24:
                continue
            pts = transitions_by_flight.get(icao24, [])
            # Evidence: explicit approaching→enroute OR multiple approaches
            has_ga_transition = any(
                pt["from_phase"] == "approaching" and pt["to_phase"] == "enroute"
                for pt in pts
            )
            approach_count = sum(
                1 for pt in pts if pt["to_phase"] in ("approaching", "landing")
                and pt["from_phase"] in ("scheduled", "enroute", "approaching")
            )
            if not has_ga_transition and approach_count < 2:
                unmatched.append(icao24)

        assert len(unmatched) <= 2, (
            f"{len(unmatched)}/{len(ga_events)} go-arounds without re-approach evidence: {unmatched[:5]}"
        )

    def test_go_around_flight_reapproaches(self, sim):
        ga_events = [e for e in sim["scenario_events"] if e.get("event_type") == "go_around"]
        if not ga_events:
            pytest.skip("No go-arounds in this simulation")

        transitions_by_flight = defaultdict(list)
        for pt in sim["phase_transitions"]:
            transitions_by_flight[pt["icao24"]].append(pt)

        no_reapproach = []
        for event in ga_events:
            icao24 = event.get("icao24")
            if not icao24:
                continue
            pts = transitions_by_flight.get(icao24, [])
            ga_indices = [
                i for i, pt in enumerate(pts)
                if pt["from_phase"] == "approaching" and pt["to_phase"] == "enroute"
            ]
            for idx in ga_indices:
                later_approach = any(
                    pt["to_phase"] == "approaching" or pt["to_phase"] == "diverted"
                    for pt in pts[idx + 1:]
                )
                if not later_approach:
                    no_reapproach.append(icao24)

        # Some go-arounds at end of simulation may not have time to reapproach
        ratio = len(no_reapproach) / max(len(ga_events), 1)
        assert ratio < 0.3, (
            f"{len(no_reapproach)}/{len(ga_events)} go-arounds never reapproached: {no_reapproach[:5]}"
        )

    def test_max_go_arounds_per_flight(self, sim):
        ga_events = [e for e in sim["scenario_events"] if e.get("event_type") == "go_around"]
        if not ga_events:
            pytest.skip("No go-arounds in this simulation")

        ga_counts = defaultdict(int)
        for event in ga_events:
            icao24 = event.get("icao24")
            if icao24:
                ga_counts[icao24] += 1

        for icao24, count in ga_counts.items():
            assert count <= 4, f"{icao24} had {count} go-arounds (max 3 expected before diversion)"

    def test_go_around_seekability(self, sim):
        """Verify go-around events are seekable (visible in position data near event time)."""
        ga_events = [e for e in sim["scenario_events"] if e.get("event_type") == "go_around"]
        if not ga_events:
            pytest.skip("No go-arounds in this simulation")

        snapshots = sim["position_snapshots"]
        if not snapshots:
            pytest.skip("No position snapshots")

        # Group snapshots by timestamp (frame)
        frames: dict[str, list[dict]] = defaultdict(list)
        for s in snapshots:
            frames[s["time"]].append(s)
        frame_times = sorted(frames.keys())

        # Get airport center from config or first snapshot
        config = sim.get("config", {})
        airport_lat = None
        airport_lon = None
        # Approximate center from first ground-level snapshot
        for s in snapshots[:100]:
            if s.get("on_ground") and s["altitude"] < 50:
                airport_lat = s["latitude"]
                airport_lon = s["longitude"]
                break

        unseekable = []
        for event in ga_events[:20]:  # Limit to first 20 for performance
            icao24 = event.get("icao24")
            callsign = event.get("callsign")
            if not icao24:
                continue

            event_time = event["time"]
            # Seek target: 120s before event
            try:
                et = datetime.fromisoformat(event_time)
                from datetime import timedelta
                seek_target = (et - timedelta(seconds=120)).isoformat()
            except (ValueError, TypeError):
                continue

            # Find nearest frame
            target_idx = 0
            for i, ft in enumerate(frame_times):
                if ft >= seek_target:
                    target_idx = i
                    break

            # Search ±30 frames
            found = False
            search_start = max(0, target_idx - 30)
            search_end = min(len(frame_times), target_idx + 31)
            for i in range(search_start, search_end):
                frame = frames[frame_times[i]]
                for s in frame:
                    if s["icao24"] == icao24 or s.get("callsign") == callsign:
                        # Check distance from airport center
                        if airport_lat is not None:
                            dlat = abs(s["latitude"] - airport_lat)
                            dlon = abs(s["longitude"] - airport_lon)
                            dist_sq = dlat * dlat + dlon * dlon
                            if dist_sq <= 0.16:  # 0.4² = 0.16
                                found = True
                                break
                        else:
                            found = True
                            break
                if found:
                    break

            if not found:
                unseekable.append(f"{icao24} at {event_time}")

        if unseekable:
            ratio = len(unseekable) / len(ga_events[:20])
            assert ratio < 0.2, (
                f"{len(unseekable)}/{min(len(ga_events), 20)} go-arounds not seekable: {unseekable[:5]}"
            )


# ---------------------------------------------------------------------------
# D. Diversion Behavior
# ---------------------------------------------------------------------------

class TestDiversionBehavior:
    @pytest.fixture(params=_available_airports() or ["_skip_"], ids=lambda x: x)
    def sim(self, request):
        if request.param == "_skip_":
            pytest.skip("No simulation data downloaded")
        data = _load_simulation(request.param)
        if data is None:
            pytest.skip(f"No data for {request.param}")
        return data

    def test_diversion_events_have_matching_transition(self, sim):
        div_events = [e for e in sim["scenario_events"] if e.get("event_type") == "diversion"]
        if not div_events:
            pytest.skip("No diversions in this simulation")

        transitions_by_flight = defaultdict(list)
        for pt in sim["phase_transitions"]:
            transitions_by_flight[pt["icao24"]].append(pt)

        unmatched = []
        for event in div_events:
            icao24 = event.get("icao24")
            if not icao24:
                continue
            pts = transitions_by_flight.get(icao24, [])
            has_diversion = any(pt["to_phase"] == "diverted" for pt in pts)
            if not has_diversion:
                unmatched.append(icao24)

        # Allow some tolerance (diversions at end of sim may not record transition)
        ratio = len(unmatched) / max(len(div_events), 1)
        assert ratio < 0.2, (
            f"{len(unmatched)} diversion events without transition: {unmatched[:5]}"
        )

    def test_diverted_flights_dont_reappear(self, sim):
        transitions_by_flight = defaultdict(list)
        for pt in sim["phase_transitions"]:
            transitions_by_flight[pt["icao24"]].append(pt)

        reappeared = []
        for icao24, pts in transitions_by_flight.items():
            diverted_idx = None
            for i, pt in enumerate(pts):
                if pt["to_phase"] == "diverted":
                    diverted_idx = i
                    break
            if diverted_idx is not None:
                later_approach = any(
                    pt["to_phase"] in ("approaching", "landing")
                    for pt in pts[diverted_idx + 1:]
                )
                if later_approach:
                    reappeared.append(icao24)

        assert len(reappeared) == 0, (
            f"{len(reappeared)} diverted flights reappeared: {reappeared[:5]}"
        )


# ---------------------------------------------------------------------------
# E. Flight Lifecycle Completeness
# ---------------------------------------------------------------------------

class TestFlightLifecycle:
    @pytest.fixture(params=_available_airports() or ["_skip_"], ids=lambda x: x)
    def sim(self, request):
        if request.param == "_skip_":
            pytest.skip("No simulation data downloaded")
        data = _load_simulation(request.param)
        if data is None:
            pytest.skip(f"No data for {request.param}")
        return data

    def test_spawned_arrivals_have_snapshots(self, sim):
        spawned_arrivals = {
            f"sim{i:05d}" for i, entry in enumerate(sim["schedule"])
            if entry["flight_type"] == "arrival" and entry.get("spawned", True)
        }
        if not spawned_arrivals:
            pytest.skip("No spawned arrivals")

        seen_in_snapshots = {s["icao24"] for s in sim["position_snapshots"]}
        missing = spawned_arrivals - seen_in_snapshots
        ratio = len(missing) / len(spawned_arrivals)
        # Larger sims (500+ flights over 36h) commonly have 15-30% late arrivals
        # that are marked spawned but arrive after sim recording ends
        threshold = 0.35 if len(spawned_arrivals) > 200 else 0.10
        assert ratio < threshold, (
            f"{len(missing)}/{len(spawned_arrivals)} spawned arrivals have no snapshots: {list(missing)[:5]}"
        )

    def test_spawned_departures_have_snapshots(self, sim):
        arrivals_count = sum(1 for e in sim["schedule"] if e["flight_type"] == "arrival")
        spawned_departures = {
            f"sim{i:05d}" for i, entry in enumerate(sim["schedule"])
            if entry["flight_type"] == "departure" and entry.get("spawned", True)
        }
        if not spawned_departures:
            pytest.skip("No spawned departures")

        seen_in_snapshots = {s["icao24"] for s in sim["position_snapshots"]}
        missing = spawned_departures - seen_in_snapshots
        ratio = len(missing) / len(spawned_departures)
        assert ratio < 0.05, (
            f"{len(missing)}/{len(spawned_departures)} spawned departures have no snapshots: {list(missing)[:5]}"
        )

    def test_no_orphan_flights(self, sim):
        """Every icao24 in snapshots should map to a schedule entry."""
        schedule_icao24s = {f"sim{i:05d}" for i in range(len(sim["schedule"]))}
        snapshot_icao24s = {s["icao24"] for s in sim["position_snapshots"]}
        orphans = snapshot_icao24s - schedule_icao24s
        assert len(orphans) == 0, f"Orphan flights in snapshots: {list(orphans)[:10]}"

    def test_gate_events_are_paired(self, sim):
        """Gate occupy/vacate should be reasonably paired."""
        gate_events_by_flight = defaultdict(list)
        for ge in sim["gate_events"]:
            gate_events_by_flight[ge["icao24"]].append(ge["event_type"])

        unpaired = 0
        for icao24, events in gate_events_by_flight.items():
            occupies = events.count("occupy")
            vacates = events.count("vacate")
            # Allow 1 occupy without vacate (flight still parked at end)
            if occupies - vacates > 1:
                unpaired += 1

        ratio = unpaired / max(len(gate_events_by_flight), 1)
        assert ratio < 0.1, f"{unpaired} flights have unpaired gate events"


# ---------------------------------------------------------------------------
# F. Spatial / Physics Validation
# ---------------------------------------------------------------------------

class TestSpatialPhysics:
    @pytest.fixture(params=_available_airports() or ["_skip_"], ids=lambda x: x)
    def sim(self, request):
        if request.param == "_skip_":
            pytest.skip("No simulation data downloaded")
        data = _load_simulation(request.param)
        if data is None:
            pytest.skip(f"No data for {request.param}")
        return data

    def test_parked_flights_stationary(self, sim):
        """Parked flights should have velocity ~0 and altitude ~0."""
        parked = [s for s in sim["position_snapshots"][:5000] if s["phase"] == "parked"]
        if not parked:
            pytest.skip("No parked snapshots in sample")

        moving = [s for s in parked if s["velocity"] > 2.0]
        ratio = len(moving) / len(parked)
        assert ratio < 0.05, f"{len(moving)}/{len(parked)} parked flights are moving"

        elevated = [s for s in parked if s["altitude"] > 50]
        ratio = len(elevated) / len(parked)
        assert ratio < 0.01, f"{len(elevated)}/{len(parked)} parked flights have altitude > 50ft"

    def test_taxi_speed_reasonable(self, sim):
        """Taxi velocity should be < 35 kts (velocity field is in knots)."""
        taxi_phases = {"taxi_to_gate", "taxi_to_runway"}
        taxi_snaps = [
            s for s in sim["position_snapshots"][:5000]
            if s["phase"] in taxi_phases
        ]
        if not taxi_snaps:
            pytest.skip("No taxi snapshots in sample")

        too_fast = [s for s in taxi_snaps if s["velocity"] > 35.0]
        ratio = len(too_fast) / len(taxi_snaps)
        assert ratio < 0.05, (
            f"{len(too_fast)}/{len(taxi_snaps)} taxi snapshots exceeding 35 kts"
        )

    def test_no_teleportation(self, sim):
        """No position jumps > 0.1° between consecutive snapshots for same flight."""
        snapshots_by_flight = defaultdict(list)
        for s in sim["position_snapshots"][:10000]:
            snapshots_by_flight[s["icao24"]].append(s)

        # Phases where large jumps are expected/acceptable
        exempt_phases = {"enroute", "departed", "diverted", "parked", "pushback"}

        teleports = []
        for icao24, snaps in list(snapshots_by_flight.items())[:50]:
            for i in range(1, len(snaps)):
                if snaps[i]["phase"] in exempt_phases or snaps[i-1]["phase"] in exempt_phases:
                    continue
                dlat = abs(snaps[i]["latitude"] - snaps[i-1]["latitude"])
                dlon = abs(snaps[i]["longitude"] - snaps[i-1]["longitude"])
                if dlat > 0.1 or dlon > 0.1:
                    teleports.append(
                        f"{icao24} {snaps[i]['phase']}: ({dlat:.3f}, {dlon:.3f}) at {snaps[i]['time']}"
                    )

        assert len(teleports) < 5, f"Teleportation detected: {teleports[:5]}"

    def test_landing_altitude_decreases(self, sim):
        """During landing phase, altitude should generally decrease."""
        snapshots_by_flight = defaultdict(list)
        for s in sim["position_snapshots"]:
            if s["phase"] == "landing":
                snapshots_by_flight[s["icao24"]].append(s)

        if not snapshots_by_flight:
            pytest.skip("No landing snapshots")

        violations = 0
        checked = 0
        for icao24, snaps in list(snapshots_by_flight.items())[:30]:
            if len(snaps) < 3:
                continue
            checked += 1
            increases = sum(
                1 for i in range(1, len(snaps))
                if snaps[i]["altitude"] > snaps[i-1]["altitude"] + 50
            )
            if increases > len(snaps) * 0.3:
                violations += 1

        if checked > 0:
            ratio = violations / checked
            assert ratio < 0.2, f"{violations}/{checked} flights have altitude increasing during landing"

    def test_takeoff_altitude_increases(self, sim):
        """During takeoff, altitude should eventually increase."""
        snapshots_by_flight = defaultdict(list)
        for s in sim["position_snapshots"]:
            if s["phase"] == "takeoff":
                snapshots_by_flight[s["icao24"]].append(s)

        if not snapshots_by_flight:
            pytest.skip("No takeoff snapshots")

        never_climbed = 0
        checked = 0
        for icao24, snaps in list(snapshots_by_flight.items())[:30]:
            if len(snaps) < 3:
                continue
            checked += 1
            max_alt = max(s["altitude"] for s in snaps)
            if max_alt < 10:
                never_climbed += 1

        if checked > 0:
            ratio = never_climbed / checked
            assert ratio < 0.6, f"{never_climbed}/{checked} takeoff flights never climbed above 10ft"


# ---------------------------------------------------------------------------
# G. Summary Metrics Sanity
# ---------------------------------------------------------------------------

class TestSummaryMetrics:
    @pytest.fixture(params=_available_airports() or ["_skip_"], ids=lambda x: x)
    def sim(self, request):
        if request.param == "_skip_":
            pytest.skip("No simulation data downloaded")
        data = _load_simulation(request.param)
        if data is None:
            pytest.skip(f"No data for {request.param}")
        return data

    def test_on_time_pct_reasonable(self, sim):
        pct = sim["summary"]["on_time_pct"]
        assert 30 <= pct <= 100, f"on_time_pct={pct}% is unreasonable"

    def test_avg_turnaround_reasonable(self, sim):
        ta = sim["summary"]["avg_turnaround_min"]
        if ta == 0:
            pytest.skip("No turnaround data")
        assert 15 <= ta <= 240, f"avg_turnaround_min={ta} is unreasonable"

    def test_peak_simultaneous_flights(self, sim):
        peak = sim["summary"]["peak_simultaneous_flights"]
        assert peak >= 3, f"peak_simultaneous_flights={peak} too low"

    def test_cancellation_rate_not_extreme(self, sim):
        rate = sim["summary"]["cancellation_rate_pct"]
        assert rate < 60, f"cancellation_rate_pct={rate}% too high"

    def test_total_flights_matches_config(self, sim):
        config = sim["config"]
        expected = config.get("arrivals", 0) + config.get("departures", 0)
        actual = sim["summary"]["total_flights"]
        assert actual == expected, f"total_flights={actual}, expected {expected} from config"

    def test_snapshots_exist(self, sim):
        count = sim["summary"]["total_position_snapshots"]
        assert count > 100, f"Only {count} position snapshots"

    def test_phase_transitions_exist(self, sim):
        count = sim["summary"]["total_phase_transitions"]
        assert count > 10, f"Only {count} phase transitions"


# ---------------------------------------------------------------------------
# H. Cross-Airport Consistency (runs once, compares all available airports)
# ---------------------------------------------------------------------------

class TestCrossAirportConsistency:
    def test_all_airports_produce_flights(self):
        available = _available_airports()
        if not available:
            pytest.skip("No simulation data downloaded")

        empty = []
        for airport in available:
            data = _load_simulation(airport)
            if data and data["summary"]["total_flights"] < 10:
                empty.append(airport)

        assert len(empty) == 0, f"Airports with < 10 flights: {empty}"

    def test_no_airport_has_zero_snapshots(self):
        available = _available_airports()
        if not available:
            pytest.skip("No simulation data downloaded")

        zero = []
        for airport in available:
            data = _load_simulation(airport)
            if data and data["summary"]["total_position_snapshots"] == 0:
                zero.append(airport)

        assert len(zero) == 0, f"Airports with 0 snapshots: {zero}"
