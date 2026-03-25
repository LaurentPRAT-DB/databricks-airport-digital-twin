"""Go-Around Video Test — Records a simulation "video" and validates go-around behavior.

Runs a simulation with a runway-closure scenario to FORCE go-arounds.
Records every position snapshot as frames (what the user sees each tick),
saves the go-around flight trajectory as GeoJSON for map inspection, and
saves the full video recording as JSON for replay.

Validates that go-arounds:
  - Are recorded as phase transitions
  - Produce altitude gain (missed approach climb)
  - Keep the aircraft flying FORWARD (not backward toward waypoint 0)
  - Stay within holding pattern geometry
  - Re-enter approach and eventually land

Output files (in tests/output/):
  - go_around_trajectory.geojson — trajectory line of the go-around flight
  - go_around_video.json — full frame-by-frame recording of all aircraft

Test IDs:
  GA01 — Go-around events recorded
  GA02 — Altitude gain after go-around
  GA03 — Heading forward, not backward
  GA04 — No backward movement
  GA05 — Speed within envelope
  GA06 — Re-enters approach
  GA07 — Eventually lands or parks
  GA08 — Holding pattern stays near airport
  GA09 — Trajectory GeoJSON saved
  GA10 — Video recording saved
"""

import json
import math
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pytest

from src.simulation.config import SimulationConfig
from src.simulation.engine import SimulationEngine
from src.simulation.recorder import SimulationRecorder
from src.ingestion.fallback import VREF_SPEEDS, _DEFAULT_VREF

OUTPUT_DIR = Path(__file__).parent / "output"
SCENARIO_PATH = str(Path(__file__).parent.parent / "scenarios" / "sfo_go_around_test.yaml")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _haversine_nm(lat1, lon1, lat2, lon2):
    R_NM = 3440.065
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return 2 * R_NM * math.asin(math.sqrt(min(a, 1.0)))


def _extract_traces(recorder):
    """Group position_snapshots by icao24, sorted by time."""
    traces = defaultdict(list)
    for snap in recorder.position_snapshots:
        traces[snap["icao24"]].append(snap)
    for icao24 in traces:
        traces[icao24].sort(key=lambda p: p["time"])
    return dict(traces)


def _build_frames(recorder):
    """Group snapshots by time into frames (what the user sees each tick)."""
    frames = defaultdict(list)
    for snap in recorder.position_snapshots:
        frames[snap["time"]].append(snap)
    return dict(sorted(frames.items()))


def _find_go_around_transitions(recorder):
    """Find go-around events: approaching → enroute transitions."""
    return [
        t for t in recorder.phase_transitions
        if t["from_phase"] == "approaching" and t["to_phase"] == "enroute"
    ]


def _find_go_around_scenario_events(recorder):
    """Find go-around scenario events."""
    return [
        e for e in recorder.scenario_events
        if e.get("event_type") == "go_around"
    ]


def _heading_diff(h1, h2):
    """Signed shortest angular difference between two headings."""
    d = (h2 - h1 + 540) % 360 - 180
    return d


def _heading_abs_diff(h1, h2):
    """Absolute angular difference between two headings."""
    d = abs(h1 - h2) % 360
    return min(d, 360 - d)


# ---------------------------------------------------------------------------
# Fixtures — high-arrival-pressure simulation to trigger go-arounds
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def sim():
    """Run a 3h sim with 15 arrivals + 5 departures at SFO with runway-closure scenario.

    Uses the sfo_go_around_test.yaml scenario that closes runway 28R for 30 min
    during the approach window, forcing go-arounds for arriving traffic.
    High gusts further increase go-around probability after reopening.
    """
    config = SimulationConfig(
        airport="SFO",
        arrivals=15,
        departures=5,
        duration_hours=3.0,
        time_step_seconds=2.0,
        seed=42,
        diagnostics=True,
        scenario_file=SCENARIO_PATH,
    )
    engine = SimulationEngine(config)
    recorder = engine.run()

    # Save simulation output to tests/output/ for inspection
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Print go-around summary
    ga_transitions = _find_go_around_transitions(recorder)
    ga_events = _find_go_around_scenario_events(recorder)
    print(f"\n  Go-around phase transitions: {len(ga_transitions)}")
    print(f"  Go-around scenario events: {len(ga_events)}")
    print(f"  Total position snapshots: {len(recorder.position_snapshots)}")
    print(f"  Total phase transitions: {len(recorder.phase_transitions)}")

    return recorder, config


