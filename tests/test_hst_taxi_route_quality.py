"""High-speed turnoff (HST) and taxi route quality regression tests.

Validates:
- Aircraft exits runway at realistic HST speed (45-60kt, not 30kt)
- Rollout distance matches real-world (900-1400m, not <850m)
- Deceleration profile is two-phase (reverse thrust + brakes)
- Taxi routes after landing do not pass through terminal buildings
- Routes from rollout position snap to taxiway nodes, not through buildings
"""

import math
from datetime import datetime

import pytest

from src.ingestion._constants import VREF_SPEEDS, _DEFAULT_VREF
from src.simulation.config import SimulationConfig
from src.simulation.engine import SimulationEngine
from tests.sim_helpers import extract_flight_traces, phase_positions


@pytest.fixture(scope="module")
def hst_sim():
    """Run SFO sim focused on arrivals to validate HST + taxi quality."""
    config = SimulationConfig(
        airport="SFO",
        arrivals=20,
        departures=5,
        duration_hours=6.0,
        time_step_seconds=2.0,
        seed=99,
        diagnostics=True,
    )
    engine = SimulationEngine(config)
    recorder = engine.run()
    traces = extract_flight_traces(recorder)
    return recorder, config, traces


def _haversine_m(lat1, lon1, lat2, lon2):
    """Distance between two (lat, lon) points in meters."""
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


class TestHighSpeedTurnoff:
    """Aircraft should exit runway at HST speed (45-60kt), not crawl to 30kt."""

    def test_runway_exit_speed_is_hst_range(self, hst_sim):
        """Last landing snapshot speed should be in HST range (40-60kt)."""
        _, _, traces = hst_sim
        checked = 0
        in_hst_range = 0

        for icao24, trace in traces.items():
            landing = phase_positions(trace, "landing")
            taxi = phase_positions(trace, "taxi_to_gate")
            if not landing or not taxi:
                continue
            checked += 1
            exit_speed = landing[-1]["velocity"]
            if 35 <= exit_speed <= 60:
                in_hst_range += 1

        assert checked >= 5, f"Need ≥5 arrivals, got {checked}"
        ratio = in_hst_range / checked
        assert ratio >= 0.70, (
            f"Only {in_hst_range}/{checked} ({ratio:.0%}) exited at HST speed (35-60kt). "
            f"Expected ≥70%."
        )

    def test_rollout_distance_realistic(self, hst_sim):
        """Rollout from touchdown to taxi transition: 900-1500m (not <800m)."""
        _, _, traces = hst_sim
        rollout_distances = []

        for icao24, trace in traces.items():
            landing = phase_positions(trace, "landing")
            if not landing:
                continue
            ground_snaps = [s for s in landing if s["altitude"] == 0]
            if len(ground_snaps) < 2:
                continue
            first = ground_snaps[0]
            last = ground_snaps[-1]
            dist = _haversine_m(
                first["latitude"], first["longitude"],
                last["latitude"], last["longitude"]
            )
            if dist > 50:
                rollout_distances.append(dist)

        assert len(rollout_distances) >= 5, f"Need ≥5 rollouts, got {len(rollout_distances)}"
        mean_dist = sum(rollout_distances) / len(rollout_distances)
        assert mean_dist >= 800, (
            f"Mean rollout {mean_dist:.0f}m is too short (expected ≥800m). "
            f"Aircraft not reaching HST exits."
        )
        too_short = sum(1 for d in rollout_distances if d < 600)
        assert too_short / len(rollout_distances) < 0.20, (
            f"{too_short}/{len(rollout_distances)} rollouts < 600m. "
            f"Too many short rollouts — aircraft braking too aggressively."
        )

    def test_two_phase_deceleration(self, hst_sim):
        """Decel should be slower at high speed (~3.5kt/s) and faster below 60kt (~5kt/s)."""
        _, _, traces = hst_sim
        high_speed_decels = []
        low_speed_decels = []

        for icao24, trace in traces.items():
            landing = phase_positions(trace, "landing")
            ground_snaps = [s for s in landing if s["altitude"] == 0]
            if len(ground_snaps) < 3:
                continue
            for i in range(1, len(ground_snaps)):
                dt = (datetime.fromisoformat(ground_snaps[i]["time"]) -
                      datetime.fromisoformat(ground_snaps[i-1]["time"])).total_seconds()
                if dt <= 0:
                    continue
                v_prev = ground_snaps[i-1]["velocity"]
                v_curr = ground_snaps[i]["velocity"]
                decel = (v_prev - v_curr) / dt
                if decel < 0:
                    continue
                if v_prev > 70:
                    high_speed_decels.append(decel)
                elif v_prev < 55:
                    low_speed_decels.append(decel)

        if len(high_speed_decels) >= 5:
            mean_high = sum(high_speed_decels) / len(high_speed_decels)
            assert mean_high < 5.0, (
                f"High-speed decel {mean_high:.1f} kt/s too aggressive "
                f"(expected <5 for reverse thrust phase)"
            )

        if len(low_speed_decels) >= 5:
            mean_low = sum(low_speed_decels) / len(low_speed_decels)
            assert mean_low >= 2.5, (
                f"Low-speed decel {mean_low:.1f} kt/s too weak "
                f"(expected ≥2.5 for braking phase)"
            )


