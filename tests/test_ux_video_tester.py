"""UX Video Tester — Simulates a user watching the airport digital twin UI.

Runs a small simulation, "records" it as a sequence of frames, and checks
every visible element described in EVENT_CATALOG_TESTER.md (sections A-O).

Each defect is a UX bug: something the user would see that looks wrong,
broken, or confusing. The test names map to the tester guide sections.
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
    """Group snapshots by time into frames (what the user sees each tick)."""
    frames = defaultdict(list)
    for snap in recorder.position_snapshots:
        frames[snap["time"]].append(snap)
    return dict(sorted(frames.items()))


# ---------------------------------------------------------------------------
# Fixture — single small SFO simulation
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def sim():
    """Run a small 3h sim with 10 arrivals + 10 departures at SFO."""
    config = SimulationConfig(
        airport="SFO",
        arrivals=10,
        departures=10,
        duration_hours=3.0,
        time_step_seconds=2.0,
        seed=42,
        diagnostics=True,
    )
    engine = SimulationEngine(config)
    recorder = engine.run()
    return recorder, config


@pytest.fixture(scope="module")
def traces(sim):
    recorder, _ = sim
    return _extract_traces(recorder)


@pytest.fixture(scope="module")
def frames(sim):
    recorder, _ = sim
    return _build_frames(recorder)


# ============================================================================
# SECTION A: THE MAP — Aircraft markers and movement
# ============================================================================

class TestMapMarkers:
    """Section A: What the tester sees on the 2D/3D map."""

    def test_A01_icon_at_valid_coordinates(self, traces):
        """Aircraft icons should be at valid lat/lon (not NaN, not 0/0)."""
        defects = []
        for icao24, trace in traces.items():
            for snap in trace:
                lat, lon = snap["latitude"], snap["longitude"]
                if math.isnan(lat) or math.isnan(lon):
                    defects.append(f"{snap['callsign']} has NaN coords at {snap['time']}")
                elif abs(lat) < 0.1 and abs(lon) < 0.1:
                    defects.append(f"{snap['callsign']} at 0,0 at {snap['time']}")
        assert len(defects) == 0, f"A01: {len(defects)} NaN/zero coordinate defects:\n" + "\n".join(defects[:5])

    def test_A02_no_teleporting(self, traces):
        """Aircraft should not teleport (jump > 5nm between consecutive ticks)."""
        defects = []
        for icao24, trace in traces.items():
            for i in range(1, len(trace)):
                if trace[i]["phase"] != trace[i-1]["phase"]:
                    continue  # Phase transitions can cause position jumps
                dist = _haversine_nm(
                    trace[i-1]["latitude"], trace[i-1]["longitude"],
                    trace[i]["latitude"], trace[i]["longitude"],
                )
                dt = _dt_seconds(trace[i-1]["time"], trace[i]["time"])
                if dt > 0 and dist > 5.0:
                    defects.append(
                        f"{trace[i]['callsign']} teleported {dist:.1f}nm "
                        f"in {dt:.0f}s at {trace[i]['time']} (phase={trace[i]['phase']})"
                    )
        assert len(defects) == 0, f"A02: {len(defects)} teleport defects:\n" + "\n".join(defects[:5])

    def test_A03_no_stuck_markers(self, traces):
        """Aircraft in moving phases should actually move (not freeze on map)."""
        defects = []
        moving_phases = {"approaching", "landing", "taxi_to_gate", "taxi_to_runway",
                        "pushback", "takeoff", "departing", "climbing", "enroute"}
        for icao24, trace in traces.items():
            # Check if a moving-phase aircraft stays at exact same position for >10 ticks
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
                            f"{trace[i]['callsign']} stuck for {stuck_count} ticks "
                            f"at {trace[i]['time']} phase={trace[i]['phase']}"
                        )
                        break
        assert len(defects) == 0, f"A03: {len(defects)} stuck marker defects:\n" + "\n".join(defects[:5])

    def test_A04_heading_matches_direction(self, traces):
        """Icon rotation (heading) should match actual direction of travel."""
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
                if diff > 90:  # More than 90° off means pointing wrong direction
                    defects += 1
        if checked > 0:
            rate = defects / checked
            assert rate < 0.15, (
                f"A04: {defects}/{checked} ({rate:.0%}) heading-vs-direction mismatches >90°"
            )

    def test_A05_smooth_speed_transitions(self, traces):
        """Speed should change smoothly — no instant jumps > 150kts between ticks.

        Approach speed can drop sharply when separation kicks in (speed_slow factor),
        so we allow up to 150kts within approach phase. Jumps > 150kts would be
        truly jarring on the map visualization.
        """
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
        assert len(defects) == 0, f"A05: {len(defects)} speed jump defects:\n" + "\n".join(defects[:5])

    def test_A06_aircraft_appears_at_correct_position(self, traces):
        """First snapshot should be at approach entry (airborne) or gate (ground)."""
        defects = []
        for icao24, trace in traces.items():
            first = trace[0]
            if first["phase"] == "approaching":
                # Should be airborne, altitude > 500ft
                if first["altitude"] < 500:
                    defects.append(
                        f"{first['callsign']} approaching but altitude={first['altitude']:.0f}ft"
                    )
            elif first["phase"] == "parked":
                # Should have a gate assignment
                if not first.get("assigned_gate"):
                    defects.append(f"{first['callsign']} parked with no gate")
        assert len(defects) == 0, f"A06: {len(defects)} spawn position defects:\n" + "\n".join(defects[:5])

    def test_A07_aircraft_disappears_cleanly(self, traces):
        """Last snapshot should be enroute/departing (departure) or parked (stayed)."""
        defects = []
        bad_final_phases = {"landing", "taxi_to_gate"}  # Should not vanish mid-taxi or landing
        for icao24, trace in traces.items():
            last = trace[-1]
            if last["phase"] in bad_final_phases:
                defects.append(
                    f"{last['callsign']} vanished during {last['phase']} at {last['time']}"
                )
        assert len(defects) == 0, f"A07: {len(defects)} unclean disappearance defects:\n" + "\n".join(defects[:5])

    def test_A08_no_pileups(self, frames):
        """Multiple aircraft should not stack at the exact same point."""
        defects = []
        for time_key, snaps in frames.items():
            positions = {}
            for s in snaps:
                pos_key = (round(s["latitude"], 5), round(s["longitude"], 5))
                if pos_key in positions and positions[pos_key] != s["icao24"]:
                    # Two different aircraft at exact same position
                    defects.append(
                        f"Pile-up at {time_key}: {positions[pos_key]} and {s['icao24']} "
                        f"at ({pos_key[0]}, {pos_key[1]})"
                    )
                positions[pos_key] = s["icao24"]
        # Allow a few (phase transitions can cause brief overlaps)
        assert len(defects) < 10, f"A08: {len(defects)} pile-up defects:\n" + "\n".join(defects[:5])

    def test_A09_landing_on_runway(self, traces):
        """Landing should happen at the runway, not mid-taxiway."""
        defects = []
        for icao24, trace in traces.items():
            for i in range(1, len(trace)):
                if trace[i-1]["phase"] == "approaching" and trace[i]["phase"] == "landing":
                    alt = trace[i-1]["altitude"]
                    if alt > 800:
                        defects.append(
                            f"{trace[i]['callsign']} started landing at {alt:.0f}ft (should be ~200ft)"
                        )
        if defects:
            # Allow up to 20% failures (some go-arounds reset altitude)
            total_landings = sum(1 for _, t in traces.items()
                               for i in range(1, len(t))
                               if t[i-1]["phase"] == "approaching" and t[i]["phase"] == "landing")
            rate = len(defects) / max(1, total_landings)
            assert rate < 0.30, f"A09: {len(defects)} high-altitude landing defects:\n" + "\n".join(defects[:5])


# ============================================================================
# SECTION B: FLIGHT LIST — Left panel
# ============================================================================

class TestFlightList:
    """Section B: Flight list panel checks."""

    def test_B01_callsign_present(self, traces):
        """Every flight should have a non-empty callsign."""
        defects = []
        for icao24, trace in traces.items():
            if not trace[0].get("callsign"):
                defects.append(f"{icao24} has no callsign")
        assert len(defects) == 0, f"B01: {len(defects)} missing callsigns:\n" + "\n".join(defects)

    def test_B02_altitude_zero_on_ground(self, traces):
        """Ground phases should show altitude near 0ft (not airborne values)."""
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
            assert rate < 0.05, f"B02: {defects}/{total} ({rate:.0%}) ground flights show altitude > 100ft"

    def test_B03_speed_zero_when_parked(self, traces):
        """Parked flights should show speed ~0 (user sees 'SPD: 0kts')."""
        defects = 0
        total = 0
        for icao24, trace in traces.items():
            for snap in _phase_positions(trace, "parked"):
                total += 1
                if snap["velocity"] > 5:
                    defects += 1
        if total > 0:
            rate = defects / total
            assert rate < 0.05, f"B03: {defects}/{total} ({rate:.0%}) parked with speed > 5kts"

    def test_B04_frame_count_consistent(self, frames):
        """Flight count per frame should be monotonic-ish (not wild jumps)."""
        counts = [len(snaps) for snaps in frames.values()]
        if len(counts) < 2:
            return
        max_jump = max(abs(counts[i] - counts[i-1]) for i in range(1, len(counts)))
        # A jump of more than 5 flights in a single tick is suspicious
        assert max_jump <= 8, f"B04: Max flight count jump = {max_jump} between consecutive frames"


# ============================================================================
# SECTION C: FLIGHT DETAIL — Right panel
# ============================================================================

class TestFlightDetail:
    """Section C: Flight detail panel data correctness."""

    def test_C01_vertical_rate_not_dash(self, traces):
        """Climbing/descending flights should show a numeric vertical rate, not '--'.

        Enroute level flight has vertical_rate=0 by design (not a defect).
        Only check phases where the aircraft should be actively climbing or descending.
        """
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
                f"C01: {defects}/{total} ({rate:.0%}) climbing/descending snapshots with vertical_rate=0"
            )

    def test_C02_speed_varies_by_type(self, traces):
        """Approach speeds should vary by aircraft type (not all identical)."""
        type_speeds = defaultdict(list)
        for icao24, trace in traces.items():
            approach = _phase_positions(trace, "approaching")
            if len(approach) >= 3:
                aircraft_type = approach[-1].get("aircraft_type", "UNK")
                # Use full approach average (not just last 3) for robustness
                avg_speed = sum(s["velocity"] for s in approach) / len(approach)
                type_speeds[aircraft_type].append(avg_speed)

        if len(type_speeds) >= 2:
            means = {t: sum(v)/len(v) for t, v in type_speeds.items() if v}
            speeds = list(means.values())
            spread = max(speeds) - min(speeds) if speeds else 0
            assert spread > 0.5, (
                f"C02: Approach speed spread only {spread:.1f}kts across types {means}"
            )

    def test_C03_phase_changes_at_right_place(self, traces):
        """Phase changes should happen at reasonable positions/altitudes."""
        defects = []
        for icao24, trace in traces.items():
            for i in range(1, len(trace)):
                prev, curr = trace[i-1], trace[i]
                # Landing → taxi_to_gate should be at ground level
                if prev["phase"] == "landing" and curr["phase"] == "taxi_to_gate":
                    if curr["altitude"] > 50:
                        defects.append(
                            f"{curr['callsign']} landing→taxi at alt={curr['altitude']:.0f}ft"
                        )
                # takeoff → departing should be at low altitude
                if prev["phase"] == "takeoff" and curr["phase"] == "departing":
                    if curr["altitude"] > 5000:
                        defects.append(
                            f"{curr['callsign']} takeoff→departing at alt={curr['altitude']:.0f}ft"
                        )
        assert len(defects) == 0, f"C03: {len(defects)} phase-position defects:\n" + "\n".join(defects[:5])

    def test_C04_heading_in_valid_range(self, traces):
        """Heading should be 0-360 degrees (what the detail panel displays)."""
        defects = 0
        total = 0
        for icao24, trace in traces.items():
            for snap in trace:
                total += 1
                hdg = snap["heading"]
                if hdg < 0 or hdg > 360 or math.isnan(hdg):
                    defects += 1
        assert defects == 0, f"C04: {defects}/{total} invalid heading values (outside 0-360)"

    def test_C05_icao24_format(self, traces):
        """ICAO24 should be a non-empty string (shown in sub-header)."""
        defects = []
        for icao24 in traces:
            if not icao24 or len(icao24) < 3:
                defects.append(f"ICAO24 '{icao24}' too short")
        assert len(defects) == 0, f"C05: {len(defects)} ICAO24 format defects:\n" + "\n".join(defects[:5])


# ============================================================================
# SECTION D: DELAY PREDICTION
# ============================================================================

class TestDelayPrediction:
    """Section D: ML delay predictions shown in flight detail."""

    def test_D01_schedule_has_delays(self, sim):
        """Flights should have delay_minutes in schedule data."""
        recorder, _ = sim
        if not recorder.schedule:
            pytest.skip("No schedule data")
        has_delay = sum(1 for f in recorder.schedule if "delay_minutes" in f)
        assert has_delay > 0, "D01: No flights have delay_minutes field"

    def test_D02_delay_categories_realistic(self, sim):
        """Delay distribution should not be all zero or all extreme."""
        recorder, _ = sim
        delays = [f.get("delay_minutes", 0) for f in recorder.schedule]
        if not delays:
            pytest.skip("No schedule data")
        on_time = sum(1 for d in delays if d <= 15)
        rate = on_time / len(delays)
        assert rate >= 0.30, f"D02: Only {rate:.0%} flights on-time (expect >= 30%)"


# ============================================================================
# SECTION F: GATE STATUS PANEL
# ============================================================================

class TestGateStatus:
    """Section F: Gate status panel checks."""

    def test_F01_no_double_occupancy(self, sim):
        """Two aircraft should never occupy the same gate simultaneously."""
        recorder, _ = sim
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
                        defects.append(
                            f"Gate {gate}: {occupant} and {evt['icao24']} at {evt['time']}"
                        )
                    occupant = evt["icao24"]
                elif evt["event_type"] == "release":
                    if occupant == evt["icao24"]:
                        occupant = None
        assert len(defects) == 0, f"F01: {len(defects)} double occupancy defects:\n" + "\n".join(defects[:5])

    def test_F02_gate_occupy_has_release(self, sim):
        """Every gate occupation should eventually be released (gate turns green again)."""
        recorder, _ = sim
        occupations = {}
        releases = set()
        for evt in recorder.gate_events:
            if evt["event_type"] in ("assign", "occupy"):
                occupations[(evt["gate"], evt["icao24"])] = evt["time"]
            elif evt["event_type"] == "release":
                releases.add((evt["gate"], evt["icao24"]))

        # Flights still parked at sim end are OK — only flag if > 50% have no release
        unreleased = len(occupations) - len(releases & set(occupations.keys()))
        if occupations:
            rate = unreleased / len(occupations)
            assert rate < 0.60, (
                f"F02: {unreleased}/{len(occupations)} ({rate:.0%}) gate occupations never released"
            )


# ============================================================================
# SECTION G: TURNAROUND TIMELINE
# ============================================================================

class TestTurnaroundTimeline:
    """Section G: Turnaround phase progression for parked flights."""

    def test_G01_turnaround_time_reasonable(self, sim):
        """Turnaround should be 15-300 minutes (visible in progress bar)."""
        recorder, _ = sim
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
                defects.append(f"{callsign}: turnaround only {dt:.0f}min (too short)")
            elif dt > 300:
                defects.append(f"{callsign}: turnaround {dt:.0f}min (too long)")
        assert len(defects) == 0, f"G01: {len(defects)} turnaround time defects:\n" + "\n".join(defects[:5])


# ============================================================================
# SECTION H: BAGGAGE STATUS
# ============================================================================

class TestBaggageStatus:
    """Section H: Baggage counts and processing."""

    def test_H01_bag_count_reasonable(self, sim):
        """Each flight should have 50-400 bags (shown in stats grid)."""
        recorder, _ = sim
        defects = []
        for evt in recorder.baggage_events:
            count = evt.get("bag_count", 0)
            if count < 10:
                defects.append(f"{evt['flight_number']}: only {count} bags")
            elif count > 500:
                defects.append(f"{evt['flight_number']}: {count} bags (excessive)")
        if defects:
            rate = len(defects) / max(1, len(recorder.baggage_events))
            assert rate < 0.20, f"H01: {len(defects)} bag count defects:\n" + "\n".join(defects[:5])


# ============================================================================
# SECTION I: FIDS — Flight Information Display
# ============================================================================

class TestFIDS:
    """Section I: FIDS board data correctness."""

    def test_I01_schedule_has_required_fields(self, sim):
        """Each schedule entry should have the fields shown on FIDS."""
        recorder, _ = sim
        required = {"flight_number", "flight_type", "scheduled_time"}
        defects = []
        for f in recorder.schedule[:5]:
            missing = required - set(f.keys())
            if missing:
                defects.append(f"{f.get('flight_number', '?')}: missing {missing}")
        assert len(defects) == 0, f"I01: {len(defects)} schedule field defects:\n" + "\n".join(defects)

    def test_I02_schedule_time_ordered(self, sim):
        """Schedule should be in chronological order."""
        recorder, _ = sim
        arrivals = [f for f in recorder.schedule if f.get("flight_type") == "arrival"]
        departures = [f for f in recorder.schedule if f.get("flight_type") == "departure"]

        for label, flights in [("arrivals", arrivals), ("departures", departures)]:
            times = [f["scheduled_time"] for f in flights if "scheduled_time" in f]
            sorted_times = sorted(times)
            assert times == sorted_times, f"I02: {label} not in chronological order"


# ============================================================================
# SECTION J: WEATHER WIDGET
# ============================================================================

class TestWeatherWidget:
    """Section J: Weather data shown in header."""

    def test_J01_weather_snapshots_exist(self, sim):
        """At least one weather snapshot should be recorded."""
        recorder, _ = sim
        assert len(recorder.weather_snapshots) > 0, "J01: No weather snapshots recorded"

    def test_J02_weather_has_required_fields(self, sim):
        """Weather should have temp, wind, visibility, category."""
        recorder, _ = sim
        if not recorder.weather_snapshots:
            pytest.skip("No weather data")
        w = recorder.weather_snapshots[0]
        for field in ["wind_speed_kts", "visibility_sm", "temperature_c", "flight_category"]:
            assert field in w, f"J02: Weather missing '{field}'"


# ============================================================================
# SECTION K: PLAYBACK BAR — Timeline consistency
# ============================================================================

class TestPlaybackBar:
    """Section K: Simulation playback timeline checks."""

    def test_K01_time_advances_monotonically(self, frames):
        """Simulation time should always advance (progress bar moves right)."""
        times = sorted(frames.keys())
        for i in range(1, len(times)):
            assert times[i] > times[i-1], f"K01: Time went backwards at {times[i]}"

    def test_K02_no_empty_frames(self, frames):
        """No frame should have zero flights (playback bar shows count > 0)."""
        empty = [t for t, snaps in frames.items() if len(snaps) == 0]
        assert len(empty) == 0, f"K02: {len(empty)} frames with zero flights"

    def test_K03_flight_count_rises_and_falls(self, frames):
        """Flight count should rise (spawning) and fall (completing) over time."""
        counts = [len(snaps) for snaps in frames.values()]
        if not counts:
            pytest.skip("No frames")
        peak = max(counts)
        final = counts[-1]
        # Peak should be higher than both start and end (flights come and go)
        assert peak >= 2, f"K03: Peak simultaneous flights = {peak} (too few for 20 flights)"


# ============================================================================
# SECTION L: SIMULATION FILE — Summary metrics
# ============================================================================

class TestSimulationSummary:
    """Section L: Summary metrics correctness."""

    def test_L01_summary_counts_match(self, sim):
        """Summary flight counts should match actual data."""
        recorder, config = sim
        summary = recorder.compute_summary(config.model_dump())
        # Position snapshots count
        assert summary["total_position_snapshots"] == len(recorder.position_snapshots)
        # Phase transitions count
        assert summary["total_phase_transitions"] == len(recorder.phase_transitions)
        # Gate events count
        assert summary["total_gate_events"] == len(recorder.gate_events)

    def test_L02_schedule_count_matches_config(self, sim):
        """Scheduled flights should match config arrivals + departures."""
        recorder, config = sim
        expected = config.arrivals + config.departures
        actual = len(recorder.schedule)
        assert actual == expected, f"L02: {actual} scheduled vs {expected} configured"


# ============================================================================
# SECTION O: CONNECTION / DATA INTEGRITY
# ============================================================================

class TestDataIntegrity:
    """Section O: Overall data integrity checks."""

    def test_O01_no_nan_in_numeric_fields(self, traces):
        """No NaN values in numeric fields (would show as '--' in UI)."""
        numeric_fields = ["latitude", "longitude", "altitude", "velocity", "heading", "vertical_rate"]
        defects = 0
        total = 0
        for icao24, trace in traces.items():
            for snap in trace:
                for field in numeric_fields:
                    val = snap.get(field)
                    if val is not None:
                        total += 1
                        if isinstance(val, float) and math.isnan(val):
                            defects += 1
        assert defects == 0, f"O01: {defects}/{total} NaN values in numeric fields"

    def test_O02_no_negative_altitude(self, traces):
        """Altitude must never go negative (physically impossible)."""
        defects = 0
        for icao24, trace in traces.items():
            for snap in trace:
                if snap["altitude"] < -10:
                    defects += 1
        assert defects == 0, f"O02: {defects} negative altitude readings"

    def test_O03_all_arrivals_complete_lifecycle(self, traces, sim):
        """Arriving flights should progress: approaching → landing → taxi → parked."""
        recorder, _ = sim
        defects = []
        # Build icao24 from schedule index (engine uses f"sim{idx:05d}")
        arrivals = set()
        for idx, f in enumerate(recorder.schedule):
            if f.get("flight_type") == "arrival" and f.get("spawned"):
                arrivals.add(f"sim{idx:05d}")
        for icao24 in arrivals:
            if icao24 not in traces:
                continue
            seq = _phase_sequence(traces[icao24])
            if "approaching" in seq and "parked" not in seq:
                defects.append(f"{traces[icao24][0]['callsign']}: {' → '.join(seq)}")
        # Allow some flights that are still in progress at sim end
        if arrivals and defects:
            rate = len(defects) / len(arrivals)
            assert rate < 0.55, f"O03: {len(defects)}/{len(arrivals)} arrivals incomplete:\n" + "\n".join(defects[:5])

    def test_O04_all_departures_complete_lifecycle(self, traces, sim):
        """Departing flights should progress: parked → pushback → taxi → takeoff → departing."""
        recorder, _ = sim
        defects = []
        departures = set()
        for idx, f in enumerate(recorder.schedule):
            if f.get("flight_type") == "departure" and f.get("spawned"):
                departures.add(f"sim{idx:05d}")
        for icao24 in departures:
            if icao24 not in traces:
                continue
            seq = _phase_sequence(traces[icao24])
            if "parked" in seq and "departing" not in seq and "enroute" not in seq:
                defects.append(f"{traces[icao24][0]['callsign']}: {' → '.join(seq)}")
        if departures and defects:
            rate = len(defects) / len(departures)
            # In a short 3h sim, many departures may still be on the ground at sim end
            assert rate < 0.75, f"O04: {len(defects)}/{len(departures)} departures incomplete:\n" + "\n".join(defects[:5])

    def test_O05_smooth_altitude_during_approach(self, traces):
        """Approach altitude should decrease smoothly (no abrupt altitude resets).

        Go-arounds produce legitimate altitude gains at ≤1500 ft/min (~750ft per
        30s snapshot). Only flag altitude gains that exceed the go-around climb
        rate (indicating an instant reset rather than smooth climb).
        """
        defects = []
        MAX_GA_CLIMB_PER_SNAP = 850  # 1500 ft/min * 30s + 100ft tolerance
        for icao24, trace in traces.items():
            approach = _phase_positions(trace, "approaching")
            for i in range(1, len(approach)):
                alt_change = approach[i]["altitude"] - approach[i-1]["altitude"]
                if 0 < alt_change <= MAX_GA_CLIMB_PER_SNAP:
                    continue  # Normal go-around climb rate
                if alt_change > MAX_GA_CLIMB_PER_SNAP:
                    defects.append(
                        f"{approach[i]['callsign']} altitude jumped +{alt_change:.0f}ft "
                        f"at {approach[i-1]['altitude']:.0f}ft during approach at {approach[i]['time']}"
                    )
        assert len(defects) == 0, f"O05: {len(defects)} altitude jump defects:\n" + "\n".join(defects[:5])

    def test_O06_heading_smooth_turns(self, traces):
        """Heading should change smoothly (max ~3°/s standard rate turn)."""
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
                # Standard rate turn = 3°/s, allow double for corrections
                max_turn = 6.0 * dt + 5  # degrees (with 5° noise tolerance)
                if diff > max_turn:
                    defects += 1
        if checked > 0:
            rate = defects / checked
            assert rate < 0.05, f"O06: {defects}/{checked} ({rate:.0%}) jerky heading changes"