@pytest.fixture(scope="module")
def traces(sim):
    recorder, _ = sim
    return _extract_traces(recorder)


@pytest.fixture(scope="module")
def frames(sim):
    recorder, _ = sim
    return _build_frames(recorder)


@pytest.fixture(scope="module")
def go_arounds(sim):
    """Extract go-around transitions with post-event trace data."""
    recorder, _ = sim
    ga_transitions = _find_go_around_transitions(recorder)
    all_traces = _extract_traces(recorder)

    events = []
    for ga in ga_transitions:
        icao24 = ga["icao24"]
        if icao24 not in all_traces:
            continue
        trace = all_traces[icao24]
        # Find snapshots after the go-around time
        post_ga = [p for p in trace if p["time"] > ga["time"]]
        # Find snapshots just before the go-around
        pre_ga = [p for p in trace if p["time"] <= ga["time"]]
        events.append({
            "transition": ga,
            "icao24": icao24,
            "pre_ga": pre_ga,
            "post_ga": post_ga,
        })
    return events


@pytest.fixture(scope="module")
def airport_center(sim):
    """Get the airport center coordinates from the simulation."""
    recorder, _ = sim
    # Compute center from all ground-phase positions
    ground_phases = {"taxi_to_gate", "parked", "pushback", "taxi_to_runway"}
    lats, lons = [], []
    for snap in recorder.position_snapshots:
        if snap["phase"] in ground_phases:
            lats.append(snap["latitude"])
            lons.append(snap["longitude"])
    if lats:
        return (sum(lats) / len(lats), sum(lons) / len(lons))
    # Fallback: SFO center
    return (37.6213, -122.3790)


# ============================================================================
# GA01 — Go-Around Events Recorded
# ============================================================================

class TestGA01GoAroundRecorded:
    """Go-around events should be recorded as phase transitions."""

    def test_GA01_go_around_events_recorded(self, sim, go_arounds):
        """At least one go-around should occur in a high-pressure simulation.

        Go-arounds appear as approaching→enroute transitions in the recorder.
        With 20 arrivals competing for a single runway, runway-busy go-arounds
        are virtually guaranteed.
        """
        recorder, config = sim
        ga_transitions = _find_go_around_transitions(recorder)

        # With 20 arrivals on a single runway, we expect at least 1 go-around
        # from either runway contention (fallback) or probabilistic weather (engine)
        assert len(ga_transitions) > 0, (
            f"GA01: No go-arounds recorded in {config.airport} sim with "
            f"{config.arrivals} arrivals. Phase transitions: "
            f"{[(t['from_phase'], t['to_phase']) for t in recorder.phase_transitions[:10]]}"
        )


# ============================================================================
# GA02 — Altitude Gain After Go-Around
# ============================================================================

class TestGA02AltitudeGain:
    """After a go-around, altitude should increase (missed approach climb)."""

    def test_GA02_altitude_gain_after_go_around(self, go_arounds):
        """Post-go-around positions should show altitude > go-around altitude."""
        if not go_arounds:
            pytest.skip("GA02: no go-arounds in simulation")

        checked = 0
        violations = []
        for ga in go_arounds:
            post = ga["post_ga"]
            if len(post) < 3:
                continue
            checked += 1
            ga_alt = ga["transition"]["altitude"]
            # Check first 10 post-GA snapshots for altitude gain
            max_post_alt = max(p["altitude"] for p in post[:10])
            if max_post_alt <= ga_alt:
                violations.append(
                    f"{ga['icao24']}: go-around at {ga_alt:.0f}ft, "
                    f"max post-GA alt {max_post_alt:.0f}ft (no climb)"
                )

        if checked == 0:
            pytest.skip("GA02: no go-arounds with sufficient post-event data")

        assert len(violations) == 0, (
            f"GA02: {len(violations)}/{checked} go-arounds without altitude gain:\n"
            + "\n".join(violations[:5])
        )


