"""Automated landing centerline validation across multiple airports.

Runs a short simulation for each airport, extracts all APPROACHING→LANDING
transitions, and validates that every aircraft lands within acceptable
lateral offset from the runway centerline. Catches go-around regression
where aircraft land off-runway after re-entering approach.
"""

import math
import warnings
from datetime import datetime, timezone

import pytest

from src.simulation.config import SimulationConfig
from src.simulation.engine import SimulationEngine


VALIDATION_AIRPORTS = [
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

MAX_LATERAL_OFFSET_DEG = 0.006  # ~666m — tolerates minor origin-position artifacts


def _reset_all_module_state():
    """Reset all module-level caches that persist between airports."""
    import app.backend.services.airport_config_service as _acs
    _acs._service_instance = None

    import src.ingestion._approach_departure as _ad
    _ad._cached_osm_primary_runway = None
    _ad._osm_primary_runway_resolved = False
    _ad._osm_runway_config_id = None
    _ad._approach_waypoints_cache.clear()

    import src.ingestion.fallback as _fb
    if hasattr(_fb, '_flight_states'):
        _fb._flight_states.clear()
    if hasattr(_fb, '_gate_states'):
        _fb._gate_states.clear()


def _lateral_offset(lat: float, lon: float, thr_lat: float, thr_lon: float, rwy_heading: float) -> float:
    """Perpendicular distance from runway extended centerline in degrees."""
    dlat = lat - thr_lat
    dlon = (lon - thr_lon) * math.cos(math.radians(thr_lat))
    hdg_rad = math.radians(rwy_heading)
    rwy_dlat = math.cos(hdg_rad)
    rwy_dlon = math.sin(hdg_rad)
    return abs(dlat * rwy_dlon - dlon * rwy_dlat)


def _run_simulation(iata: str, icao: str, lat: float, lon: float):
    """Run simulation for a single airport with full state isolation."""
    from app.backend.services.airport_config_service import get_airport_config_service
    from src.ingestion.fallback import set_airport_center
    from src.ingestion._approach_departure import _get_runway_threshold, _get_runway_heading

    _reset_all_module_state()

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

    rwy_heading = _get_runway_heading()
    rwy_threshold = _get_runway_threshold()

    return recorder, rwy_heading, rwy_threshold


@pytest.mark.parametrize(
    "icao,iata,lat,lon",
    VALIDATION_AIRPORTS,
    ids=[a[0] for a in VALIDATION_AIRPORTS],
)
def test_all_landings_on_centerline(icao, iata, lat, lon):
    """Every APPROACHING→LANDING transition is near the runway centerline."""
    recorder, rwy_heading, rwy_threshold = _run_simulation(iata, icao, lat, lon)

    if rwy_heading is None or rwy_threshold is None:
        pytest.skip(f"No runway data for {icao}")

    thr_lat, thr_lon = rwy_threshold[1], rwy_threshold[0]

    all_landings = [
        pt for pt in recorder.phase_transitions
        if pt["to_phase"] == "landing"
    ]

    if not all_landings:
        pytest.skip(f"No landings recorded for {icao}")

    # Use all landings — the lateral offset check itself catches misaligned ones
    landings = all_landings

    failures = []
    for landing in landings:
        offset = _lateral_offset(
            landing["latitude"], landing["longitude"],
            thr_lat, thr_lon, rwy_heading,
        )
        if offset > MAX_LATERAL_OFFSET_DEG:
            failures.append(
                f"  {landing['callsign']}: lateral={offset:.4f}deg "
                f"({offset * 111_000:.0f}m) at "
                f"({landing['latitude']:.4f}, {landing['longitude']:.4f}) "
                f"alt={landing['altitude']:.0f}ft"
            )

    assert not failures, (
        f"{icao}: {len(failures)}/{len(landings)} landings off-centerline "
        f"(threshold {MAX_LATERAL_OFFSET_DEG}deg = {MAX_LATERAL_OFFSET_DEG * 111_000:.0f}m):\n"
        + "\n".join(failures)
    )


@pytest.mark.parametrize(
    "icao,iata,lat,lon",
    VALIDATION_AIRPORTS,
    ids=[a[0] for a in VALIDATION_AIRPORTS],
)
def test_go_around_landings_on_centerline(icao, iata, lat, lon):
    """Go-around flights specifically must also land on centerline."""
    recorder, rwy_heading, rwy_threshold = _run_simulation(iata, icao, lat, lon)

    if rwy_heading is None or rwy_threshold is None:
        pytest.skip(f"No runway data for {icao}")

    thr_lat, thr_lon = rwy_threshold[1], rwy_threshold[0]

    go_around_flights = set()
    for pt in recorder.phase_transitions:
        if pt["from_phase"] == "approaching" and pt["to_phase"] == "enroute":
            go_around_flights.add(pt["icao24"])

    ga_landings = [
        pt for pt in recorder.phase_transitions
        if pt["to_phase"] == "landing"
        and pt["icao24"] in go_around_flights
    ]

    if not ga_landings:
        warnings.warn(f"{icao}: no go-around landings recorded (seed=42)")
        return

    failures = []
    for landing in ga_landings:
        offset = _lateral_offset(
            landing["latitude"], landing["longitude"],
            thr_lat, thr_lon, rwy_heading,
        )
        if offset > MAX_LATERAL_OFFSET_DEG:
            failures.append(
                f"  {landing['callsign']}: lateral={offset:.4f}deg "
                f"({offset * 111_000:.0f}m) at "
                f"({landing['latitude']:.4f}, {landing['longitude']:.4f}) "
                f"alt={landing['altitude']:.0f}ft"
            )

    assert not failures, (
        f"{icao}: {len(failures)}/{len(ga_landings)} go-around landings off-centerline "
        f"(threshold {MAX_LATERAL_OFFSET_DEG}deg = {MAX_LATERAL_OFFSET_DEG * 111_000:.0f}m):\n"
        + "\n".join(failures)
    )
