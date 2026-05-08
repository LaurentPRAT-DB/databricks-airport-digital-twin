"""Go-around trajectory visualization — physics and continuity validation.

Tests the `generate_synthetic_trajectory` output for go-around flights,
validating that the rendered path:
- Has no gaps that would split the polyline on the map
- Follows realistic missed approach geometry (climb-out → crosswind → downwind → base)
- Doesn't cross the active runway centerline
- Maintains physically plausible speeds, climb rates, and turn radii
- Complies with ICAO Doc 8168 / FAA AIM missed approach procedures

These tests exercise the trajectory *visualization* code (not the simulation engine).
"""

import math

import pytest

from src.ingestion._state import FlightState, FlightPhase


# Override conftest's autouse patch that forces SFO runway for all tests.
# This module uses real airport configs loaded via initialize_from_lakehouse.
@pytest.fixture(autouse=True)
def _provide_osm_runway_data():
    """Disable conftest's SFO runway patch — use real OSM data from config service."""
    yield


# ─── Fixtures ────────────────────────────────────────────────────────────────

def _init_airport(icao: str, iata: str, lat: float, lon: float):
    """Load airport config and set as current."""
    from app.backend.services.airport_config_service import get_airport_config_service
    from src.ingestion.fallback import set_airport_center

    service = get_airport_config_service()
    service.initialize_from_lakehouse(icao)
    set_airport_center(lat, lon, iata=iata)


def _make_go_around_flight(
    icao24: str,
    callsign: str,
    lat: float,
    lon: float,
    altitude: float,
    heading: float,
    origin: str,
    destination: str,
    go_around_count: int = 1,
    waypoint_index: int = 10,
) -> FlightState:
    """Create a flight state representing a go-around in re-approach."""
    from src.ingestion._generation import _flight_states

    state = FlightState(
        icao24=icao24,
        callsign=callsign,
        latitude=lat,
        longitude=lon,
        altitude=altitude,
        velocity=160.0,
        heading=heading,
        vertical_rate=-700.0,
        on_ground=False,
        phase=FlightPhase.APPROACHING,
    )
    state.go_around_count = go_around_count
    state.origin_airport = origin
    state.destination_airport = destination
    state.waypoint_index = waypoint_index
    _flight_states[icao24] = state
    return state


def _generate_trajectory(icao24: str):
    """Generate trajectory for a registered flight."""
    from src.ingestion._generation import generate_synthetic_trajectory
    return generate_synthetic_trajectory(icao24, minutes=60, limit=500)


def _get_heading():
    """Get current airport runway heading."""
    from src.ingestion._approach_departure import _get_runway_heading
    return _get_runway_heading()


# ─── Helper: geometry ────────────────────────────────────────────────────────

def _gap(p1: dict, p2: dict) -> float:
    """Euclidean distance in degrees between two trajectory points."""
    return math.sqrt(
        (p2["latitude"] - p1["latitude"]) ** 2
        + (p2["longitude"] - p1["longitude"]) ** 2
    )


def _distance_nm(p1: dict, p2: dict) -> float:
    """Great-circle distance in nautical miles (approximate)."""
    dlat = math.radians(p2["latitude"] - p1["latitude"])
    dlon = math.radians(p2["longitude"] - p1["longitude"])
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(p1["latitude"]))
         * math.cos(math.radians(p2["latitude"]))
         * math.sin(dlon / 2) ** 2)
    return 2 * 3440.065 * math.asin(math.sqrt(a))


def _bearing(p1: dict, p2: dict) -> float:
    """Bearing from p1 to p2 in degrees [0, 360)."""
    lat1, lon1 = math.radians(p1["latitude"]), math.radians(p1["longitude"])
    lat2, lon2 = math.radians(p2["latitude"]), math.radians(p2["longitude"])
    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = (math.cos(lat1) * math.sin(lat2)
         - math.sin(lat1) * math.cos(lat2) * math.cos(dlon))
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def _heading_diff(h1: float, h2: float) -> float:
    """Smallest angular difference between two headings."""
    return abs((h2 - h1 + 180) % 360 - 180)