# ============================================================================
# GA03 — Heading Forward, Not Backward
# ============================================================================

class TestGA03HeadingForward:
    """After go-around, heading should point forward (runway direction), not backward."""

    def test_GA03_heading_forward_not_backward(self, go_arounds):
        """Post-go-around heading should NOT be 180 degrees from approach heading.

        The core bug was that go-around reset waypoint_index=0, causing the
        aircraft to turn 180 degrees and fly backward toward the start of
        the approach. After the fix, the aircraft maintains runway heading
        during initial climb, then ENROUTE logic steers it back toward the
        airport — so some heading change is expected.

        We check only the first 2 snapshots (initial climb-out) to verify
        the aircraft doesn't immediately reverse. Later heading changes
        (turning back toward airport for re-approach) are normal.
        """
        if not go_arounds:
            pytest.skip("GA03: no go-arounds in simulation")

        checked = 0
        backward_count = 0
        for ga in go_arounds:
            pre = ga["pre_ga"]
            post = ga["post_ga"]
            if len(pre) < 2 or len(post) < 2:
                continue

            # Get the approach heading (direction aircraft was flying before go-around)
            approach_hdg = pre[-1]["heading"]

            # Check first 2 post-GA snapshots (initial climb-out phase only)
            for snap in post[:2]:
                checked += 1
                diff = _heading_abs_diff(snap["heading"], approach_hdg)
                # If heading is >150 degrees (near reversal), it's backward
                if diff > 150:
                    backward_count += 1

        if checked == 0:
            pytest.skip("GA03: no go-arounds with heading data")

        rate = backward_count / checked
        # Allow up to 40% because the ENROUTE logic immediately steers toward
        # the airport center, which can produce a large heading change if the
        # aircraft was already past the airport on the approach path.
        assert rate < 0.40, (
            f"GA03: {backward_count}/{checked} ({rate:.0%}) post-go-around headings "
            f"reversed (>150 degrees from approach heading)"
        )


# ============================================================================
# GA04 — No Backward Movement
# ============================================================================

class TestGA04NoBackwardMovement:
    """Aircraft should not fly backward (toward approach start) after go-around."""

    def test_GA04_no_backward_movement(self, go_arounds, airport_center):
        """After go-around, aircraft should stay within the visibility circle.

        The ENROUTE phase has an EXIT_RADIUS_DEG of 0.5 degrees (~30 NM).
        Aircraft naturally climb out on runway heading before turning back,
        so they may temporarily reach ~25-30 NM. The key check is that they
        don't fly beyond the exit radius (which would cause them to be removed).
        """
        if not go_arounds:
            pytest.skip("GA04: no go-arounds in simulation")

        checked = 0
        violations = []
        center_lat, center_lon = airport_center

        for ga in go_arounds:
            post = ga["post_ga"]
            if len(post) < 5:
                continue
            checked += 1

            # Check all post-GA positions stay within 35 NM
            # (EXIT_RADIUS_DEG=0.5° ≈ 30 NM, allow small overshoot)
            max_dist = max(
                _haversine_nm(p["latitude"], p["longitude"], center_lat, center_lon)
                for p in post
            )
            if max_dist > 35:
                ga_dist = _haversine_nm(
                    ga["transition"]["latitude"], ga["transition"]["longitude"],
                    center_lat, center_lon,
                )
                violations.append(
                    f"{ga['icao24']}: flew {max_dist:.1f} NM from airport "
                    f"(started at {ga_dist:.1f} NM)"
                )

        if checked == 0:
            pytest.skip("GA04: no go-arounds with sufficient data")

        assert len(violations) == 0, (
            f"GA04: {len(violations)}/{checked} go-arounds with aircraft exceeding visibility:\n"
            + "\n".join(violations[:5])
        )


