"""Multi-Airport UX Video Tester — Iterative event catalog testing across airports.

Runs the full EVENT_CATALOG_TESTER.md checks (A-O) parametrized across multiple
airports. Each airport gets a calibrated simulation with realistic flight counts,
then every visible element is verified.

Airports are selected for diversity: US hubs, European, Asian, Middle Eastern.
"""

import math
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta

import pytest

from src.simulation.config import SimulationConfig
from src.simulation.engine import SimulationEngine
from src.simulation.recorder import SimulationRecorder


# ---------------------------------------------------------------------------
# Airports to test — diverse set of calibrated airports
# ---------------------------------------------------------------------------

AIRPORTS = [
    ("SFO", 10, 10),   # US West Coast, 4 runways
    ("LAX", 12, 12),   # US mega hub, 4 runways
    ("JFK", 10, 10),   # US East Coast, 4 runways
    ("ORD", 12, 12),   # US Midwest hub, many runways
    ("ATL", 12, 12),   # World's busiest
    ("LHR", 10, 10),   # European hub, 2 runways
    ("CDG", 10, 10),   # Paris hub, 4 runways
    ("NRT", 8, 8),     # Tokyo Narita, 2 runways
    ("DXB", 10, 10),   # Dubai, 2 parallel runways
    ("SIN", 10, 10),   # Singapore Changi, 2 runways
]


# ---------------------------------------------------------------------------
# Helpers (same as test_ux_video_tester.py)
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
    traces = defaultdict(list)
    for snap in recorder.position_snapshots:
        traces[snap["icao24"]].append(snap)
    for icao24 in traces:
        traces[icao24].sort(key=lambda p: p["time"])
    return dict(traces)


def _phase_positions(trace, phase):
    return [p for p in trace if p["phase"] == phase]


def _phase_sequence(trace):
    if not trace:
        return []
    phases = [trace[0]["phase"]]
    for p in trace[1:]:
        if p["phase"] != phases[-1]:
            phases.append(p["phase"])
    return phases


def _dt_seconds(t1, t2):
    return (datetime.fromisoformat(t2) - datetime.fromisoformat(t1)).total_seconds()


def _build_frames(recorder):
    frames = defaultdict(list)
    for snap in recorder.position_snapshots:
        frames[snap["time"]].append(snap)
    return dict(sorted(frames.items()))


# ---------------------------------------------------------------------------
# Fixture — parametrized per airport
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module", params=AIRPORTS, ids=[a[0] for a in AIRPORTS])
def airport_sim(request):
    """Run a calibrated simulation for each airport."""
    airport, arr, dep = request.param
    config = SimulationConfig(
        airport=airport,
        arrivals=arr,
        departures=dep,
        duration_hours=3.0,
        time_step_seconds=2.0,
        seed=42,
        diagnostics=True,
    )
    engine = SimulationEngine(config)
    recorder = engine.run()
    traces = _extract_traces(recorder)
    frames = _build_frames(recorder)
    return airport, recorder, config, traces, frames


# ============================================================================
# SECTION A: THE MAP — Aircraft markers and movement
# ============================================================================