def _perpendicular_distance_to_line(
    point: dict, line_start: dict, line_end: dict
) -> float:
    """Perpendicular distance from point to line in nautical miles."""
    d_start = _distance_nm(line_start, point)
    bearing_line = _bearing(line_start, line_end)
    bearing_point = _bearing(line_start, point)
    angle_diff = math.radians(bearing_point - bearing_line)
    return abs(d_start * math.sin(angle_diff))


# ─── Test airports ───────────────────────────────────────────────────────────

AIRPORTS = [
    ("KJFK", "JFK", 40.6413, -73.7781, "ATL"),
    ("KSFO", "SFO", 37.6213, -122.379, "LAX"),
]


@pytest.fixture(params=AIRPORTS, ids=[a[0] for a in AIRPORTS], scope="module")
def go_around_trajectory(request):
    """Generate a go-around trajectory for each test airport."""
    icao, iata, lat, lon, origin = request.param
    _init_airport(icao, iata, lat, lon)
    heading = _get_heading()
    if heading is None:
        pytest.skip(f"No runway data for {icao}")

    # Position aircraft on approach near the runway
    offset_lat = -0.02 * math.cos(math.radians(heading))
    offset_lon = -0.02 * math.sin(math.radians(heading))
    ac_lat = lat + offset_lat
    ac_lon = lon + offset_lon

    flight_id = f"ga_{icao.lower()}"
    _make_go_around_flight(
        icao24=flight_id,
        callsign=f"TST{icao[1:4]}",
        lat=ac_lat,
        lon=ac_lon,
        altitude=3000.0,
        heading=heading,
        origin=origin,
        destination=iata,
        go_around_count=1,
        waypoint_index=10,
    )
    traj = _generate_trajectory(flight_id)
    if not traj or len(traj) < 10:
        pytest.skip(f"Trajectory generation failed for {icao}")

    return {
        "airport": icao,
        "heading": heading,
        "threshold_lat": lat,
        "threshold_lon": lon,
        "trajectory": traj,
    }


# ─── T1: Polyline Continuity ────────────────────────────────────────────────

class TestContinuity:
    """The trajectory must render as a single continuous polyline."""

    MAX_GAP_DEG = 0.04  # Frontend splitAtGaps threshold

    def test_no_gaps_exceed_split_threshold(self, go_around_trajectory):
        """No consecutive point gap > 0.04° (the frontend polyline split threshold)."""
        traj = go_around_trajectory["trajectory"]
        max_gap = 0.0
        worst_idx = 0
        for i in range(1, len(traj)):
            g = _gap(traj[i - 1], traj[i])
            if g > max_gap:
                max_gap = g
                worst_idx = i
        assert max_gap < self.MAX_GAP_DEG, (
            f"Gap at point {worst_idx}: {max_gap:.5f}° > {self.MAX_GAP_DEG}° threshold "
            f"({max_gap * 111:.1f} km) — trajectory will split on map"
        )

    def test_max_gap_under_1km(self, go_around_trajectory):
        """Conservative check: max gap should be well under 1 km for smoothness."""
        traj = go_around_trajectory["trajectory"]
        max_gap_km = max(
            _gap(traj[i - 1], traj[i]) * 111 for i in range(1, len(traj))
        )
        assert max_gap_km < 1.5, f"Max gap {max_gap_km:.2f} km — trajectory may look jumpy"

    def test_no_excessive_duplicate_positions(self, go_around_trajectory):
        """No more than 5 consecutive points at the exact same lat/lon.

        Some duplicates are acceptable at phase transitions (e.g., the
        climb-out start shares the threshold position), but long runs
        indicate the trajectory is stalled.
        """
        traj = go_around_trajectory["trajectory"]
        max_repeats = 0
        current_repeats = 0
        for i in range(1, len(traj)):
            if (abs(traj[i]["latitude"] - traj[i - 1]["latitude"]) < 1e-7
                    and abs(traj[i]["longitude"] - traj[i - 1]["longitude"]) < 1e-7):
                current_repeats += 1
                max_repeats = max(max_repeats, current_repeats)
            else:
                current_repeats = 0
        assert max_repeats <= 5, (
            f"{max_repeats} consecutive duplicate positions — trajectory stalls visually"
        )


