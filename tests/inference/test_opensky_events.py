"""Tests for OpenSky event inference pipeline."""

import pytest

from src.inference.opensky_events import (
    OpenSkyEventInferrer,
    haversine_m,
    GATE_MATCH_RADIUS_M,
    STATIONARY_VELOCITY_MS,
)


# ── Test fixtures ────────────────────────────────────────────────────────

# LSGG gate positions (representative subset)
SAMPLE_GATES = [
    {"ref": "A1", "geo": {"latitude": 46.2300, "longitude": 6.1050}, "terminal": "T1"},
    {"ref": "A2", "geo": {"latitude": 46.2302, "longitude": 6.1055}, "terminal": "T1"},
    {"ref": "B1", "geo": {"latitude": 46.2310, "longitude": 6.1070}, "terminal": "T2"},
    {"ref": "R1", "geo": {"latitude": 46.2350, "longitude": 6.1100}, "terminal": None},  # Remote stand
]


def _snap(
    icao24: str = "abc123",
    callsign: str = "SWR100",
    lat: float = 46.2300,
    lon: float = 6.1050,
    altitude: float = 0.0,
    velocity: float = 0.0,  # kts
    heading: float = 90.0,
    on_ground: bool = True,
    vertical_rate: float = 0.0,
) -> dict:
    """Build a frame snapshot dict (post-conversion, in display units)."""
    return {
        "time": "",  # Set by frame timestamp
        "icao24": icao24,
        "callsign": callsign,
        "latitude": lat,
        "longitude": lon,
        "altitude": altitude,
        "velocity": velocity,
        "heading": heading,
        "phase": "ground",
        "on_ground": on_ground,
        "aircraft_type": "",
        "assigned_gate": None,
        "vertical_rate": vertical_rate,
    }


# ── Haversine tests ─────────────────────────────────────────────────────

class TestHaversine:
    def test_zero_distance(self):
        assert haversine_m(46.23, 6.10, 46.23, 6.10) == 0.0

    def test_known_distance(self):
        # ~111 km per degree of latitude
        d = haversine_m(46.0, 6.0, 47.0, 6.0)
        assert 110_000 < d < 112_000

    def test_small_distance(self):
        # Two points ~50m apart
        d = haversine_m(46.2300, 6.1050, 46.23045, 6.1050)
        assert 40 < d < 60


# ── Nearest gate matching ────────────────────────────────────────────────

class TestFindNearestGate:
    def setup_method(self):
        self.inferrer = OpenSkyEventInferrer(SAMPLE_GATES)

    def test_exact_match(self):
        gate, dist = self.inferrer.find_nearest_gate(46.2300, 6.1050)
        assert gate == "A1"
        assert dist < 1.0

    def test_nearest_among_multiple(self):
        gate, dist = self.inferrer.find_nearest_gate(46.2310, 6.1070)
        assert gate == "B1"
        assert dist < 5.0

    def test_beyond_radius(self):
        # Point far from any gate
        gate, dist = self.inferrer.find_nearest_gate(46.25, 6.15)
        assert gate is None

    def test_custom_radius(self):
        # Point at ~200m from nearest gate
        gate, _ = self.inferrer.find_nearest_gate(46.2320, 6.1050, max_dist_m=50)
        assert gate is None  # Too far for 50m radius

    def test_no_gates(self):
        inferrer = OpenSkyEventInferrer([])
        gate, dist = inferrer.find_nearest_gate(46.23, 6.10)
        assert gate is None

    def test_gates_missing_geo(self):
        """Gates without geo coords are silently skipped."""
        inferrer = OpenSkyEventInferrer([
            {"ref": "X1", "geo": {}},
            {"ref": "X2"},
        ])
        assert len(inferrer._gate_positions) == 0


# ── State machine: parking detection ─────────────────────────────────────

class TestParkingDetection:
    def setup_method(self):
        self.inferrer = OpenSkyEventInferrer(SAMPLE_GATES)

    def test_taxi_to_parked_emits_events(self):
        """Aircraft taxiing → stops at gate → should emit occupy + parked."""
        # Frame 1: taxiing (on ground, moving)
        self.inferrer.process_frame("2026-04-03T10:00:00", [
            _snap(velocity=15.0, lat=46.2295, lon=6.1040),  # Moving, away from gate
        ])
        # Frame 2: stopped at gate A1
        self.inferrer.process_frame("2026-04-03T10:01:00", [
            _snap(velocity=0.0, lat=46.2300, lon=6.1050),  # Stationary at gate A1
        ])

        result = self.inferrer.get_results()
        # Should have phase transition to parked
        parked = [pt for pt in result["phase_transitions"] if pt["to_phase"] == "parked"]
        assert len(parked) >= 1
        assert parked[0]["icao24"] == "abc123"

        # Should have gate occupy event
        occupies = [ge for ge in result["gate_events"] if ge["event_type"] == "occupy"]
        assert len(occupies) >= 1
        assert occupies[0]["gate"] == "A1"

    def test_parked_to_pushback_emits_release(self):
        """Parked aircraft starts moving → should emit release + pushback."""
        # Frame 1: taxiing in
        self.inferrer.process_frame("2026-04-03T10:00:00", [
            _snap(velocity=15.0, lat=46.2295, lon=6.1040),
        ])
        # Frame 2: parked
        self.inferrer.process_frame("2026-04-03T10:01:00", [
            _snap(velocity=0.0, lat=46.2300, lon=6.1050),
        ])
        # Frame 3: starts moving (pushback)
        self.inferrer.process_frame("2026-04-03T10:30:00", [
            _snap(velocity=5.0, lat=46.2300, lon=6.1050),
        ])

        result = self.inferrer.get_results()
        releases = [ge for ge in result["gate_events"] if ge["event_type"] == "release"]
        assert len(releases) >= 1
        assert releases[0]["gate"] == "A1"

        pushbacks = [pt for pt in result["phase_transitions"]
                     if pt["from_phase"] == "parked" and pt["to_phase"] == "taxi_to_runway"]
        assert len(pushbacks) >= 1