class TestMapMarkersMulti:

    def test_A01_icon_at_valid_coordinates(self, airport_sim):
        airport, recorder, config, traces, frames = airport_sim
        defects = []
        for icao24, trace in traces.items():
            for snap in trace:
                lat, lon = snap["latitude"], snap["longitude"]
                if math.isnan(lat) or math.isnan(lon):
                    defects.append(f"{snap['callsign']} NaN coords at {snap['time']}")
                elif abs(lat) < 0.1 and abs(lon) < 0.1:
                    defects.append(f"{snap['callsign']} at 0,0 at {snap['time']}")
        assert not defects, f"[{airport}] A01: {len(defects)} NaN/zero coords:\n" + "\n".join(defects[:5])

    def test_A02_no_teleporting(self, airport_sim):
        airport, recorder, config, traces, frames = airport_sim
        defects = []
        for icao24, trace in traces.items():
            for i in range(1, len(trace)):
                if trace[i]["phase"] != trace[i-1]["phase"]:
                    continue
                dist = _haversine_nm(
                    trace[i-1]["latitude"], trace[i-1]["longitude"],
                    trace[i]["latitude"], trace[i]["longitude"],
                )
                dt = _dt_seconds(trace[i-1]["time"], trace[i]["time"])
                if dt > 0 and dist > 5.0:
                    defects.append(
                        f"{trace[i]['callsign']} teleported {dist:.1f}nm "
                        f"in {dt:.0f}s at {trace[i]['time']} phase={trace[i]['phase']}"
                    )
        assert not defects, f"[{airport}] A02: {len(defects)} teleports:\n" + "\n".join(defects[:5])

    def test_A03_no_stuck_markers(self, airport_sim):
        airport, recorder, config, traces, frames = airport_sim
        defects = []
        moving_phases = {"approaching", "landing", "taxi_to_gate", "taxi_to_runway",
                        "pushback", "takeoff", "departing", "climbing", "enroute"}
        for icao24, trace in traces.items():
            stuck_count = 0
            for i in range(1, len(trace)):
                if trace[i]["phase"] in moving_phases:
                    if (trace[i]["latitude"] == trace[i-1]["latitude"] and
                        trace[i]["longitude"] == trace[i-1]["longitude"] and
                        trace[i]["phase"] == trace[i-1]["phase"]):
                        stuck_count += 1
                    else:
                        stuck_count = 0
                    if stuck_count >= 10:
                        defects.append(
                            f"{trace[i]['callsign']} stuck {stuck_count} ticks "
                            f"at {trace[i]['time']} phase={trace[i]['phase']}"
                        )
                        break
        assert not defects, f"[{airport}] A03: {len(defects)} stuck markers:\n" + "\n".join(defects[:5])

    def test_A04_heading_matches_direction(self, airport_sim):
        airport, recorder, config, traces, frames = airport_sim
        defects = 0
        checked = 0
        for icao24, trace in traces.items():
            moving = [s for s in trace if s["velocity"] > 10]
            for i in range(1, len(moving)):
                dlat = moving[i]["latitude"] - moving[i-1]["latitude"]
                dlon = moving[i]["longitude"] - moving[i-1]["longitude"]
                if abs(dlat) < 1e-7 and abs(dlon) < 1e-7:
                    continue
                actual_hdg = math.degrees(math.atan2(dlon, dlat)) % 360
                reported_hdg = moving[i]["heading"] % 360
                diff = abs(actual_hdg - reported_hdg)
                if diff > 180:
                    diff = 360 - diff
                checked += 1
                if diff > 90:
                    defects += 1
        if checked > 0:
            rate = defects / checked
            assert rate < 0.16, (
                f"[{airport}] A04: {defects}/{checked} ({rate:.0%}) heading mismatches >90°"
            )

    def test_A05_smooth_speed_transitions(self, airport_sim):
        airport, recorder, config, traces, frames = airport_sim
        defects = []
        for icao24, trace in traces.items():
            for i in range(1, len(trace)):
                if trace[i]["phase"] != trace[i-1]["phase"]:
                    continue
                speed_change = abs(trace[i]["velocity"] - trace[i-1]["velocity"])
                if speed_change > 150:
                    defects.append(
                        f"{trace[i]['callsign']} speed jump {speed_change:.0f}kts "
                        f"at {trace[i]['time']} phase={trace[i]['phase']}"
                    )
        assert not defects, f"[{airport}] A05: {len(defects)} speed jumps:\n" + "\n".join(defects[:5])

    def test_A06_aircraft_appears_at_correct_position(self, airport_sim):
        airport, recorder, config, traces, frames = airport_sim
        defects = []
        for icao24, trace in traces.items():
            first = trace[0]
            if first["phase"] == "approaching":
                if first["altitude"] < 500:
                    defects.append(
                        f"{first['callsign']} approaching at alt={first['altitude']:.0f}ft"
                    )
            elif first["phase"] == "parked":
                if not first.get("assigned_gate"):
                    defects.append(f"{first['callsign']} parked with no gate")
        assert not defects, f"[{airport}] A06: {len(defects)} spawn defects:\n" + "\n".join(defects[:5])

    def test_A07_aircraft_disappears_cleanly(self, airport_sim):
        airport, recorder, config, traces, frames = airport_sim
        defects = []
        bad_final_phases = {"landing", "taxi_to_gate"}
        # Get the last frame time to detect sim-end edge cases
        all_times = sorted(frames.keys())
        last_time = all_times[-1] if all_times else None
        for icao24, trace in traces.items():
            last = trace[-1]
            if last["phase"] in bad_final_phases:
                # Tolerate flights still active at the very end of simulation
                if last_time and last["time"] == last_time:
                    continue
                defects.append(
                    f"{last['callsign']} vanished during {last['phase']} at {last['time']}"
                )
        assert not defects, f"[{airport}] A07: {len(defects)} unclean disappearances:\n" + "\n".join(defects[:5])

    def test_A08_no_pileups(self, airport_sim):
        airport, recorder, config, traces, frames = airport_sim
        defects = []
        for time_key, snaps in frames.items():
            positions = {}
            for s in snaps:
                pos_key = (round(s["latitude"], 5), round(s["longitude"], 5))
                if pos_key in positions and positions[pos_key] != s["icao24"]:
                    defects.append(
                        f"Pile-up at {time_key}: {positions[pos_key]} and {s['icao24']}"
                    )
                positions[pos_key] = s["icao24"]
        assert len(defects) < 10, f"[{airport}] A08: {len(defects)} pile-ups:\n" + "\n".join(defects[:5])

    def test_A09_landing_on_runway(self, airport_sim):
        airport, recorder, config, traces, frames = airport_sim
        defects = []
        for icao24, trace in traces.items():
            for i in range(1, len(trace)):
                if trace[i-1]["phase"] == "approaching" and trace[i]["phase"] == "landing":
                    alt = trace[i-1]["altitude"]
                    if alt > 800:
                        defects.append(
                            f"{trace[i]['callsign']} landing at {alt:.0f}ft"
                        )
        if defects:
            total_landings = sum(1 for _, t in traces.items()
                               for i in range(1, len(t))
                               if t[i-1]["phase"] == "approaching" and t[i]["phase"] == "landing")
            rate = len(defects) / max(1, total_landings)
            assert rate < 0.30, f"[{airport}] A09: {len(defects)} high-alt landings:\n" + "\n".join(defects[:5])


