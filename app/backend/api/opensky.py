"""OpenSky Network API endpoints for live ADS-B flight data and recorded replays."""

import logging
import os
from datetime import datetime

from fastapi import APIRouter, HTTPException

from app.backend.services.opensky_service import (
    get_opensky_service,
    determine_flight_phase,
    M_TO_FT,
    MS_TO_KTS,
    MS_TO_FTMIN,
)
from app.backend.services.airport_config_service import get_airport_config_service

logger = logging.getLogger(__name__)

opensky_router = APIRouter(prefix="/api/opensky", tags=["opensky"])


def _get_airport_center() -> tuple[float, float]:
    """Get the current airport's center coordinates."""
    service = get_airport_config_service()
    config = service.get_config()

    # Try reference point from config
    ref = config.get("reference_point") or config.get("referencePoint")
    if ref and "latitude" in ref and "longitude" in ref:
        return float(ref["latitude"]), float(ref["longitude"])

    # Fall back to converter reference
    converter = getattr(service, "_converter", None)
    if converter:
        return converter.reference_lat, converter.reference_lon

    raise HTTPException(status_code=503, detail="No airport loaded — cannot determine location")


@opensky_router.get("/flights")
async def get_opensky_flights() -> dict:
    """Fetch live flights from OpenSky Network for the current airport.

    Returns flights in the same schema as /api/flights for easy frontend consumption.
    """
    lat, lon = _get_airport_center()
    opensky = get_opensky_service()
    flights = await opensky.fetch_flights(lat, lon)

    return {
        "flights": flights,
        "count": len(flights),
        "data_source": "opensky",
    }


@opensky_router.get("/status")
async def get_opensky_status() -> dict:
    """Return OpenSky service health and last fetch info."""
    opensky = get_opensky_service()
    return opensky.get_status()


@opensky_router.get("/diag")
async def opensky_diagnostic() -> dict:
    """Diagnostic endpoint to test OpenSky API connectivity from this environment.

    Does DNS, connectivity, and API tests. Returns detailed results for debugging.
    Always available (no DEBUG_MODE requirement) for deployment debugging.
    """
    import httpx
    import socket
    import time

    lat, lon = _get_airport_center()
    radius = 0.5
    params = {
        "lamin": lat - radius,
        "lamax": lat + radius,
        "lomin": lon - radius,
        "lomax": lon + radius,
    }

    result: dict = {
        "airport_center": {"lat": lat, "lon": lon},
        "bounding_box": params,
        "api_url": "https://opensky-network.org/api/states/all",
    }

    # Step 1: DNS resolution test
    try:
        t0 = time.monotonic()
        addrs = socket.getaddrinfo("opensky-network.org", 443)
        dns_ms = (time.monotonic() - t0) * 1000
        result["dns"] = {
            "resolved": True,
            "elapsed_ms": round(dns_ms, 1),
            "addresses": list({addr[4][0] for addr in addrs})[:3],
        }
    except Exception as e:
        dns_ms = (time.monotonic() - t0) * 1000
        result["dns"] = {
            "resolved": False,
            "elapsed_ms": round(dns_ms, 1),
            "error": f"{type(e).__name__}: {e}",
        }

    # Step 2: General egress test (known-good host)
    try:
        t0 = time.monotonic()
        async with httpx.AsyncClient(timeout=5.0) as client:
            egress_resp = await client.get("https://httpbin.org/status/200")
        egress_ms = (time.monotonic() - t0) * 1000
        result["egress_test"] = {
            "host": "httpbin.org",
            "status": egress_resp.status_code,
            "elapsed_ms": round(egress_ms, 1),
        }
    except Exception as e:
        egress_ms = (time.monotonic() - t0) * 1000
        result["egress_test"] = {
            "host": "httpbin.org",
            "error": f"{type(e).__name__}: {e}",
            "elapsed_ms": round(egress_ms, 1),
        }

    # Step 3: OpenSky API test
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                "https://opensky-network.org/api/states/all",
                params=params,
            )
        elapsed_ms = (time.monotonic() - t0) * 1000

        result["http_status"] = response.status_code
        result["elapsed_ms"] = round(elapsed_ms, 1)
        result["response_headers"] = dict(response.headers)

        if response.status_code == 200:
            data = response.json()
            states = data.get("states") or []
            result["raw_time"] = data.get("time")
            result["state_count"] = len(states)
            if states:
                result["sample_state"] = states[0]
        else:
            result["response_body"] = response.text[:500]

    except Exception as e:
        elapsed_ms = (time.monotonic() - t0) * 1000
        result["error"] = f"{type(e).__name__}: {e}"
        result["elapsed_ms"] = round(elapsed_ms, 1)

    # Step 4: Service status + credential info
    opensky = get_opensky_service()
    result["service_status"] = opensky.get_status()

    logger.info("OpenSky diag: dns=%s, egress=%s, api_status=%s, states=%s, elapsed=%.0fms",
                result.get("dns", {}).get("resolved"),
                result.get("egress_test", {}).get("status"),
                result.get("http_status"), result.get("state_count"),
                result.get("elapsed_ms", 0))

    return result