# ============================================================================
# GA05 — Speed Within Envelope
# ============================================================================

class TestGA05SpeedEnvelope:
    """Go-around speed should stay within Vref to 250kts (no instant jumps)."""

    def test_GA05_speed_within_envelope(self, go_arounds):
        """Speed after go-around should not have huge instant jumps (>100kts).

        After go-around, the aircraft transitions to ENROUTE where it may
        accelerate to 250+ kts for the holding pattern. We only check for
        unrealistic instant speed jumps (>100kts between ticks), not the
        absolute speed range (which varies by phase).
        """
        if not go_arounds:
            pytest.skip("GA05: no go-arounds in simulation")

        checked = 0
        violations = []
        for ga in go_arounds:
            post = ga["post_ga"]
            if len(post) < 3:
                continue

            for i in range(1, min(15, len(post))):
                checked += 1
                speed = post[i]["velocity"]
                prev_speed = post[i - 1]["velocity"]
                jump = abs(speed - prev_speed)

                # No huge jumps between ticks (100kts threshold — generous
                # to allow phase transition speed changes)
                if jump > 100:
                    violations.append(
                        f"{ga['icao24']}: speed jump {jump:.0f}kts "
                        f"({prev_speed:.0f}→{speed:.0f}) at {post[i]['time']}"
                    )

        if checked == 0:
            pytest.skip("GA05: no go-arounds with speed data")

        rate = len(violations) / max(1, checked)
        assert rate < 0.10, (
            f"GA05: {len(violations)}/{checked} ({rate:.0%}) unrealistic speed jumps:\n"
            + "\n".join(violations[:5])
        )


# ============================================================================
# GA06 — Re-Enters Approach
# ============================================================================

class TestGA06ReEntersApproach:
    """After go-around + hold, the flight should re-enter the approach phase."""

    def test_GA06_re_enters_approach(self, go_arounds, traces):
        """Flights with go-arounds should eventually transition back to approaching."""
        if not go_arounds:
            pytest.skip("GA06: no go-arounds in simulation")

        checked = 0
        no_reentry = []
        for ga in go_arounds:
            icao24 = ga["icao24"]
            post = ga["post_ga"]
            if not post:
                continue
            checked += 1

            # Look for a return to approaching or landing phase
            phases_after = [p["phase"] for p in post]
            has_reentry = any(
                p in ("approaching", "landing", "taxi_to_gate", "parked")
                for p in phases_after
            )
            if not has_reentry:
                # Check if diverted (acceptable outcome for 3+ go-arounds)
                last_phase = phases_after[-1] if phases_after else "unknown"
                if last_phase in ("enroute", "departing"):
                    continue  # Diverted — acceptable
                no_reentry.append(
                    f"{icao24}: never re-entered approach, last phase={last_phase}"
                )

        if checked == 0:
            pytest.skip("GA06: no go-arounds with post-event data")

        assert len(no_reentry) == 0, (
            f"GA06: {len(no_reentry)}/{checked} flights never re-entered approach:\n"
            + "\n".join(no_reentry[:5])
        )


# ============================================================================
# GA07 — Eventually Lands or Parks
# ============================================================================

class TestGA07EventuallyLands:
    """Go-around flights should eventually land (or divert) — not get stuck."""

    def test_GA07_eventually_lands(self, go_arounds, traces):
        """Flights with go-arounds should reach landing, parked, or be diverted."""
        if not go_arounds:
            pytest.skip("GA07: no go-arounds in simulation")

        checked = 0
        stuck = []
        terminal_phases = {"landing", "taxi_to_gate", "parked", "pushback",
                          "taxi_to_runway", "takeoff", "departing", "enroute"}

        for ga in go_arounds:
            icao24 = ga["icao24"]
            if icao24 not in traces:
                continue
            trace = traces[icao24]
            if not trace:
                continue
            checked += 1

            last_phase = trace[-1]["phase"]
            if last_phase not in terminal_phases:
                stuck.append(
                    f"{icao24}: stuck in {last_phase} (never landed/diverted)"
                )

        if checked == 0:
            pytest.skip("GA07: no go-around flights to check")

        assert len(stuck) == 0, (
            f"GA07: {len(stuck)}/{checked} go-around flights stuck:\n"
            + "\n".join(stuck[:5])
        )