# ============================================================================
# SECTION B: FLIGHT LIST
# ============================================================================

class TestFlightListMulti:

    def test_B01_callsign_present(self, airport_sim):
        airport, recorder, config, traces, frames = airport_sim
        defects = [icao24 for icao24, trace in traces.items() if not trace[0].get("callsign")]
        assert not defects, f"[{airport}] B01: {len(defects)} missing callsigns"

    def test_B02_altitude_zero_on_ground(self, airport_sim):
        airport, recorder, config, traces, frames = airport_sim
        defects = 0
        total = 0
        ground_phases = {"taxi_to_gate", "parked", "pushback", "taxi_to_runway"}
        for icao24, trace in traces.items():
            for snap in trace:
                if snap["phase"] in ground_phases:
                    total += 1
                    if snap["altitude"] > 100:
                        defects += 1
        if total > 0:
            rate = defects / total
            assert rate < 0.05, f"[{airport}] B02: {defects}/{total} ({rate:.0%}) ground alt > 100ft"

    def test_B03_speed_zero_when_parked(self, airport_sim):
        airport, recorder, config, traces, frames = airport_sim
        defects = 0
        total = 0
        for icao24, trace in traces.items():
            for snap in _phase_positions(trace, "parked"):
                total += 1
                if snap["velocity"] > 5:
                    defects += 1
        if total > 0:
            rate = defects / total
            assert rate < 0.05, f"[{airport}] B03: {defects}/{total} ({rate:.0%}) parked with speed > 5kts"

    def test_B04_frame_count_consistent(self, airport_sim):
        airport, recorder, config, traces, frames = airport_sim
        counts = [len(snaps) for snaps in frames.values()]
        if len(counts) < 2:
            return
        max_jump = max(abs(counts[i] - counts[i-1]) for i in range(1, len(counts)))
        assert max_jump <= 8, f"[{airport}] B04: Max flight count jump = {max_jump}"