# ── Recorded data endpoints ──────────────────────────────────────────────


_UC_CATALOG = os.getenv("DATABRICKS_CATALOG", "serverless_stable_3n0ihb_catalog")
_UC_SCHEMA = os.getenv("DATABRICKS_SCHEMA", "airport_digital_twin")
_RECORDINGS_TABLE = f"{_UC_CATALOG}.{_UC_SCHEMA}.opensky_states_raw"


def _get_delta_connection():
    """Get a Databricks SQL connection for querying recorded data."""
    from app.backend.services.delta_service import DeltaService
    svc = DeltaService()
    if not svc.is_available:
        raise HTTPException(status_code=503, detail="Databricks SQL not available")
    return svc._get_connection()


@opensky_router.get("/recordings")
async def list_recordings() -> dict:
    """List available recorded OpenSky data sessions, grouped by airport and date.

    Each recording represents a collection session with real ADS-B data
    captured from the OpenSky Network and stored in the lakehouse.
    """
    import threading

    result: list = []
    error: list = []

    def _query():
        try:
            conn = _get_delta_connection()
            with conn.cursor() as cur:
                cur.execute(f"""
                    SELECT
                        airport_icao,
                        CAST(collection_date AS STRING) AS date,
                        COUNT(DISTINCT icao24) AS aircraft_count,
                        COUNT(*) AS state_count,
                        MIN(collection_time) AS first_seen,
                        MAX(collection_time) AS last_seen
                    FROM {_RECORDINGS_TABLE}
                    GROUP BY airport_icao, collection_date
                    ORDER BY collection_date DESC, airport_icao
                """)
                rows = cur.fetchall()
                cols = [d[0] for d in cur.description]
            conn.close()
            result.append([dict(zip(cols, row)) for row in rows])
        except Exception as e:
            error.append(e)

    thread = threading.Thread(target=_query, daemon=True)
    thread.start()
    thread.join(timeout=15)

    if error:
        logger.warning("Failed to query recordings: %s", error[0])
        raise HTTPException(status_code=503, detail=f"Failed to query recordings: {error[0]}")
    if not result:
        logger.warning("Timed out querying recordings")
        raise HTTPException(status_code=504, detail="Query timed out")

    recordings = []
    for row in result[0]:
        first = row["first_seen"]
        last = row["last_seen"]
        if isinstance(first, datetime) and isinstance(last, datetime):
            duration_min = round((last - first).total_seconds() / 60, 1)
            first_str = first.isoformat()
            last_str = last.isoformat()
        else:
            duration_min = 0
            first_str = str(first)
            last_str = str(last)

        recordings.append({
            "airport_icao": row["airport_icao"],
            "date": row["date"],
            "aircraft_count": row["aircraft_count"],
            "state_count": row["state_count"],
            "first_seen": first_str,
            "last_seen": last_str,
            "duration_minutes": duration_min,
            "data_source": "opensky_live",
        })

    return {"recordings": recordings, "count": len(recordings)}


