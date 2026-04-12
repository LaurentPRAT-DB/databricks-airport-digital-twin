"""OpenSky Network API endpoints for live ADS-B flight data and recorded replays."""

import logging
import os
import threading
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException

from app.backend.services.opensky_service import (
    get_opensky_service,
    determine_flight_phase,
    enrich_origins_opensky,
    enrich_origins_heading,
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


def _derive_schedule_from_recording(
    inferrer: Any,
    enrichment: dict[str, Any],
    origins: dict[str, tuple[str | None, str | None]],
    airport_icao: str,
    sorted_timestamps: list[str],
    frames: dict[str, list[dict]],
) -> list[dict]:
    """Derive a flight schedule from observed aircraft lifecycles in recorded data.

    Extracts real arrival/departure times, gate assignments, and origin/destination
    from the inferred events. Only fills gaps with heuristics when data is missing.
    """
    if not sorted_timestamps:
        return []

    # Build lookup structures from events
    gate_by_aircraft: dict[str, str] = {}  # icao24 -> last assigned gate
    gate_times: dict[str, list[tuple[str, str, str]]] = {}  # icao24 -> [(time, gate, event_type)]

    for ge in enrichment["gate_events"]:
        icao24 = ge["icao24"]
        if icao24 not in gate_times:
            gate_times[icao24] = []
        gate_times[icao24].append((ge["time"], ge["gate"], ge["event_type"]))
        if ge["event_type"] in ("assign", "occupy"):
            gate_by_aircraft[icao24] = ge["gate"]

    # Phase transition lookup: icao24 -> [(time, from_phase, to_phase)]
    transitions_by_aircraft: dict[str, list[tuple[str, str, str]]] = {}
    for pt in enrichment["phase_transitions"]:
        icao24 = pt["icao24"]
        if icao24 not in transitions_by_aircraft:
            transitions_by_aircraft[icao24] = []
        transitions_by_aircraft[icao24].append((pt["time"], pt["from_phase"], pt["to_phase"]))

    # First and last seen per aircraft (from frames)
    first_seen: dict[str, dict] = {}
    last_seen: dict[str, dict] = {}
    for ts in sorted_timestamps:
        for snap in frames[ts]:
            icao24 = snap["icao24"]
            if icao24 not in first_seen:
                first_seen[icao24] = snap
            last_seen[icao24] = snap

    schedule: list[dict] = []

    for icao24, tracker in inferrer._trackers.items():
        callsign = tracker.callsign or icao24
        first = first_seen.get(icao24)
        last = last_seen.get(icao24)
        if not first or not last:
            continue

        origin_info = origins.get(icao24, (None, None))
        gate = gate_by_aircraft.get(icao24)
        transitions = transitions_by_aircraft.get(icao24, [])

        # Determine if this aircraft arrived and/or departed during the recording
        first_phase = first.get("phase", "unknown")
        last_phase = last.get("phase", "unknown")

        saw_landing = any(tp == "landing" or tp == "taxi_to_gate" for _, _, tp in transitions)
        saw_takeoff = any(tp == "takeoff" for _, _, tp in transitions)
        was_airborne_initially = first_phase in ("airborne", "enroute", "approaching", "landing", "departing")
        was_on_ground_initially = first_phase in ("parked", "taxi_to_gate", "taxi_to_runway")

        # Find key timestamps from transitions
        arrival_time = None
        departure_time = None

        # Arrival: first landing or taxi_to_gate transition, or first seen if already on ground arriving
        for t, _, to_phase in transitions:
            if to_phase in ("landing", "taxi_to_gate") and arrival_time is None:
                arrival_time = t
                break
        if arrival_time is None and was_airborne_initially:
            arrival_time = first.get("time")

        # Departure: last takeoff transition, or gate release followed by takeoff
        for t, _, to_phase in reversed(transitions):
            if to_phase == "takeoff":
                departure_time = t
                break

        # Create arrival schedule entry
        if saw_landing or was_airborne_initially:
            sched_time = arrival_time or first.get("time")
            schedule.append({
                "flight_number": callsign,
                "airline": _extract_airline(callsign),
                "airline_code": _extract_airline_code(callsign),
                "origin": origin_info[0],
                "destination": airport_icao,
                "scheduled_time": sched_time,
                "estimated_time": sched_time,
                "actual_time": arrival_time,
                "gate": gate,
                "status": "Landed",
                "delay_minutes": 0,
                "delay_reason": None,
                "aircraft_type": first.get("aircraft_type", ""),
                "flight_type": "arrival",
            })

        # Create departure schedule entry
        if saw_takeoff:
            sched_time = departure_time or last.get("time")
            schedule.append({
                "flight_number": callsign,
                "airline": _extract_airline(callsign),
                "airline_code": _extract_airline_code(callsign),
                "origin": airport_icao,
                "destination": origin_info[1],
                "scheduled_time": sched_time,
                "estimated_time": sched_time,
                "actual_time": departure_time,
                "gate": gate,
                "status": "Departed",
                "delay_minutes": 0,
                "delay_reason": None,
                "aircraft_type": last.get("aircraft_type", ""),
                "flight_type": "departure",
            })

        # Aircraft observed only parked (no arrival or departure seen)
        if not saw_landing and not was_airborne_initially and not saw_takeoff:
            sched_time = first.get("time")
            schedule.append({
                "flight_number": callsign,
                "airline": _extract_airline(callsign),
                "airline_code": _extract_airline_code(callsign),
                "origin": origin_info[0],
                "destination": origin_info[1],
                "scheduled_time": sched_time,
                "estimated_time": sched_time,
                "actual_time": sched_time,
                "gate": gate,
                "status": "On Time",
                "delay_minutes": 0,
                "delay_reason": None,
                "aircraft_type": first.get("aircraft_type", ""),
                "flight_type": "arrival",
            })

    logger.info("Derived %d schedule entries from recording %s/%s", len(schedule), airport_icao, sorted_timestamps[0][:10] if sorted_timestamps else "?")
    return schedule


def _extract_airline(callsign: str) -> str:
    """Extract airline name prefix from callsign (e.g. 'UAL123' -> 'UAL')."""
    prefix = ""
    for ch in callsign:
        if ch.isalpha():
            prefix += ch
        else:
            break
    return prefix or callsign


def _extract_airline_code(callsign: str) -> str:
    """Extract airline ICAO code from callsign (first 3 alpha chars)."""
    return _extract_airline(callsign)[:3]


def _persist_recording_to_lakebase(
    enrichment: dict[str, Any],
    enriched_snapshots: list[dict],
    schedule: list[dict],
    origins: dict[str, tuple[str | None, str | None]],
    airport_icao: str,
    date: str,
) -> None:
    """Persist enriched recording data to Lakebase for ML training.

    Runs synchronously — intended to be called from a background thread.
    """
    from app.backend.services.lakebase_service import get_lakebase_service

    lakebase = get_lakebase_service()
    if not lakebase.is_available:
        logger.info("Lakebase not available, skipping recording persistence")
        return

    session_id = f"recorded-{airport_icao}-{date}"

    # 1. Persist enriched position snapshots
    snapshots_for_lakebase = [
        {
            "icao24": s["icao24"],
            "callsign": s.get("callsign"),
            "latitude": s.get("latitude"),
            "longitude": s.get("longitude"),
            "altitude": s.get("altitude"),
            "velocity": s.get("velocity"),
            "heading": s.get("heading"),
            "vertical_rate": s.get("vertical_rate"),
            "on_ground": s.get("on_ground"),
            "flight_phase": s.get("phase"),
            "aircraft_type": s.get("aircraft_type"),
            "assigned_gate": s.get("assigned_gate"),
            "origin_airport": origins.get(s["icao24"], (None, None))[0],
            "destination_airport": origins.get(s["icao24"], (None, None))[1],
            "data_source": "opensky_recorded",
            "snapshot_time": s.get("time"),
        }
        for s in enriched_snapshots
    ]
    snap_count = lakebase.insert_flight_snapshots(snapshots_for_lakebase, session_id, airport_icao)

    # 2. Persist gate events
    gate_events_for_lakebase = [
        {**ge, "event_time": ge["time"]}
        for ge in enrichment["gate_events"]
    ]
    gate_count = lakebase.insert_gate_events(gate_events_for_lakebase, session_id, airport_icao)

    # 3. Persist phase transitions
    transitions_for_lakebase = [
        {**pt, "event_time": pt["time"]}
        for pt in enrichment["phase_transitions"]
    ]
    trans_count = lakebase.insert_phase_transitions(transitions_for_lakebase, session_id, airport_icao)

    # 4. Persist derived schedule
    sched_count = lakebase.upsert_schedule(schedule, airport_icao=airport_icao)

    logger.info(
        "Recording %s/%s persisted to Lakebase: %d snapshots, %d gate events, "
        "%d phase transitions, %d schedule entries",
        airport_icao, date, snap_count, gate_count, trans_count, sched_count,
    )


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

    logger.info("Recordings list: %d sessions found", len(recordings))
    return {"recordings": recordings, "count": len(recordings)}


def _weather_snapshots_to_scenario_events(weather_snapshots: list[dict]) -> list[dict]:
    """Convert METAR weather snapshots into scenario_events for PlaybackBar.

    Only emits an event when conditions *change* from the previous snapshot,
    avoiding duplicate events for sustained weather. Noteworthy conditions:
    - Flight category transitions (IFR, LIFR, MVFR)
    - High wind or gusts (>= 25 kts)
    - Low visibility (< 3 SM)
    - Low ceiling (< 1000 ft)
    """
    events: list[dict] = []
    prev_category: str | None = None

    for snap in weather_snapshots:
        category = snap.get("flight_category", "VFR")
        time_str = snap.get("time", "")

        # Only emit when category changes
        if category == prev_category:
            continue
        prev_category = category

        # VFR with no noteworthy conditions — skip
        if category == "VFR":
            wind = snap.get("wind_speed_kts") or 0
            gust = snap.get("wind_gust_kts") or 0
            if wind < 25 and gust < 25:
                # Emit a "return to VFR" event if we had a prior non-VFR event
                if events:
                    events.append({
                        "time": time_str,
                        "event_type": "weather",
                        "description": "VFR conditions restored",
                    })
                continue

        # Build description from available data
        parts: list[str] = []
        vis = snap.get("visibility_sm")
        if vis is not None and vis < 3:
            parts.append(f"visibility {vis} SM")

        raw = snap.get("raw_metar", "")
        # Extract ceiling from raw METAR (BKN/OVC/VV followed by 3-digit hundreds of feet)
        import re
        ceiling_match = re.search(r"(BKN|OVC|VV)(\d{3})", raw)
        ceiling_ft: int | None = None
        if ceiling_match:
            ceiling_ft = int(ceiling_match.group(2)) * 100
            if ceiling_ft < 1000:
                parts.append(f"ceiling {ceiling_ft} ft")

        wind = snap.get("wind_speed_kts") or 0
        gust = snap.get("wind_gust_kts") or 0
        if gust >= 25:
            parts.append(f"wind {wind} G{gust} kts")
        elif wind >= 25:
            parts.append(f"wind {wind} kts")

        detail = f": {', '.join(parts)}" if parts else ""
        description = f"{category} conditions{detail}"

        event: dict = {
            "time": time_str,
            "event_type": "weather",
            "description": description,
        }
        # Add structured details for consistency with simulation events
        if vis is not None:
            event["visibility_sm"] = vis
        if ceiling_ft is not None:
            event["ceiling_ft"] = ceiling_ft
        if wind:
            event["wind_speed_kts"] = wind
        if gust:
            event["wind_gust_kts"] = gust
        event["flight_category"] = category

        events.append(event)

    return events


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
                        on_ground, collection_time,
                        aircraft_type, airline_icao
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
    # Deduplicate per (collection_time, icao24) — APPEND-only ingestion can create dupes
    frames: dict[str, list] = {}
    unique_aircraft: set[str] = set()
    seen_in_frame: dict[str, set[str]] = {}

    for row in rows:
        ct = row["collection_time"]
        ts = ct.isoformat() if isinstance(ct, datetime) else str(ct)

        icao24 = row["icao24"]
        if ts not in seen_in_frame:
            seen_in_frame[ts] = set()
        if icao24 in seen_in_frame[ts]:
            continue  # skip duplicate icao24 within same frame
        seen_in_frame[ts].add(icao24)
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
            "aircraft_type": row.get("aircraft_type") or "",
            "assigned_gate": None,
            "vertical_rate": vrate_ftmin,
        }

        if ts not in frames:
            frames[ts] = []
        frames[ts].append(snap)

    sorted_timestamps = sorted(frames.keys())

    # ── Aircraft type enrichment from OpenSky aircraft database ────────
    from app.backend.services.aircraft_db import get_aircraft_database

    aircraft_db = get_aircraft_database()
    try:
        await aircraft_db.ensure_loaded()
    except Exception as e:
        logger.warning("Aircraft database load failed: %s", e)

    if aircraft_db.loaded:
        enriched_types = 0
        for ts_key in sorted_timestamps:
            for snap in frames[ts_key]:
                if not snap.get("aircraft_type"):
                    typecode, _ = aircraft_db.lookup(snap["icao24"])
                    if typecode:
                        snap["aircraft_type"] = typecode
                        enriched_types += 1
        if enriched_types:
            logger.info("Enriched aircraft_type for %d snapshots from OpenSky DB", enriched_types)

    # ── Historical METAR weather enrichment ────────────────────────────
    from app.backend.services.metar_history import fetch_historical_metar
    from datetime import date as date_type

    target_date = date_type.fromisoformat(date)
    weather_snapshots: list[dict] = []
    try:
        weather_snapshots = await fetch_historical_metar(airport, target_date)
    except Exception as e:
        logger.warning("Historical METAR fetch failed for %s/%s: %s", airport, date, e)

    # ── Event inference: derive gate_events + phase_transitions from positions ──
    from src.inference.opensky_events import OpenSkyEventInferrer

    try:
        service = get_airport_config_service()
        config = service.get_config()
        gates = config.get("gates", [])
    except Exception:
        gates = []

    inferrer = OpenSkyEventInferrer(gates)
    for ts in sorted_timestamps:
        inferrer.process_frame(ts, frames[ts])
    enrichment = inferrer.get_results()

    # Update snapshots with inferred gate assignments + snap parked positions
    gate_by_aircraft: dict[str, str] = {}
    for ge in enrichment["gate_events"]:
        if ge["event_type"] in ("assign", "occupy"):
            gate_by_aircraft[ge["icao24"]] = ge["gate"]
        elif ge["event_type"] == "release":
            gate_by_aircraft.pop(ge["icao24"], None)

    # Build gate coordinate lookup for position snapping
    gate_coords: dict[str, tuple[float, float]] = {}
    for g in gates:
        gid = g.get("ref") or g.get("id") or ""
        geo = g.get("geo", {})
        glat, glon = geo.get("latitude"), geo.get("longitude")
        if gid and glat is not None and glon is not None:
            gate_coords[str(gid)] = (float(glat), float(glon))

    for ts_key in sorted_timestamps:
        for snap in frames[ts_key]:
            gate = gate_by_aircraft.get(snap["icao24"])
            if gate:
                snap["assigned_gate"] = gate
                # Snap parked aircraft to gate position (ADS-B ground positions are inaccurate)
                if snap.get("on_ground") and float(snap.get("velocity", 0) or 0) < 5 and gate in gate_coords:
                    snap["latitude"], snap["longitude"] = gate_coords[gate]

    # ── Origin/destination enrichment (cascading) ─────────────────────
    # Collect first-seen snapshot per aircraft for heading heuristic
    aircraft_first_seen: dict[str, dict] = {}
    for ts_key in sorted_timestamps:
        for snap in frames[ts_key]:
            if snap["icao24"] not in aircraft_first_seen:
                aircraft_first_seen[snap["icao24"]] = snap

    origins: dict[str, tuple[str | None, str | None]] = {}

    # Level 1: OpenSky flights API (if reachable)
    if sorted_timestamps:
        try:
            begin_dt = datetime.fromisoformat(sorted_timestamps[0])
            end_dt = datetime.fromisoformat(sorted_timestamps[-1])
            begin_ts = int(begin_dt.timestamp())
            end_ts = int(end_dt.timestamp())
            api_results = await enrich_origins_opensky(unique_aircraft, begin_ts, end_ts)
            origins.update(api_results)
        except Exception as e:
            logger.warning("OpenSky flights API enrichment failed: %s", e)

    # Level 2: Heading-based heuristic for remaining aircraft
    remaining = {ic for ic in unique_aircraft if ic not in origins}
    if remaining:
        remaining_first_seen = {ic: aircraft_first_seen[ic] for ic in remaining if ic in aircraft_first_seen}
        heading_results = enrich_origins_heading(remaining_first_seen, lat, lon, airport)
        origins.update(heading_results)

    # Apply origins to all snapshots
    enriched_count = 0
    for ts_key in sorted_timestamps:
        for snap in frames[ts_key]:
            origin_info = origins.get(snap["icao24"])
            if origin_info:
                snap["origin_airport"] = origin_info[0]
                snap["destination_airport"] = origin_info[1]
                enriched_count += 1

    # ── Derive schedule from observed aircraft lifecycles ───────────────
    derived_schedule = _derive_schedule_from_recording(
        inferrer, enrichment, origins, airport, sorted_timestamps, frames,
    )

    logger.info(
        "Recording %s/%s: %d rows → %d frames, %d unique aircraft, "
        "%d phase transitions, %d gate events inferred, "
        "%d/%d aircraft origins resolved, %d schedule entries derived, "
        "%d weather snapshots",
        airport, date, len(rows), len(sorted_timestamps), len(unique_aircraft),
        len(enrichment["phase_transitions"]), len(enrichment["gate_events"]),
        len(origins), len(unique_aircraft), len(derived_schedule),
        len(weather_snapshots),
    )

    # ── Persist enriched data to Lakebase (background, fire-and-forget) ──
    enriched_snapshots = inferrer.get_enriched_snapshots()
    persist_thread = threading.Thread(
        target=_persist_recording_to_lakebase,
        args=(enrichment, enriched_snapshots, derived_schedule, origins, airport, date),
        daemon=True,
    )
    persist_thread.start()

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
        "schedule": derived_schedule,
        "frames": {t: frames[t] for t in sorted_timestamps},
        "frame_timestamps": sorted_timestamps,
        "frame_count": len(sorted_timestamps),
        "phase_transitions": enrichment["phase_transitions"],
        "gate_events": enrichment["gate_events"],
        "weather_snapshots": weather_snapshots,
        "scenario_events": _weather_snapshots_to_scenario_events(weather_snapshots),
        "time_window": {
            "start_time": sorted_timestamps[0] if sorted_timestamps else None,
            "end_time": sorted_timestamps[-1] if sorted_timestamps else None,
        },
    }