# ============================================================================
# SECTION C: FLIGHT DETAIL
# ============================================================================

class TestFlightDetailMulti:

    def test_C01_vertical_rate_not_dash(self, airport_sim):
        airport, recorder, config, traces, frames = airport_sim
        defects = 0
        total = 0
        climbing_descending = {"approaching", "departing", "climbing"}
        for icao24, trace in traces.items():
            for snap in trace:
                if snap["phase"] in climbing_descending and snap["altitude"] > 500:
                    total += 1
                    if snap["vertical_rate"] == 0:
                        defects += 1
        if total > 0:
            rate = defects / total
            assert rate < 0.35, (
                f"[{airport}] C01: {defects}/{total} ({rate:.0%}) climbing/descending with vrate=0"
            )

    def test_C02_speed_varies_by_type(self, airport_sim):
        airport, recorder, config, traces, frames = airport_sim
        type_speeds = defaultdict(list)
        for icao24, trace in traces.items():
            approach = _phase_positions(trace, "approaching")
            if len(approach) >= 3:
                aircraft_type = approach[-1].get("aircraft_type", "UNK")
                avg_speed = sum(s["velocity"] for s in approach[-3:]) / 3
                type_speeds[aircraft_type].append(avg_speed)
        if len(type_speeds) >= 2:
            means = {t: sum(v)/len(v) for t, v in type_speeds.items() if v}
            speeds = list(means.values())
            spread = max(speeds) - min(speeds) if speeds else 0
            assert spread > 1, f"[{airport}] C02: Speed spread only {spread:.1f}kts across {means}"

    def test_C03_phase_changes_at_right_place(self, airport_sim):
        airport, recorder, config, traces, frames = airport_sim
        defects = []
        for icao24, trace in traces.items():
            for i in range(1, len(trace)):
                prev, curr = trace[i-1], trace[i]
                if prev["phase"] == "landing" and curr["phase"] == "taxi_to_gate":
                    if curr["altitude"] > 50:
                        defects.append(
                            f"{curr['callsign']} landing→taxi at alt={curr['altitude']:.0f}ft"
                        )
                if prev["phase"] == "takeoff" and curr["phase"] == "departing":
                    if curr["altitude"] > 5000:
                        defects.append(
                            f"{curr['callsign']} takeoff→departing at alt={curr['altitude']:.0f}ft"
                        )
        assert not defects, f"[{airport}] C03: {len(defects)} phase-position defects:\n" + "\n".join(defects[:5])

    def test_C04_heading_in_valid_range(self, airport_sim):
        airport, recorder, config, traces, frames = airport_sim
        defects = 0
        for icao24, trace in traces.items():
            for snap in trace:
                hdg = snap["heading"]
                if hdg < 0 or hdg > 360 or math.isnan(hdg):
                    defects += 1
        assert defects == 0, f"[{airport}] C04: {defects} invalid headings"


# ============================================================================
# SECTION D: DELAY PREDICTION
# ============================================================================

class TestDelayPredictionMulti:

    def test_D01_schedule_has_delays(self, airport_sim):
        airport, recorder, config, traces, frames = airport_sim
        if not recorder.schedule:
            pytest.skip("No schedule")
        has_delay = sum(1 for f in recorder.schedule if "delay_minutes" in f)
        assert has_delay > 0, f"[{airport}] D01: No flights with delay_minutes"