@opensky_router.get("/recordings/{airport_icao}/{date}")
async def get_recording_data(airport_icao: str, date: str) -> dict:
    """Load a recorded OpenSky session as frame-based replay data.

    Returns data in the same format as /api/simulation/data/ so the frontend
    replay engine can play it back unchanged. Each frame is a collection_time
    snapshot with all aircraft positions at that moment.

    This is real ADS-B data from the OpenSky Network, not simulated.
    """
    import threading

    # Validate date format
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid date format: {date} (expected YYYY-MM-DD)")

    airport = airport_icao.upper()
    result: list = []
    error: list = []

    def _query():
        try:
            conn = _get_delta_connection()
            with conn.cursor() as cur:
                cur.execute(f"""
                    SELECT
                        icao24, callsign, origin_country,
                        latitude, longitude,
                        baro_altitude, geo_altitude,
                        velocity, true_track, vertical_rate,
                        on_ground, collection_time
                    FROM {_RECORDINGS_TABLE}
                    WHERE airport_icao = '{airport}'
                      AND collection_date = '{date}'
                    ORDER BY collection_time, icao24
                """)
                rows = cur.fetchall()
                cols = [d[0] for d in cur.description]
            conn.close()
            result.append([dict(zip(cols, row)) for row in rows])
        except Exception as e:
            error.append(e)

    thread = threading.Thread(target=_query, daemon=True)
    thread.start()
    thread.join(timeout=30)

    if error:
        raise HTTPException(status_code=503, detail=f"Query failed: {error[0]}")
    if not result:
        raise HTTPException(status_code=504, detail="Query timed out")
    if not result[0]:
        raise HTTPException(status_code=404, detail=f"No recorded data for {airport} on {date}")

    rows = result[0]

    # Group by collection_time into frames, converting to simulation snapshot format
    frames: dict[str, list] = {}
    unique_aircraft: set[str] = set()

    for row in rows:
        ct = row["collection_time"]
        ts = ct.isoformat() if isinstance(ct, datetime) else str(ct)

        icao24 = row["icao24"]
        unique_aircraft.add(icao24)

        baro_alt_m = row["baro_altitude"] or 0.0
        velocity_ms = row["velocity"] or 0.0
        vrate_ms = row["vertical_rate"] or 0.0
        on_ground = bool(row["on_ground"])

        altitude_ft = baro_alt_m * M_TO_FT
        velocity_kts = velocity_ms * MS_TO_KTS
        vrate_ftmin = vrate_ms * MS_TO_FTMIN

        phase = determine_flight_phase(altitude_ft, vrate_ftmin, on_ground)

        snap = {
            "time": ts,
            "icao24": icao24,
            "callsign": (row["callsign"] or icao24).strip(),
            "latitude": row["latitude"],
            "longitude": row["longitude"],
            "altitude": altitude_ft,
            "velocity": velocity_kts,
            "heading": row["true_track"],
            "phase": phase,
            "on_ground": on_ground,
            "aircraft_type": "",
            "vertical_rate": vrate_ftmin,
        }

        if ts not in frames:
            frames[ts] = []
        frames[ts].append(snap)

    sorted_timestamps = sorted(frames.keys())

    return {
        "config": {
            "airport": airport,
            "source": "opensky_recorded",
            "date": date,
        },
        "summary": {
            "total_flights": len(unique_aircraft),
            "data_source": "opensky_live",
            "scenario_name": f"Recorded ADS-B — {airport} {date}",
        },
        "schedule": [],
        "frames": {t: frames[t] for t in sorted_timestamps},
        "frame_timestamps": sorted_timestamps,
        "frame_count": len(sorted_timestamps),
        "phase_transitions": [],
        "gate_events": [],
        "scenario_events": [],
    }