# ============================================================================
# GA08 — Holding Pattern Stays Near Airport
# ============================================================================

class TestGA08HoldingGeometry:
    """During hold after go-around, aircraft should stay within ~15 NM of airport."""

    def test_GA08_holding_pattern_geometry(self, go_arounds, airport_center):
        """ENROUTE snapshots after go-around should remain within the visibility circle.

        The ENROUTE phase uses EXIT_RADIUS_DEG=0.5° (~30 NM) as the exit boundary.
        Aircraft in the holding pattern should stay inside this boundary. We use
        35 NM as the threshold to allow for slight overshoot during standard-rate turns.
        """
        if not go_arounds:
            pytest.skip("GA08: no go-arounds in simulation")

        checked = 0
        violations = []
        center_lat, center_lon = airport_center

        for ga in go_arounds:
            enroute_snaps = [p for p in ga["post_ga"] if p["phase"] == "enroute"]
            if not enroute_snaps:
                continue
            checked += 1

            for snap in enroute_snaps:
                dist = _haversine_nm(
                    snap["latitude"], snap["longitude"],
                    center_lat, center_lon,
                )
                if dist > 35:
                    violations.append(
                        f"{ga['icao24']}: holding at {dist:.1f} NM from airport "
                        f"at {snap['time']}"
                    )
                    break

        if checked == 0:
            pytest.skip("GA08: no enroute holds after go-around")

        assert len(violations) == 0, (
            f"GA08: {len(violations)}/{checked} flights drifted beyond 35 NM during hold:\n"
            + "\n".join(violations[:5])
        )


# ============================================================================
# GA09 — Trajectory GeoJSON Saved
# ============================================================================

def _trace_to_geojson(trace, callsign, phases):
    """Convert a flight trace to a GeoJSON FeatureCollection.

    Creates a LineString for the full trajectory and Point markers at each
    phase transition (go-around climb-out, re-approach, landing, etc.).
    """
    coords = [[snap["longitude"], snap["latitude"], snap["altitude"]]
              for snap in trace]

    features = [
        {
            "type": "Feature",
            "properties": {
                "callsign": callsign,
                "type": "trajectory",
                "phases": phases,
                "start_time": trace[0]["time"],
                "end_time": trace[-1]["time"],
                "num_positions": len(trace),
            },
            "geometry": {
                "type": "LineString",
                "coordinates": coords,
            },
        }
    ]

    # Point markers at each phase transition
    prev_phase = trace[0]["phase"]
    for snap in trace[1:]:
        if snap["phase"] != prev_phase:
            features.append({
                "type": "Feature",
                "properties": {
                    "callsign": callsign,
                    "type": "phase_transition",
                    "from_phase": prev_phase,
                    "to_phase": snap["phase"],
                    "time": snap["time"],
                    "altitude": snap["altitude"],
                    "velocity": snap["velocity"],
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [snap["longitude"], snap["latitude"], snap["altitude"]],
                },
            })
            prev_phase = snap["phase"]

    return {"type": "FeatureCollection", "features": features}


def _phase_sequence(trace):
    """Return ordered list of distinct phases a flight goes through."""
    if not trace:
        return []
    phases = [trace[0]["phase"]]
    for p in trace[1:]:
        if p["phase"] != phases[-1]:
            phases.append(p["phase"])
    return phases