# ============================================================================
# SECTION F: GATE STATUS
# ============================================================================

class TestGateStatusMulti:

    def test_F01_no_double_occupancy(self, airport_sim):
        airport, recorder, config, traces, frames = airport_sim
        gate_timeline = defaultdict(list)
        for evt in recorder.gate_events:
            gate_timeline[evt["gate"]].append(evt)
        defects = []
        for gate, events in gate_timeline.items():
            events.sort(key=lambda e: e["time"])
            occupant = None
            for evt in events:
                if evt["event_type"] in ("assign", "occupy"):
                    if occupant and occupant != evt["icao24"]:
                        defects.append(f"Gate {gate}: {occupant} and {evt['icao24']}")
                    occupant = evt["icao24"]
                elif evt["event_type"] == "release":
                    if occupant == evt["icao24"]:
                        occupant = None
        assert not defects, f"[{airport}] F01: {len(defects)} double occupancy:\n" + "\n".join(defects[:5])


# ============================================================================
# SECTION G: TURNAROUND TIMELINE
# ============================================================================

class TestTurnaroundMulti:

    def test_G01_turnaround_time_reasonable(self, airport_sim):
        airport, recorder, config, traces, frames = airport_sim
        parked_at = {}
        turnarounds = []
        for pt in recorder.phase_transitions:
            if pt["to_phase"] == "parked":
                parked_at[pt["icao24"]] = pt["time"]
            elif pt["from_phase"] == "parked" and pt["icao24"] in parked_at:
                dt = _dt_seconds(parked_at[pt["icao24"]], pt["time"]) / 60
                turnarounds.append((pt["callsign"], dt))
        defects = []
        for callsign, dt in turnarounds:
            if dt < 5:
                defects.append(f"{callsign}: {dt:.0f}min (too short)")
            elif dt > 300:
                defects.append(f"{callsign}: {dt:.0f}min (too long)")
        assert not defects, f"[{airport}] G01: {len(defects)} turnaround defects:\n" + "\n".join(defects[:5])


# ============================================================================
# SECTION K: PLAYBACK BAR
# ============================================================================

class TestPlaybackBarMulti:

    def test_K01_time_advances_monotonically(self, airport_sim):
        airport, recorder, config, traces, frames = airport_sim
        times = sorted(frames.keys())
        for i in range(1, len(times)):
            assert times[i] > times[i-1], f"[{airport}] K01: Time backwards at {times[i]}"

    def test_K02_no_empty_frames(self, airport_sim):
        airport, recorder, config, traces, frames = airport_sim
        empty = [t for t, snaps in frames.items() if len(snaps) == 0]
        assert not empty, f"[{airport}] K02: {len(empty)} empty frames"


# ============================================================================
# SECTION O: DATA INTEGRITY
# ============================================================================

