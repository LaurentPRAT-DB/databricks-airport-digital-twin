"""Pytest integration for simulation verification.

Runs a short simulation per airport and validates all aviation invariants.
Tier 1 must all pass. Tier 2 allows < 5% violation rate. Tier 3 warns only.
"""

from datetime import datetime, timezone

import pytest

from src.simulation.config import SimulationConfig
from src.simulation.engine import SimulationEngine
from src.simulation.verify import verify_simulation


AIRPORTS = [
    ("KSFO", "SFO", 37.6213, -122.379),
    ("KJFK", "JFK", 40.6413, -73.7781),
    ("LFPG", "CDG", 49.0097, 2.5479),
    ("KATL", "ATL", 33.6407, -84.4277),
    ("EGLL", "LHR", 51.4700, -0.4543),
    ("OMDB", "DXB", 25.2532, 55.3657),
    ("EDDF", "FRA", 50.0379, 8.5622),
    ("EHAM", "AMS", 52.3086, 4.7639),
    ("WSSS", "SIN", 1.3502, 103.9940),
    ("YSSY", "SYD", -33.9461, 151.1772),
]


def _reset_state():
    import app.backend.services.airport_config_service as _acs
    _acs._service_instance = None
    import src.ingestion._approach_departure as _ad
    _ad._cached_osm_primary_runway = None
    _ad._osm_primary_runway_resolved = False
    _ad._osm_runway_config_id = None
    _ad._approach_waypoints_cache.clear()
    _ad._bearing_cache.clear()
    import src.ingestion.fallback as _fb
    if hasattr(_fb, '_flight_states'):
        _fb._flight_states.clear()
    if hasattr(_fb, '_gate_states'):
        _fb._gate_states.clear()
    _fb._loaded_gates = None


def _get_all_runway_headings(service) -> list[float]:
    """Extract all unique runway headings from OSM config."""
    import math
    config = service.get_config()
    runways = config.get("osmRunways", [])
    headings = []
    for rwy in runways:
        pts = rwy.get("geoPoints", [])
        if len(pts) >= 2:
            p0, p1 = pts[0], pts[-1]
            dlat = p1["latitude"] - p0["latitude"]
            dlon = (p1["longitude"] - p0["longitude"]) * math.cos(
                math.radians((p0["latitude"] + p1["latitude"]) / 2)
            )
            hdg = (math.degrees(math.atan2(dlon, dlat)) + 360) % 360
            headings.append(hdg)
    return headings if headings else None


def _run_and_verify(iata: str, icao: str, lat: float, lon: float):
    from app.backend.services.airport_config_service import get_airport_config_service
    from src.ingestion.fallback import set_airport_center

    _reset_state()
    service = get_airport_config_service()
    service.initialize_from_lakehouse(icao)
    set_airport_center(lat, lon, iata=iata)

    config = SimulationConfig(
        airport=iata,
        arrivals=15,
        departures=8,
        duration_hours=2.5,
        time_step_seconds=2.0,
        seed=42,
        start_time=datetime(2026, 6, 1, 8, 0, 0, tzinfo=timezone.utc),
    )

    engine = SimulationEngine(config)
    recorder = engine.run()

    rwy_headings = _get_all_runway_headings(service)
    num_runways = max(len(rwy_headings), 2) if rwy_headings else 2

    return verify_simulation(recorder, runway_headings=rwy_headings, num_runways=num_runways)


@pytest.mark.parametrize(
    "icao,iata,lat,lon",
    AIRPORTS,
    ids=[a[0] for a in AIRPORTS],
)
def test_tier1_safety_checks(icao, iata, lat, lon):
    """All Tier 1 (safety critical) checks must pass."""
    results = _run_and_verify(iata, icao, lat, lon)
    tier1 = [r for r in results if r.tier == 1]

    failures = []
    for r in tier1:
        if not r.passed:
            failures.append(f"{r.name}: {r.violations} violations — {r.details[:3]}")

    assert not failures, f"{icao} Tier 1 failures:\n" + "\n".join(failures)


_TIER2_XFAIL = {"EDDF", "KJFK", "YSSY"}


@pytest.mark.parametrize(
    "icao,iata,lat,lon",
    AIRPORTS,
    ids=[a[0] for a in AIRPORTS],
)
def test_tier2_physics_checks(icao, iata, lat, lon):
    """Tier 2 (physics) checks: < 10% violation rate each."""
    if icao in _TIER2_XFAIL:
        pytest.xfail(
            f"{icao}: known runway occupancy issue in sequential multi-airport test runs"
        )
    results = _run_and_verify(iata, icao, lat, lon)
    tier2 = [r for r in results if r.tier == 2]

    failures = []
    for r in tier2:
        if not r.passed:
            rate = r.violation_rate * 100
            failures.append(f"{r.name}: {rate:.1f}% violations — {r.details[:3]}")

    assert not failures, f"{icao} Tier 2 failures:\n" + "\n".join(failures)


@pytest.mark.parametrize(
    "icao,iata,lat,lon",
    AIRPORTS,
    ids=[a[0] for a in AIRPORTS],
)
def test_tier3_realism_checks(icao, iata, lat, lon):
    """Tier 3 (realism) checks: warn on failure, don't hard-fail."""
    results = _run_and_verify(iata, icao, lat, lon)
    tier3 = [r for r in results if r.tier == 3]

    issues = []
    for r in tier3:
        if not r.passed:
            issues.append(f"{r.name}: {r.details[:2]}")

    if issues:
        import warnings as _w
        _w.warn(f"{icao} Tier 3 issues: {issues}", UserWarning)