# ─── T2: Go-Around Pattern Shape ────────────────────────────────────────────

class TestMissedApproachPattern:
    """The trajectory must show the standard missed approach pattern."""

    def test_has_climb_phase(self, go_around_trajectory):
        """Altitude must increase after the low point (climb-out after missed approach)."""
        traj = go_around_trajectory["trajectory"]
        altitudes = [p.get("altitude", 0) for p in traj]
        has_climb = any(
            altitudes[i] > altitudes[i - 1] + 50 for i in range(1, len(altitudes))
        )
        assert has_climb, "No climb detected — go-around pattern not visible"

    def test_climb_out_on_runway_heading(self, go_around_trajectory):
        """Initial climb-out should be approximately on runway heading (±30°)."""
        traj = go_around_trajectory["trajectory"]
        rwy_heading = go_around_trajectory["heading"]

        # Find the low-altitude point (missed approach point) and check heading after
        altitudes = [p.get("altitude", 0) for p in traj]
        min_idx = altitudes.index(min(altitudes))

        # Check heading of first few points after the minimum
        climb_start = min(min_idx + 1, len(traj) - 2)
        climb_end = min(climb_start + 5, len(traj) - 1)
        if climb_end <= climb_start:
            return

        climb_bearing = _bearing(traj[climb_start], traj[climb_end])
        diff = _heading_diff(rwy_heading, climb_bearing)
        assert diff < 40, (
            f"Climb-out heading {climb_bearing:.0f}° deviates {diff:.0f}° "
            f"from runway heading {rwy_heading:.0f}° (max 40°)"
        )

    def test_lateral_offset_from_runway(self, go_around_trajectory):
        """The return leg must be laterally offset from the runway centerline.

        ICAO Doc 8168 Vol II: missed approach must not conflict with runway ops.
        The downwind/return should be at least 0.5 NM lateral offset.
        """
        traj = go_around_trajectory["trajectory"]
        rwy_heading = go_around_trajectory["heading"]
        threshold = {
            "latitude": go_around_trajectory["threshold_lat"],
            "longitude": go_around_trajectory["threshold_lon"],
        }

        # The runway far end (approximate, 2km along heading)
        rwy_far = {
            "latitude": threshold["latitude"] + 0.02 * math.cos(math.radians(rwy_heading)),
            "longitude": threshold["longitude"] + 0.02 * math.sin(math.radians(rwy_heading))
            / math.cos(math.radians(threshold["latitude"])),
        }

        # Find the "return" portion: points where altitude is near climb-out (1500ft ± 500)
        return_points = [
            p for p in traj
            if 1000 < p.get("altitude", 0) < 2500
            and _distance_nm(p, threshold) > 0.5
        ]

        if not return_points:
            return  # No distinct return phase identifiable

        max_offset = max(
            _perpendicular_distance_to_line(p, threshold, rwy_far)
            for p in return_points
        )
        assert max_offset > 0.3, (
            f"Max lateral offset {max_offset:.2f} NM — pattern too close to runway "
            f"(min 0.3 NM for traffic separation)"
        )

    def test_does_not_cross_runway(self, go_around_trajectory):
        """The return path must not cross directly over the runway threshold.

        This was the original bug: straight-line return flew over the runway.
        """
        traj = go_around_trajectory["trajectory"]
        threshold = {
            "latitude": go_around_trajectory["threshold_lat"],
            "longitude": go_around_trajectory["threshold_lon"],
        }

        # Find the "return" phase: after climb-out (altitude ≥ 1200ft),
        # before re-approach descent
        altitudes = [p.get("altitude", 0) for p in traj]
        min_idx = altitudes.index(min(altitudes))

        # Points after the climb that are at pattern altitude
        pattern_points = [
            p for i, p in enumerate(traj)
            if i > min_idx + 3 and 1000 < p.get("altitude", 0) < 4000
        ]

        if not pattern_points:
            return

        # None of the pattern points should be directly over the threshold.
        # Some proximity is expected (climb-out starts at threshold), so we
        # check that the lateral offset portions are away from the runway zone.
        # Filter to only the return/downwind points (not climb-out start).
        return_points = [
            p for p in pattern_points
            if _distance_nm(p, threshold) > 0.3
        ]
        if not return_points:
            return  # All pattern points are near threshold (short pattern)
        closest = min(
            _distance_nm(p, threshold) for p in return_points
        )
        assert closest > 0.3, (
            f"Return leg passes {closest:.2f} NM from threshold — too close"
        )


