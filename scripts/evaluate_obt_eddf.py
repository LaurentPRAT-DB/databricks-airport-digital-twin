#!/usr/bin/env python3
"""Evaluate OBT model predictions against real OpenSky ADS-B turnaround data.

Loads collected EDDF JSONL files, runs the OpenSkyEventInferrer to detect
gate occupy/release events, then compares observed turnaround durations
against the current OBT model predictions.

Usage:
    uv run python scripts/evaluate_obt_eddf.py
    uv run python scripts/evaluate_obt_eddf.py --data-dir data/opensky_raw --airport EDDF
    uv run python scripts/evaluate_obt_eddf.py --from-delta --days 7
"""

import argparse
import json
import logging
import math
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("evaluate_obt")

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.formats.osm.parser import OSMParser
from src.formats.osm.converter import OSMConverter
from src.formats.base import CoordinateConverter
from src.inference.opensky_events import OpenSkyEventInferrer
from src.ml.obt_model import OBTPredictor
from src.ml.obt_features import OBTFeatureSet, classify_aircraft

# m/s to knots conversion factor
MS_TO_KTS = 1.94384
# meters to feet
M_TO_FT = 3.28084


def load_jsonl_files(data_dir: Path, airport: str) -> list[dict]:
    """Load all JSONL files for an airport, sorted by collection_time."""
    pattern = f"{airport}_*.jsonl"
    files = sorted(data_dir.glob(pattern))
    if not files:
        logger.error("No files matching %s in %s", pattern, data_dir)
        return []

    records = []
    for f in files:
        with open(f) as fh:
            for line in fh:
                line = line.strip()
                if line:
                    records.append(json.loads(line))

    logger.info("Loaded %d records from %d files", len(records), len(files))
    return records


def _ensure_lakebase_env() -> None:
    """Set Lakebase env vars from app.yaml if not already set."""
    if os.getenv("LAKEBASE_HOST"):
        return  # Already configured

    # Load from app.yaml
    app_yaml = PROJECT_ROOT / "app.yaml"
    if not app_yaml.exists():
        return

    import yaml
    with open(app_yaml) as f:
        config = yaml.safe_load(f)

    for env_entry in config.get("env", []):
        name = env_entry.get("name", "")
        value = env_entry.get("value", "")
        if name.startswith("LAKEBASE_") and not os.getenv(name):
            os.environ[name] = value


def load_phase_transitions_from_delta(airport_icao: str, days: int = 7) -> list[dict]:
    """Load pre-enriched phase transitions from Databricks Delta table.

    The enrichment job (enrich_opensky_events.py) already ran OpenSkyEventInferrer
    with OSM gate positions, so we get phase transitions with gate assignments.
    Returns phase transition dicts compatible with the turnaround extraction logic.
    """
    _ensure_lakebase_env()

    host = os.getenv("DATABRICKS_HOST")
    token = os.getenv("DATABRICKS_TOKEN")
    if not host or not token:
        logger.error("DATABRICKS_HOST and DATABRICKS_TOKEN required for Delta queries")
        return []

    try:
        from databricks.sdk import WorkspaceClient
        from databricks.sdk.service.sql import StatementState

        w = WorkspaceClient(host=host, token=token)

        # Find a SQL warehouse
        warehouses = list(w.warehouses.list())
        if not warehouses:
            logger.error("No SQL warehouses found")
            return []
        warehouse_id = warehouses[0].id
        logger.info("Using SQL warehouse: %s (%s)", warehouses[0].name, warehouse_id)

        catalog = "serverless_stable_3n0ihb_catalog"
        schema = "airport_digital_twin"

        result = w.statement_execution.execute_statement(
            warehouse_id=warehouse_id,
            statement=f"""
                SELECT time, icao24, callsign, from_phase, to_phase,
                       latitude, longitude, altitude, aircraft_type, assigned_gate
                FROM {catalog}.{schema}.opensky_phase_transitions
                WHERE airport_icao = '{airport_icao}'
                  AND collection_date >= date_sub(current_date(), {days})
                ORDER BY time, icao24
            """,
            wait_timeout="60s",
        )

        if result.status.state != StatementState.SUCCEEDED:
            logger.error("Delta query failed: %s", result.status.error)
            return []

        cols = [c.name for c in result.manifest.schema.columns]
        transitions = []
        if result.result and result.result.data_array:
            for row in result.result.data_array:
                transitions.append(dict(zip(cols, row)))

        logger.info("Loaded %d phase transitions from Delta for %s (last %d days)",
                     len(transitions), airport_icao, days)
        return transitions

    except Exception as e:
        logger.error("Delta query failed: %s", e)
        return []