# ── State machine: airborne transitions ──────────────────────────────────

class TestAirborneTransitions:
    def setup_method(self):
        self.inferrer = OpenSkyEventInferrer(SAMPLE_GATES)

    def test_landing_detection(self):
        """Airborne → on ground should produce landing transition."""
        # Frame 1: airborne, descending
        self.inferrer.process_frame("2026-04-03T10:00:00", [
            _snap(on_ground=False, altitude=2000, velocity=130, vertical_rate=-800),
        ])
        # Frame 2: on ground, decelerating
        self.inferrer.process_frame("2026-04-03T10:01:00", [
            _snap(on_ground=True, altitude=0, velocity=80, vertical_rate=0),
        ])

        result = self.inferrer.get_results()
        transitions = result["phase_transitions"]
        assert len(transitions) >= 1
        # Should transition from a landing/approach phase to taxi
        phases = [(pt["from_phase"], pt["to_phase"]) for pt in transitions]
        assert any("landing" in from_p or "approach" in from_p for from_p, _ in phases) or \
               any("taxi" in to_p for _, to_p in phases)

    def test_takeoff_detection(self):
        """On ground → airborne should produce takeoff transition."""
        # Frame 1: on ground, taxiing
        self.inferrer.process_frame("2026-04-03T10:00:00", [
            _snap(on_ground=True, velocity=15, altitude=0),
        ])
        # Frame 2: airborne, climbing
        self.inferrer.process_frame("2026-04-03T10:01:00", [
            _snap(on_ground=False, velocity=150, altitude=500, vertical_rate=2000),
        ])

        result = self.inferrer.get_results()
        transitions = result["phase_transitions"]
        assert len(transitions) >= 1
        phases = [pt["to_phase"] for pt in transitions]
        assert "takeoff" in phases or "departing" in phases

    def test_cruise_phase(self):
        """Climbing → level at cruise altitude → should transition to cruise."""
        self.inferrer.process_frame("2026-04-03T10:00:00", [
            _snap(on_ground=False, altitude=8000, velocity=250, vertical_rate=500),
        ])
        self.inferrer.process_frame("2026-04-03T10:01:00", [
            _snap(on_ground=False, altitude=35000, velocity=450, vertical_rate=0),
        ])

        result = self.inferrer.get_results()
        transitions = result["phase_transitions"]
        assert any(pt["to_phase"] == "enroute" for pt in transitions)


# ── Multiple aircraft ────────────────────────────────────────────────────

class TestMultipleAircraft:
    def setup_method(self):
        self.inferrer = OpenSkyEventInferrer(SAMPLE_GATES)

    def test_two_aircraft_independent_tracking(self):
        """Two aircraft at different gates tracked independently."""
        self.inferrer.process_frame("2026-04-03T10:00:00", [
            _snap(icao24="ac1", callsign="SWR100", velocity=10, lat=46.2295, lon=6.1040),
            _snap(icao24="ac2", callsign="EZY200", velocity=10, lat=46.2305, lon=6.1065),
        ])
        self.inferrer.process_frame("2026-04-03T10:01:00", [
            _snap(icao24="ac1", callsign="SWR100", velocity=0, lat=46.2300, lon=6.1050),  # Gate A1
            _snap(icao24="ac2", callsign="EZY200", velocity=0, lat=46.2310, lon=6.1070),  # Gate B1
        ])

        result = self.inferrer.get_results()
        occupies = result["gate_events"]
        occupy_gates = {ge["gate"] for ge in occupies if ge["event_type"] == "occupy"}
        assert "A1" in occupy_gates
        assert "B1" in occupy_gates


# ── Event format compatibility ───────────────────────────────────────────