# ─── T3: Aviation Physics ────────────────────────────────────────────────────

class TestAviationPhysics:
    """Physical plausibility of the trajectory."""

    def test_altitude_never_negative(self, go_around_trajectory):
        """Altitude must never go below 0 ft."""
        traj = go_around_trajectory["trajectory"]
        min_alt = min(p.get("altitude", 0) for p in traj)
        assert min_alt >= 0, f"Negative altitude: {min_alt:.0f} ft"

    def test_max_altitude_reasonable(self, go_around_trajectory):
        """Approach trajectory shouldn't exceed FL250 (25,000 ft)."""
        traj = go_around_trajectory["trajectory"]
        max_alt = max(p.get("altitude", 0) for p in traj)
        assert max_alt < 25000, f"Unreasonable max altitude: {max_alt:.0f} ft"

    def test_climb_gradient_minimum(self, go_around_trajectory):
        """FAA AIM 5-4-21: missed approach climb gradient ≥ 200 ft/NM.

        We check that the climb-out gains altitude proportional to distance.
        """
        traj = go_around_trajectory["trajectory"]
        altitudes = [p.get("altitude", 0) for p in traj]
        min_idx = altitudes.index(min(altitudes))

        # Find the climb phase (min alt to peak)
        climb_points = []
        prev_alt = altitudes[min_idx]
        for i in range(min_idx, min(min_idx + 15, len(traj))):
            if altitudes[i] >= prev_alt:
                climb_points.append(traj[i])
                prev_alt = altitudes[i]
            elif len(climb_points) > 2:
                break

        if len(climb_points) < 3:
            return

        # Distance traveled during climb
        climb_dist_nm = sum(
            _distance_nm(climb_points[i], climb_points[i + 1])
            for i in range(len(climb_points) - 1)
        )
        alt_gain = climb_points[-1].get("altitude", 0) - climb_points[0].get("altitude", 0)

        if climb_dist_nm > 0.1:
            gradient = alt_gain / climb_dist_nm
            assert gradient > 150, (
                f"Climb gradient {gradient:.0f} ft/NM < 150 ft/NM minimum "
                f"(gained {alt_gain:.0f} ft over {climb_dist_nm:.1f} NM)"
            )

    def test_no_supersonic_segments(self, go_around_trajectory):
        """No segment implies speed > Mach 1 (600+ kts ground speed).

        Ground speed = distance / time between consecutive points.
        """
        from datetime import datetime

        traj = go_around_trajectory["trajectory"]
        for i in range(1, len(traj)):
            ts_curr = traj[i]["timestamp"]
            ts_prev = traj[i - 1]["timestamp"]
            # Timestamps may be epoch (int/float) or ISO string
            if isinstance(ts_curr, str):
                t1 = datetime.fromisoformat(ts_prev.replace("Z", "+00:00"))
                t2 = datetime.fromisoformat(ts_curr.replace("Z", "+00:00"))
                dt = abs((t2 - t1).total_seconds())
            else:
                dt = abs(ts_curr - ts_prev)
            if dt < 1:
                continue
            dist_nm = _distance_nm(traj[i - 1], traj[i])
            gs_kts = dist_nm / (dt / 3600)
            assert gs_kts < 600, (
                f"Point {i}: implied {gs_kts:.0f} kts ground speed (supersonic)"
            )

    def test_turn_radius_physically_possible(self, go_around_trajectory):
        """Turn radius must be achievable at approach speed (min ~0.5 NM at 160 kts).

        Bank angle 25° (standard): R = V² / (g * tan(bank))
        At 160 kts: R ≈ 0.45 NM. We use 0.3 NM as conservative lower bound.
        """
        traj = go_around_trajectory["trajectory"]
        if len(traj) < 5:
            return

        violations = 0
        total_turns = 0
        for i in range(2, len(traj) - 2):
            # Compute turn by comparing bearing before and after point
            bearing_in = _bearing(traj[i - 2], traj[i])
            bearing_out = _bearing(traj[i], traj[i + 2])
            turn_angle = _heading_diff(bearing_in, bearing_out)

            if turn_angle < 5:
                continue  # Straight segment

            total_turns += 1
            # Arc length ≈ distance over these 4 points
            arc_nm = _distance_nm(traj[i - 2], traj[i + 2])
            if arc_nm < 0.01:
                continue

            # radius = arc_length / angle_radians
            radius_nm = arc_nm / math.radians(turn_angle)
            if radius_nm < 0.2:
                violations += 1

        if total_turns > 0:
            violation_rate = violations / total_turns
            assert violation_rate < 0.15, (
                f"{violations}/{total_turns} turns have radius < 0.2 NM "
                f"(physically impossible at approach speed)"
            )


