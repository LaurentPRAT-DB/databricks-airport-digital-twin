"""Databricks job entrypoint for polling OpenSky API and writing to landing zone."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any

from src.ingestion.opensky_client import OpenSkyClient
from src.ingestion.circuit_breaker import api_circuit_breaker
from src.ingestion.fallback import generate_synthetic_flights


def poll_and_write(
    landing_path: str,
    bbox: Dict[str, float],
    synthetic_count: int = 50,
) -> int:
    """
    Poll OpenSky API and write results to landing zone.

    Implements the following failover logic:
    1. If circuit breaker is open: use synthetic data
    2. If circuit breaker allows: try API call
       - On success: record success, use API data
       - On failure: record failure, use synthetic data as fallback
    3. Write JSON file to landing zone with metadata

    Args:
        landing_path: Directory path for output JSON files.
        bbox: Bounding box dict for API query.
        synthetic_count: Number of synthetic flights if fallback needed.

    Returns:
        Count of state vectors written.
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    source: str
    data: Dict[str, Any]

    # Check circuit breaker state
    if not api_circuit_breaker.can_execute():
        # Circuit is open - don't even try the API
        data = generate_synthetic_flights(count=synthetic_count, bbox=bbox)
        source = "synthetic"
    else:
        # Circuit allows execution - try the API
        try:
            client = OpenSkyClient()
            response = client.get_states(bbox=bbox)
            api_circuit_breaker.record_success()

            data = {
                "time": response.time,
                "states": response.states or [],
            }
            source = "opensky"

        except Exception as e:
            # API call failed - record failure and use fallback
            api_circuit_breaker.record_failure()
            data = generate_synthetic_flights(count=synthetic_count, bbox=bbox)
            source = "fallback"

    # Prepare output with metadata
    output = {
        "timestamp": timestamp,
        "source": source,
        "states": data.get("states", []),
    }

    # Generate filename from timestamp (replace colons for filesystem compatibility)
    filename = f"{timestamp.replace(':', '-')}.json"
    output_path = Path(landing_path) / filename

    # Ensure directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Write JSON file
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    return len(output["states"])


def main():
    """
    Main entry point for Databricks job.

    Reads configuration from environment and executes a single poll cycle.
    For continuous polling, schedule this job with a trigger interval.
    """
    from src.config.settings import settings

    count = poll_and_write(
        landing_path=settings.LANDING_PATH,
        bbox=settings.SFO_BBOX,
    )
    print(f"Wrote {count} flight states to landing zone")
    return count


if __name__ == "__main__":
    main()