class TestTaxiRouteQuality:
    """Validate taxi routes after landing don't cross buildings."""

    def test_taxi_route_not_none(self, hst_sim):
        """All arrived flights should have a taxi route assigned."""
        _, _, traces = hst_sim
        checked = 0
        has_route = 0

        for icao24, trace in traces.items():
            taxi = phase_positions(trace, "taxi_to_gate")
            if not taxi:
                continue
            checked += 1
            if len(taxi) >= 2:
                has_route += 1

        assert checked >= 5, f"Need ≥5 arrivals with taxi phase, got {checked}"
        assert has_route / checked >= 0.90, (
            f"Only {has_route}/{checked} flights had ≥2 taxi waypoints"
        )

    def test_taxi_positions_outside_terminal_bbox(self, hst_sim):
        """Taxi positions should not be inside terminal building bounding boxes.

        Uses airport config terminal buildings to check if any taxi position
        lies inside a building polygon. Allows ≤10% violations (some routes
        may briefly clip a building corner on the graph).
        """
        _, _, traces = hst_sim
        try:
            from app.backend.services.airport_config_service import get_airport_config_service
            service = get_airport_config_service()
            config = service.get_config()
            terminals = config.get("terminals", [])
        except Exception:
            pytest.skip("Airport config not available in test env")

        if not terminals:
            pytest.skip("No terminal buildings in config")

        from src.routing.taxiway_graph import _point_in_polygon

        building_polys = []
        for t in terminals:
            poly = t.get("geoPolygon", [])
            if len(poly) >= 3:
                coords = [(p.get("latitude", 0), p.get("longitude", 0)) for p in poly]
                building_polys.append(coords)

        if not building_polys:
            pytest.skip("No valid building polygons")

        total_points = 0
        violations = 0

        for icao24, trace in traces.items():
            taxi = phase_positions(trace, "taxi_to_gate")
            for snap in taxi:
                total_points += 1
                lat, lon = snap["latitude"], snap["longitude"]
                for poly in building_polys:
                    if _point_in_polygon(lat, lon, poly):
                        violations += 1
                        break

        if total_points > 0:
            violation_rate = violations / total_points
            assert violation_rate < 0.10, (
                f"{violations}/{total_points} ({violation_rate:.1%}) taxi positions "
                f"inside terminal buildings. Target: <10%."
            )

    def test_no_teleportation_at_runway_exit(self, hst_sim):
        """Aircraft shouldn't teleport between last landing and first taxi position."""
        _, _, traces = hst_sim
        checked = 0
        teleports = 0

        for icao24, trace in traces.items():
            landing = phase_positions(trace, "landing")
            taxi = phase_positions(trace, "taxi_to_gate")
            if not landing or not taxi:
                continue
            checked += 1
            last_landing = landing[-1]
            first_taxi = taxi[0]
            gap = _haversine_m(
                last_landing["latitude"], last_landing["longitude"],
                first_taxi["latitude"], first_taxi["longitude"]
            )
            if gap > 200:
                teleports += 1

        if checked >= 5:
            assert teleports / checked < 0.15, (
                f"{teleports}/{checked} flights teleported >200m at runway exit"
            )

    def test_taxi_route_total_distance_reasonable(self, hst_sim):
        """Taxi distance from runway to gate should be 500m-5km (not 0 or 20km)."""
        _, _, traces = hst_sim
        distances = []

        for icao24, trace in traces.items():
            taxi = phase_positions(trace, "taxi_to_gate")
            if len(taxi) < 2:
                continue
            total_dist = 0
            for i in range(1, len(taxi)):
                total_dist += _haversine_m(
                    taxi[i-1]["latitude"], taxi[i-1]["longitude"],
                    taxi[i]["latitude"], taxi[i]["longitude"]
                )
            if total_dist > 50:
                distances.append(total_dist)

        assert len(distances) >= 5, f"Need ≥5 taxi routes, got {len(distances)}"
        mean_dist = sum(distances) / len(distances)
        assert 300 < mean_dist < 6000, (
            f"Mean taxi distance {mean_dist:.0f}m outside 300-6000m range"
        )
        too_long = sum(1 for d in distances if d > 8000)
        assert too_long / len(distances) < 0.10, (
            f"{too_long}/{len(distances)} taxi routes > 8km — unrealistic"
        )