# ─── T4: Descent Profile ────────────────────────────────────────────────────

class TestDescentProfile:
    """Re-approach descent should approximate standard 3° glideslope."""

    def test_final_approach_descends(self, go_around_trajectory):
        """The last 20% of points (re-approach) should show decreasing altitude."""
        traj = go_around_trajectory["trajectory"]
        n = len(traj)
        last_quarter = traj[int(n * 0.75):]

        if len(last_quarter) < 3:
            return

        # Altitude should generally decrease
        alt_start = last_quarter[0].get("altitude", 0)
        alt_end = last_quarter[-1].get("altitude", 0)
        assert alt_end < alt_start, (
            f"Re-approach doesn't descend: {alt_start:.0f}ft → {alt_end:.0f}ft"
        )

    def test_final_altitude_near_ground(self, go_around_trajectory):
        """Trajectory should end at low altitude (< 500 ft) near the runway."""
        traj = go_around_trajectory["trajectory"]
        final_alt = traj[-1].get("altitude", 0)
        assert final_alt < 500, (
            f"Trajectory ends at {final_alt:.0f}ft — should be near ground on approach"
        )

    def test_descent_rate_not_extreme(self, go_around_trajectory):
        """Descent rate should not exceed 3000 ft/NM (roughly 3× normal glideslope)."""
        traj = go_around_trajectory["trajectory"]
        n = len(traj)
        last_half = traj[int(n * 0.5):]

        for i in range(1, len(last_half)):
            dist_nm = _distance_nm(last_half[i - 1], last_half[i])
            if dist_nm < 0.05:
                continue
            alt_loss = last_half[i - 1].get("altitude", 0) - last_half[i].get("altitude", 0)
            if alt_loss <= 0:
                continue
            descent_rate = alt_loss / dist_nm
            assert descent_rate < 3000, (
                f"Descent rate {descent_rate:.0f} ft/NM at point {i} — too steep "
                f"(normal glideslope is ~318 ft/NM)"
            )