def load_from_lakebase(airport_icao: str, days: int = 7) -> list[dict]:
    """Query raw OpenSky snapshots from Lakebase for an airport.

    Uses LakebaseService for connection management (OAuth, pooling, read replica).
    Returns records in the same format as group_into_frames expects.
    """
    _ensure_lakebase_env()

    from app.backend.services.lakebase_service import get_lakebase_service

    lakebase = get_lakebase_service()
    if not lakebase.is_available:
        logger.error("Lakebase not available — check connection config")
        return []

    try:
        with lakebase._get_read_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT icao24, callsign, latitude, longitude,
                           altitude, velocity, heading, vertical_rate,
                           on_ground, aircraft_type, snapshot_time
                    FROM flight_position_snapshots
                    WHERE airport_icao = %s
                      AND data_source = 'opensky'
                      AND snapshot_time > NOW() - INTERVAL '%s days'
                    ORDER BY snapshot_time, icao24
                """, (airport_icao, days))
                cols = [d[0] for d in cur.description]
                rows = cur.fetchall()
    except Exception as e:
        logger.error("Lakebase query failed: %s", e)
        return []

    records = [dict(zip(cols, row)) for row in rows]
    logger.info("Loaded %d snapshots from Lakebase for %s (last %d days)", len(records), airport_icao, days)
    return records


def group_lakebase_into_frames(records: list[dict]) -> list[tuple[str, list[dict]]]:
    """Group Lakebase records by snapshot_time into inferrer-compatible frames.

    Unlike group_into_frames(), no unit conversion needed — the collector
    already stores velocity in kts, altitude in ft, vertical_rate in ft/min.
    """
    frames_dict: dict[str, list[dict]] = defaultdict(list)

    for rec in records:
        ts = rec.get("snapshot_time")
        if ts is None:
            continue
        ts_str = ts.isoformat() if isinstance(ts, datetime) else str(ts)

        snap = {
            "icao24": rec.get("icao24", ""),
            "callsign": (rec.get("callsign") or rec.get("icao24", "")).strip(),
            "latitude": rec.get("latitude"),
            "longitude": rec.get("longitude"),
            "on_ground": bool(rec.get("on_ground", False)),
            "velocity": float(rec.get("velocity", 0) or 0),      # already kts
            "altitude": float(rec.get("altitude", 0) or 0),       # already ft
            "vertical_rate": float(rec.get("vertical_rate", 0) or 0),  # already ft/min
            "heading": rec.get("heading"),
            "aircraft_type": rec.get("aircraft_type", ""),
        }
        frames_dict[ts_str].append(snap)

    frames = sorted(frames_dict.items(), key=lambda x: x[0])
    logger.info("Grouped into %d frames from Lakebase", len(frames))
    return frames


def fetch_gates(icao_code: str, cache_path: Path | None = None) -> list[dict]:
    """Fetch gate positions from OSM Overpass API, with optional JSON cache.

    If cache_path exists, loads gates from it. Otherwise fetches from Overpass
    and saves to cache_path for future runs.
    """
    # Try cache first
    if cache_path and cache_path.exists():
        gates = json.loads(cache_path.read_text())
        logger.info("Loaded %d cached gates from %s", len(gates), cache_path)
        return gates

    logger.info("Fetching OSM gates for %s...", icao_code)
    parser = OSMParser()
    doc = parser.parse(icao_code)

    # Need a CoordinateConverter for the converter
    ref_lat = ref_lon = None
    for g in doc.gates:
        if g.lat is not None and g.lon is not None:
            ref_lat, ref_lon = g.lat, g.lon
            break
    if ref_lat is None:
        for n in doc.nodes:
            if n.lat is not None and n.lon is not None:
                ref_lat, ref_lon = n.lat, n.lon
                break

    if ref_lat is None:
        logger.error("No coordinates found in OSM data for %s", icao_code)
        return []

    coord_conv = CoordinateConverter(ref_lat, ref_lon)
    converter = OSMConverter(coord_conv)
    config = converter.to_config(doc)

    gates = config.get("gates", [])
    logger.info("Found %d gates for %s", len(gates), icao_code)

    # Cache for next time
    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(gates, indent=2))
        logger.info("Cached gates to %s", cache_path)

    return gates


def group_into_frames(records: list[dict]) -> list[tuple[str, list[dict]]]:
    """Group raw records by collection_time into frames.

    Each frame is a (timestamp, [snapshots]) tuple. Snapshots are converted
    to the format expected by OpenSkyEventInferrer.process_frame().

    Returns frames sorted by timestamp.
    """
    frames_dict: dict[str, list[dict]] = defaultdict(list)

    for rec in records:
        ts = rec.get("collection_time", "")
        if not ts:
            continue

        # Convert to inferrer-compatible snapshot format
        velocity_ms = float(rec.get("velocity", 0) or 0)
        baro_alt_m = float(rec.get("baro_altitude", 0) or 0)
        vrate_ms = float(rec.get("vertical_rate", 0) or 0)

        snap = {
            "icao24": rec.get("icao24", ""),
            "callsign": (rec.get("callsign") or rec.get("icao24", "")).strip(),
            "latitude": rec.get("latitude"),
            "longitude": rec.get("longitude"),
            "on_ground": rec.get("on_ground", False),
            "velocity": velocity_ms * MS_TO_KTS,       # inferrer expects kts
            "altitude": baro_alt_m * M_TO_FT,           # inferrer expects ft
            "vertical_rate": vrate_ms * M_TO_FT * 60,   # m/s → ft/min
            "heading": rec.get("true_track"),
            "aircraft_type": rec.get("aircraft_type", ""),
        }
        frames_dict[ts].append(snap)

    # Sort by timestamp
    frames = sorted(frames_dict.items(), key=lambda x: x[0])
    logger.info("Grouped into %d frames", len(frames))
    return frames


def build_feature_set(
    callsign: str,
    gate_id: str,
    aircraft_type: str,
    parked_hour: int,
    parked_weekday: int,
    airport_iata: str,
) -> OBTFeatureSet:
    """Build an OBTFeatureSet from observed turnaround context."""
    h_sin = round(math.sin(2.0 * math.pi * parked_hour / 24.0), 6)
    h_cos = round(math.cos(2.0 * math.pi * parked_hour / 24.0), 6)

    airline_code = callsign[:3] if len(callsign) >= 3 and callsign[:3].isalpha() else "UNK"
    gate_prefix = ""
    for ch in (gate_id or ""):
        if ch.isalpha():
            gate_prefix += ch
        else:
            break
    gate_prefix = gate_prefix or "UNK"

    return OBTFeatureSet(
        aircraft_category=classify_aircraft(aircraft_type) if aircraft_type else "narrow",
        airline_code=airline_code,
        hour_of_day=parked_hour,
        is_international=False,  # Unknown from ADS-B alone
        arrival_delay_min=0.0,   # Unknown
        gate_id_prefix=gate_prefix,
        is_remote_stand=(gate_id or "").upper().startswith("R"),
        concurrent_gate_ops=0,   # Could compute but not critical for fallback
        wind_speed_kt=0.0,
        visibility_sm=10.0,
        has_active_ground_stop=False,
        scheduled_departure_hour=parked_hour,
        airport_code=airport_iata,
        day_of_week=parked_weekday,
        hour_sin=h_sin,
        hour_cos=h_cos,
        is_weather_scenario=False,
        scheduled_buffer_min=0.0,
        is_hub_connecting=False,
    )


def evaluate(
    data_dir: Path,
    airport: str,
    airport_iata: str,
    include_synced: bool = False,
    from_lakebase: bool = False,
    from_delta: bool = False,
    days: int = 7,
) -> None:
    """Run the full evaluation pipeline."""

    # ── Fast path: read pre-enriched data from Delta ──
    if from_delta:
        phase_transitions = load_phase_transitions_from_delta(airport, days=days)
        if not phase_transitions:
            logger.warning("No phase transitions in Delta for %s", airport)
            return
        gate_events = []  # Not needed for turnaround extraction
        logger.info("Phase transitions from Delta: %d", len(phase_transitions))

    else:
        # 1. Load raw data
        if from_lakebase:
            records = load_from_lakebase(airport, days=days)
        else:
            records = load_jsonl_files(data_dir, airport)
            if include_synced:
                synced_dir = data_dir / "synced"
                if synced_dir.is_dir():
                    synced = load_jsonl_files(synced_dir, airport)
                    records.extend(synced)
                    logger.info("Total records after including synced: %d", len(records))
        if not records:
            return

        # 2. Fetch gates from OSM (with cache)
        cache_path = data_dir / f".gates_cache_{airport}.json"
        gates = fetch_gates(airport, cache_path=cache_path)
        if not gates:
            logger.warning("No gates found — event inference will have no gate matching")

        # 3. Group into frames and run inferrer
        frames = group_lakebase_into_frames(records) if from_lakebase else group_into_frames(records)
        inferrer = OpenSkyEventInferrer(gates)

        for ts, snapshots in frames:
            inferrer.process_frame(ts, snapshots)

        results = inferrer.get_results()
        phase_transitions = results["phase_transitions"]
        gate_events = results["gate_events"]

        logger.info("Phase transitions: %d", len(phase_transitions))
        logger.info("Gate events: %d", len(gate_events))

    # 4. Extract turnaround durations (parked → taxi_to_runway/takeoff)
    parked_at: dict[str, dict] = {}   # icao24 → transition
    turnarounds: list[dict] = []

    for pt in phase_transitions:
        icao24 = pt["icao24"]
        if pt["to_phase"] == "parked":
            parked_at[icao24] = pt
        elif pt["from_phase"] == "parked" and icao24 in parked_at:
            park_pt = parked_at.pop(icao24)
            park_time = datetime.fromisoformat(park_pt["time"])
            leave_time = datetime.fromisoformat(pt["time"])
            duration_min = (leave_time - park_time).total_seconds() / 60.0

            turnarounds.append({
                "icao24": icao24,
                "callsign": pt.get("callsign", icao24),
                "gate": park_pt.get("assigned_gate") or "?",
                "parked_time": park_time,
                "leave_time": leave_time,
                "duration_min": duration_min,
                "aircraft_type": pt.get("aircraft_type", ""),
            })

    if not turnarounds:
        logger.warning("No complete turnarounds found (parked → departure)")
        logger.info("This is expected with sparse data. Need 60-90+ min of continuous "
                     "observation per aircraft to capture a full turnaround.")

        # Still show what we found
        print("\n=== Phase Transitions ===")
        for pt in phase_transitions:
            print(f"  {pt['time'][:19]}  {pt['callsign']:8s}  {pt['from_phase']:15s} → {pt['to_phase']}")

        if gate_events:
            print("\n=== Gate Events ===")
            for ge in gate_events:
                print(f"  {ge['time'][:19]}  {ge['callsign']:8s}  gate={ge['gate']:6s}  {ge['event_type']}")

        # Show aircraft still parked (incomplete turnarounds)
        if parked_at:
            print(f"\n=== Aircraft Still Parked (incomplete turnarounds) ===")
            last_time = phase_transitions[-1]["time"] if phase_transitions else None
            for icao24, pt in parked_at.items():
                park_time = datetime.fromisoformat(pt["time"])
                if last_time:
                    elapsed = (datetime.fromisoformat(last_time) - park_time).total_seconds() / 60.0
                else:
                    elapsed = 0.0
                print(f"  {pt.get('callsign', icao24):8s}  gate={pt.get('assigned_gate', '?'):6s}  "
                      f"parked at {pt['time'][:19]}  ({elapsed:.0f} min so far)")
        return

    # 5. Compare against OBT model predictions
    predictor = OBTPredictor()

    print("\n" + "=" * 90)
    print(f"{'Callsign':10s} {'Gate':8s} {'Type':6s} {'Observed':>10s} {'Predicted':>10s} "
          f"{'Error':>8s} {'Fallback':>8s}")
    print("=" * 90)

    errors = []
    for ta in sorted(turnarounds, key=lambda x: x["parked_time"]):
        features = build_feature_set(
            callsign=ta["callsign"],
            gate_id=ta["gate"],
            aircraft_type=ta["aircraft_type"],
            parked_hour=ta["parked_time"].hour,
            parked_weekday=ta["parked_time"].weekday(),
            airport_iata=airport_iata,
        )
        prediction = predictor.predict(features)

        observed = ta["duration_min"]
        predicted = prediction.turnaround_minutes
        error = observed - predicted
        errors.append(error)

        print(f"{ta['callsign']:10s} {ta['gate']:8s} {features.aircraft_category:6s} "
              f"{observed:8.1f}m {predicted:8.1f}m {error:+7.1f}m "
              f"{'yes' if prediction.is_fallback else 'no':>8s}")

    print("=" * 90)

    if errors:
        mae = sum(abs(e) for e in errors) / len(errors)
        rmse = math.sqrt(sum(e * e for e in errors) / len(errors))
        bias = sum(errors) / len(errors)
        print(f"\nSummary: {len(turnarounds)} turnarounds")
        print(f"  MAE:  {mae:.1f} min")
        print(f"  RMSE: {rmse:.1f} min")
        print(f"  Bias: {bias:+.1f} min (positive = model under-predicts)")


def main():
    parser = argparse.ArgumentParser(description="Evaluate OBT model against OpenSky data")
    parser.add_argument("--data-dir", default="data/opensky_raw", help="Directory with JSONL files")
    parser.add_argument("--airport", default="EDDF", help="ICAO code (default: EDDF)")
    parser.add_argument("--iata", default="FRA", help="IATA code for OBT model (default: FRA)")
    parser.add_argument("--include-synced", action="store_true",
                        help="Also include data from data_dir/synced/")
    parser.add_argument("--from-lakebase", action="store_true",
                        help="Read from Lakebase instead of local JSONL files")
    parser.add_argument("--from-delta", action="store_true",
                        help="Read pre-enriched phase transitions from Delta tables "
                             "(requires DATABRICKS_HOST + DATABRICKS_TOKEN)")
    parser.add_argument("--days", type=int, default=7,
                        help="Days of data to query from Lakebase/Delta (default: 7)")
    args = parser.parse_args()

    evaluate(
        Path(args.data_dir), args.airport, args.iata,
        include_synced=args.include_synced,
        from_lakebase=args.from_lakebase,
        from_delta=args.from_delta,
        days=args.days,
    )


if __name__ == "__main__":
    main()
