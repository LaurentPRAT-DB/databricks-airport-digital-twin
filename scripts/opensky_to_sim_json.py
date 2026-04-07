"""Convert OpenSky JSONL collector data to simulation JSON format.

The video renderer (video_cli.py) expects simulation output JSON with
{config, position_snapshots, ...}. This script converts raw OpenSky
JSONL files into that format so we can use --track-flight on real data.

Usage:
    uv run python scripts/opensky_to_sim_json.py --airport EDDF
    uv run python scripts/opensky_to_sim_json.py --airport EDDF --output simulation_output_eddf_opensky.json
"""

import argparse
import json
import os
from collections import defaultdict
from pathlib import Path


PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "opensky_raw" / "synced"


def load_jsonl_files(airport: str) -> list[dict]:
    """Load all JSONL files for the given airport, sorted by collection_time."""
    records = []
    pattern = f"{airport}_"
    files = sorted(f for f in DATA_DIR.iterdir() if f.name.startswith(pattern) and f.suffix == ".jsonl")
    if not files:
        raise FileNotFoundError(f"No JSONL files found for {airport} in {DATA_DIR}")

    print(f"Loading {len(files)} JSONL files for {airport}...")
    for filepath in files:
        with open(filepath) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return records


def convert_to_simulation_json(records: list[dict], airport: str) -> dict:
    """Convert raw OpenSky records to simulation output JSON format."""
    # Group records by collection_time (each collection_time = one frame)
    frames_by_time: dict[str, list[dict]] = defaultdict(list)
    for rec in records:
        ct = rec.get("collection_time", "")
        if not ct:
            continue
        frames_by_time[ct].append(rec)

    sorted_times = sorted(frames_by_time.keys())
    print(f"  {len(records)} records across {len(sorted_times)} timestamps")

    # Unique flights
    unique_flights = set()
    for rec in records:
        unique_flights.add(rec.get("icao24", ""))
    print(f"  {len(unique_flights)} unique aircraft")

    # Build position_snapshots in simulation format
    position_snapshots = []
    for ts in sorted_times:
        for rec in frames_by_time[ts]:
            # Map OpenSky velocity (m/s) to kts for consistency with simulation
            velocity_ms = rec.get("velocity") or 0
            velocity_kts = velocity_ms * 1.94384

            # Determine phase from on_ground + altitude
            on_ground = rec.get("on_ground", False)
            altitude = rec.get("baro_altitude") or rec.get("geo_altitude") or 0
            if on_ground:
                phase = "parked" if velocity_ms < 2 else "taxi_out"
            elif altitude and altitude < 1000:
                phase = "approaching"
            else:
                phase = "enroute"

            position_snapshots.append({
                "time": ts,
                "icao24": rec.get("icao24", ""),
                "callsign": (rec.get("callsign") or "").strip(),
                "latitude": rec.get("latitude", 0),
                "longitude": rec.get("longitude", 0),
                "altitude": altitude,
                "velocity": velocity_kts,
                "heading": rec.get("true_track") or 0,
                "phase": phase,
                "on_ground": on_ground,
                "aircraft_type": rec.get("aircraft_type") or "UNKN",
                "assigned_gate": None,
                "vertical_rate": rec.get("vertical_rate") or 0,
                "origin_airport": None,
                "destination_airport": airport,
            })

    # Build config
    config = {
        "airport": airport,
        "arrivals": 0,
        "departures": 0,
        "duration_hours": 0,
        "start_time": sorted_times[0] if sorted_times else "",
        "end_time": sorted_times[-1] if sorted_times else "",
        "data_source": "opensky_live",
    }

    # Compute duration
    if sorted_times:
        from datetime import datetime
        start = datetime.fromisoformat(sorted_times[0])
        end = datetime.fromisoformat(sorted_times[-1])
        config["duration_hours"] = round((end - start).total_seconds() / 3600, 2)

    return {
        "config": config,
        "summary": {
            "total_flights": len(unique_flights),
            "total_position_snapshots": len(position_snapshots),
            "scenario_name": f"OpenSky Live — {airport}",
        },
        "schedule": [],
        "position_snapshots": position_snapshots,
        "phase_transitions": [],
        "gate_events": [],
        "baggage_events": [],
        "weather_snapshots": [],
        "scenario_events": [],
    }


def main():
    parser = argparse.ArgumentParser(description="Convert OpenSky JSONL to simulation JSON")
    parser.add_argument("--airport", default="EDDF", help="Airport ICAO code (default: EDDF)")
    parser.add_argument("--output", "-o", default=None, help="Output JSON path")
    args = parser.parse_args()

    records = load_jsonl_files(args.airport)
    sim_json = convert_to_simulation_json(records, args.airport)

    output_path = args.output or f"simulation_output_{args.airport.lower()}_opensky.json"
    print(f"Writing {output_path}...")
    with open(PROJECT_ROOT / output_path, "w") as f:
        json.dump(sim_json, f, default=str)

    size_mb = os.path.getsize(PROJECT_ROOT / output_path) / (1024 * 1024)
    print(f"Done: {size_mb:.1f} MB, {sim_json['summary']['total_position_snapshots']} snapshots")


if __name__ == "__main__":
    main()