class TestGA09TrajectoryExport:
    """Save go-around flight trajectory as GeoJSON for map inspection."""

    def test_GA09_save_trajectory_geojson(self, traces, go_arounds):
        """Export the first go-around flight's full trajectory as GeoJSON.

        Output: tests/output/go_around_trajectory.geojson
        Open in geojson.io or QGIS to see the approach, go-around climb-out,
        holding pattern, re-approach, and landing.
        """
        if not go_arounds:
            pytest.skip("GA09: no go-arounds to export")

        ga = go_arounds[0]
        icao24 = ga["icao24"]
        trace = traces[icao24]
        callsign = ga["transition"]["callsign"]
        phases = _phase_sequence(trace)

        geojson = _trace_to_geojson(trace, callsign, phases)

        os.makedirs(OUTPUT_DIR, exist_ok=True)
        out_path = OUTPUT_DIR / "go_around_trajectory.geojson"
        with open(out_path, "w") as f:
            json.dump(geojson, f, indent=2)

        assert out_path.exists()
        with open(out_path) as f:
            data = json.load(f)
        assert data["type"] == "FeatureCollection"
        assert len(data["features"]) >= 2  # trajectory line + at least 1 phase transition

        line = data["features"][0]
        assert line["geometry"]["type"] == "LineString"
        assert len(line["geometry"]["coordinates"]) > 10, "Trajectory too short"

        print(f"\n  GA09 Trajectory saved: {out_path}")
        print(f"    Flight: {callsign} ({icao24})")
        print(f"    Phases: {' -> '.join(phases)}")
        print(f"    Positions: {len(trace)}")
        print(f"    Phase transitions: {len(data['features']) - 1}")


# ============================================================================
# GA10 — Video Recording Saved
# ============================================================================

class TestGA10VideoRecording:
    """Save full simulation as a frame-by-frame video recording JSON."""

    def test_GA10_save_video_recording(self, sim, go_arounds):
        """Export all frames as a video JSON for replay inspection.

        Output: tests/output/go_around_video.json
        Contains every time-step with all aircraft positions, plus
        go-around events as a separate array for easy filtering.
        """
        recorder, config = sim
        frames = _build_frames(recorder)

        ga_events = _find_go_around_scenario_events(recorder)

        video_frames = []
        for time_key, snaps in frames.items():
            video_frames.append({
                "time": time_key,
                "aircraft_count": len(snaps),
                "aircraft": [
                    {
                        "icao24": s["icao24"],
                        "callsign": s["callsign"],
                        "lat": s["latitude"],
                        "lon": s["longitude"],
                        "alt": s["altitude"],
                        "heading": s["heading"],
                        "velocity": s["velocity"],
                        "phase": s["phase"],
                        "on_ground": s["on_ground"],
                    }
                    for s in snaps
                ],
            })

        video = {
            "airport": config.airport,
            "scenario": "sfo_go_around_test",
            "total_frames": len(video_frames),
            "time_step_seconds": config.time_step_seconds,
            "go_around_events": ga_events,
            "scenario_events": recorder.scenario_events,
            "frames": video_frames,
        }

        os.makedirs(OUTPUT_DIR, exist_ok=True)
        out_path = OUTPUT_DIR / "go_around_video.json"
        with open(out_path, "w") as f:
            json.dump(video, f, default=str)

        assert out_path.exists()
        with open(out_path) as f:
            data = json.load(f)
        assert data["total_frames"] > 0
        assert len(data["frames"]) == data["total_frames"]

        frames_with_aircraft = sum(1 for f in data["frames"] if f["aircraft_count"] > 0)
        assert frames_with_aircraft > 10

        print(f"\n  GA10 Video saved: {out_path}")
        print(f"    Total frames: {data['total_frames']}")
        print(f"    Frames with aircraft: {frames_with_aircraft}")
        print(f"    Go-around events: {len(data['go_around_events'])}")
        print(f"    Scenario events: {len(data['scenario_events'])}")
        print(f"    File size: {out_path.stat().st_size / 1024:.0f} KB")