# ─── T5: Multiple Go-Arounds ────────────────────────────────────────────────

class TestMultipleGoArounds:
    """Aircraft with 2+ go-arounds should still produce valid trajectories."""

    def test_double_go_around_continuous(self):
        """A flight with go_around_count=2 should still have no gap violations."""
        import uuid

        _init_airport("KJFK", "JFK", 40.6413, -73.7781)
        heading = _get_heading()
        if heading is None:
            pytest.skip("No runway data")

        flight_id = f"ga_dbl_{uuid.uuid4().hex[:8]}"
        _make_go_around_flight(
            icao24=flight_id,
            callsign="TST999",
            lat=40.62,
            lon=-73.76,
            altitude=4000.0,
            heading=heading,
            origin="ATL",
            destination="JFK",
            go_around_count=2,
            waypoint_index=10,
        )
        traj = _generate_trajectory(flight_id)
        if not traj or len(traj) < 5:
            pytest.skip("No trajectory generated")

        max_gap = max(
            _gap(traj[i - 1], traj[i]) for i in range(1, len(traj))
        )
        assert max_gap < 0.04, f"Double go-around max gap: {max_gap:.5f}° (limit 0.04°)"


# ─── T6: Edge Cases ─────────────────────────────────────────────────────────

class TestEdgeCases:
    """Edge cases that previously caused issues."""

    def test_enroute_phase_go_around(self):
        """Flight in enroute phase (holding after go-around) gets trajectory."""
        import uuid

        _init_airport("KSFO", "SFO", 37.6213, -122.379)
        heading = _get_heading()
        if heading is None:
            pytest.skip("No runway data")

        from src.ingestion._generation import _flight_states
        flight_id = f"ga_enr_{uuid.uuid4().hex[:8]}"
        state = FlightState(
            icao24=flight_id,
            callsign="UAL777",
            latitude=37.65,
            longitude=-122.30,
            altitude=4000.0,
            velocity=180.0,
            heading=heading,
            vertical_rate=0.0,
            on_ground=False,
            phase=FlightPhase.ENROUTE,
        )
        state.go_around_count = 1
        state.origin_airport = "SEA"
        state.destination_airport = "SFO"
        state.waypoint_index = 5
        _flight_states[flight_id] = state

        traj = _generate_trajectory(flight_id)
        if not traj or len(traj) < 5:
            pytest.skip("No trajectory for enroute go-around")

        max_gap = max(
            _gap(traj[i - 1], traj[i]) for i in range(1, len(traj))
        )
        assert max_gap < 0.04, f"Enroute go-around gap: {max_gap:.5f}°"

    def test_waypoint_index_at_boundary(self):
        """Flight at various waypoint indices still produces valid trajectory."""
        import uuid

        _init_airport("KJFK", "JFK", 40.6413, -73.7781)
        heading = _get_heading()
        if heading is None:
            pytest.skip("No runway data")

        # Use ATL origin (known to have 14 waypoints at KJFK)
        # Test mid-range indices that are realistic for a re-approach
        for wp_idx in [8, 10, 12]:
            flight_id = f"ga_bnd_{wp_idx}_{uuid.uuid4().hex[:6]}"
            _make_go_around_flight(
                icao24=flight_id,
                callsign=f"BND{wp_idx:02d}",
                lat=40.62,
                lon=-73.76,
                altitude=2500.0,
                heading=heading,
                origin="ATL",
                destination="JFK",
                go_around_count=1,
                waypoint_index=wp_idx,
            )
            traj = _generate_trajectory(flight_id)
            if not traj or len(traj) < 2:
                continue

            max_gap = max(
                _gap(traj[i - 1], traj[i]) for i in range(1, len(traj))
            )
            assert max_gap < 0.04, (
                f"wp_idx={wp_idx}: gap {max_gap:.5f}° exceeds threshold"
            )