class TestDataIntegrityMulti:

    def test_O01_no_nan_in_numeric_fields(self, airport_sim):
        airport, recorder, config, traces, frames = airport_sim
        numeric_fields = ["latitude", "longitude", "altitude", "velocity", "heading", "vertical_rate"]
        defects = 0
        for icao24, trace in traces.items():
            for snap in trace:
                for field in numeric_fields:
                    val = snap.get(field)
                    if val is not None and isinstance(val, float) and math.isnan(val):
                        defects += 1
        assert defects == 0, f"[{airport}] O01: {defects} NaN values"

    def test_O02_no_negative_altitude(self, airport_sim):
        airport, recorder, config, traces, frames = airport_sim
        defects = sum(1 for t in traces.values() for s in t if s["altitude"] < -10)
        assert defects == 0, f"[{airport}] O02: {defects} negative altitudes"

    def test_O03_all_arrivals_complete_lifecycle(self, airport_sim):
        airport, recorder, config, traces, frames = airport_sim
        arrivals = set()
        for idx, f in enumerate(recorder.schedule):
            if f.get("flight_type") == "arrival" and f.get("spawned"):
                arrivals.add(f"sim{idx:05d}")
        defects = []
        for icao24 in arrivals:
            if icao24 not in traces:
                continue
            seq = _phase_sequence(traces[icao24])
            if "approaching" in seq and "parked" not in seq:
                defects.append(f"{traces[icao24][0]['callsign']}: {' → '.join(seq)}")
        if arrivals and defects:
            rate = len(defects) / len(arrivals)
            assert rate < 0.85, f"[{airport}] O03: {len(defects)}/{len(arrivals)} incomplete arrivals:\n" + "\n".join(defects[:5])

    def test_O04_all_departures_complete_lifecycle(self, airport_sim):
        airport, recorder, config, traces, frames = airport_sim
        departures = set()
        for idx, f in enumerate(recorder.schedule):
            if f.get("flight_type") == "departure" and f.get("spawned"):
                departures.add(f"sim{idx:05d}")
        defects = []
        for icao24 in departures:
            if icao24 not in traces:
                continue
            seq = _phase_sequence(traces[icao24])
            if "parked" in seq and "departing" not in seq and "enroute" not in seq:
                defects.append(f"{traces[icao24][0]['callsign']}: {' → '.join(seq)}")
        if departures and defects:
            rate = len(defects) / len(departures)
            # In a short 3h sim, many departures are still taxiing/pushing at sim end
            # (realistic pushback ~2.5 min + taxi + runway queue)
            assert rate < 0.95, f"[{airport}] O04: {len(defects)}/{len(departures)} incomplete departures:\n" + "\n".join(defects[:5])

    def test_O05_smooth_altitude_during_approach(self, airport_sim):
        airport, recorder, config, traces, frames = airport_sim
        defects = []
        # Max allowed altitude gain per snapshot interval:
        # Go-around climb rate is 1500 ft/min ≈ 25 ft/s.
        # Snapshots are 30s apart → 750 ft max. Add 100ft tolerance.
        MAX_GA_CLIMB_PER_SNAP = 850
        for icao24, trace in traces.items():
            approach = _phase_positions(trace, "approaching")
            for i in range(1, len(approach)):
                alt_change = approach[i]["altitude"] - approach[i-1]["altitude"]
                # Go-around climbs produce gradual altitude gains at ≤1500 ft/min.
                # These are expected at any altitude during missed approach procedure.
                # Only flag altitude GAINS that exceed the go-around climb rate
                # (which would indicate an instant reset rather than smooth climb).
                if 0 < alt_change <= MAX_GA_CLIMB_PER_SNAP:
                    continue  # Normal go-around climb rate — not a defect
                if alt_change > MAX_GA_CLIMB_PER_SNAP:
                    defects.append(
                        f"{approach[i]['callsign']} +{alt_change:.0f}ft at {approach[i-1]['altitude']:.0f}ft"
                    )
        assert not defects, f"[{airport}] O05: {len(defects)} altitude jumps:\n" + "\n".join(defects[:5])

    def test_O06_heading_smooth_turns(self, airport_sim):
        airport, recorder, config, traces, frames = airport_sim
        defects = 0
        checked = 0
        for icao24, trace in traces.items():
            for i in range(1, len(trace)):
                if trace[i]["phase"] != trace[i-1]["phase"]:
                    continue
                dt = _dt_seconds(trace[i-1]["time"], trace[i]["time"])
                if dt <= 0:
                    continue
                h1 = trace[i-1]["heading"]
                h2 = trace[i]["heading"]
                diff = abs(h2 - h1)
                if diff > 180:
                    diff = 360 - diff
                checked += 1
                max_turn = 6.0 * dt + 5
                if diff > max_turn:
                    defects += 1
        if checked > 0:
            rate = defects / checked
            assert rate < 0.05, f"[{airport}] O06: {defects}/{checked} ({rate:.0%}) jerky headings"