class TestEventFormat:
    """Verify events have all fields expected by src/ml/obt_features.py."""

    def setup_method(self):
        self.inferrer = OpenSkyEventInferrer(SAMPLE_GATES)
        # Generate some events
        self.inferrer.process_frame("2026-04-03T10:00:00", [
            _snap(velocity=15.0, lat=46.2295, lon=6.1040),
        ])
        self.inferrer.process_frame("2026-04-03T10:01:00", [
            _snap(velocity=0.0, lat=46.2300, lon=6.1050),
        ])
        self.result = self.inferrer.get_results()

    def test_phase_transition_fields(self):
        """Phase transitions have all required fields from recorder.py."""
        required = {"time", "icao24", "callsign", "from_phase", "to_phase",
                     "latitude", "longitude", "altitude", "aircraft_type", "assigned_gate"}
        for pt in self.result["phase_transitions"]:
            assert set(pt.keys()) == required, f"Missing fields: {required - set(pt.keys())}"

    def test_gate_event_fields(self):
        """Gate events have all required fields from recorder.py."""
        required = {"time", "icao24", "callsign", "gate", "event_type", "aircraft_type", "gate_distance_m"}
        for ge in self.result["gate_events"]:
            assert set(ge.keys()) == required, f"Missing fields: {required - set(ge.keys())}"
            assert isinstance(ge["gate_distance_m"], float)

    def test_gate_event_types_valid(self):
        """Gate event types are one of assign/occupy/release."""
        valid_types = {"assign", "occupy", "release"}
        for ge in self.result["gate_events"]:
            assert ge["event_type"] in valid_types


# ── Enriched snapshots ───────────────────────────────────────────────────

class TestEnrichedSnapshots:
    def setup_method(self):
        self.inferrer = OpenSkyEventInferrer(SAMPLE_GATES)

    def test_snapshots_accumulated(self):
        """Every processed state vector produces an enriched snapshot."""
        self.inferrer.process_frame("2026-04-03T10:00:00", [
            _snap(icao24="ac1", velocity=10, lat=46.2295, lon=6.1040),
            _snap(icao24="ac2", velocity=10, lat=46.2305, lon=6.1065),
        ])
        self.inferrer.process_frame("2026-04-03T10:01:00", [
            _snap(icao24="ac1", velocity=0, lat=46.2300, lon=6.1050),
        ])
        snaps = self.inferrer.get_enriched_snapshots()
        assert len(snaps) == 3  # 2 in frame 1, 1 in frame 2

    def test_snapshot_has_all_fields(self):
        """Enriched snapshots have the full column set for Delta table."""
        self.inferrer.process_frame("2026-04-03T10:00:00", [_snap()])
        snaps = self.inferrer.get_enriched_snapshots()
        required = {
            "time", "icao24", "callsign", "latitude", "longitude",
            "altitude", "velocity", "heading", "vertical_rate",
            "phase", "on_ground", "aircraft_type", "assigned_gate",
        }
        assert set(snaps[0].keys()) == required

    def test_snapshot_gate_assignment(self):
        """Parked aircraft get assigned_gate in their snapshots."""
        # Frame 1: taxiing
        self.inferrer.process_frame("2026-04-03T10:00:00", [
            _snap(velocity=15.0, lat=46.2295, lon=6.1040),
        ])
        # Frame 2: stopped at gate A1
        self.inferrer.process_frame("2026-04-03T10:01:00", [
            _snap(velocity=0.0, lat=46.2300, lon=6.1050),
        ])
        snaps = self.inferrer.get_enriched_snapshots()
        parked_snaps = [s for s in snaps if s["assigned_gate"] == "A1"]
        assert len(parked_snaps) >= 1

    def test_results_include_enriched_snapshots(self):
        """get_results() includes enriched_snapshots key."""
        self.inferrer.process_frame("2026-04-03T10:00:00", [_snap()])
        result = self.inferrer.get_results()
        assert "enriched_snapshots" in result
        assert len(result["enriched_snapshots"]) == 1


# ── Edge cases ───────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_empty_frames(self):
        inferrer = OpenSkyEventInferrer(SAMPLE_GATES)
        inferrer.process_frame("2026-04-03T10:00:00", [])
        result = inferrer.get_results()
        assert result["phase_transitions"] == []
        assert result["gate_events"] == []

    def test_missing_position_skipped(self):
        inferrer = OpenSkyEventInferrer(SAMPLE_GATES)
        inferrer.process_frame("2026-04-03T10:00:00", [
            _snap(lat=None, lon=6.1050),
        ])
        result = inferrer.get_results()
        assert result["phase_transitions"] == []

    def test_single_frame_no_transitions(self):
        """A single frame can't produce transitions (need before/after)."""
        inferrer = OpenSkyEventInferrer(SAMPLE_GATES)
        inferrer.process_frame("2026-04-03T10:00:00", [
            _snap(velocity=0.0, lat=46.2300, lon=6.1050),
        ])
        result = inferrer.get_results()
        # First observation at gate — no transition emitted (unknown→parked)
        assert len(result["phase_transitions"]) == 0
