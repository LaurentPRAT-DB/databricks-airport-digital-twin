"""Baggage event writer for DLT landing zone.

Writes baggage events as JSON-lines files to a Unity Catalog Volume
for Auto Loader pickup by the baggage DLT pipeline.
"""

import json
import os
from datetime import datetime, timezone

LANDING_ZONE = "/Volumes/{catalog}/{schema}/baggage_landing"


def write_baggage_events(events: list[dict], catalog: str, schema: str) -> str:
    """Write baggage events as a JSON-lines file to the landing zone volume.

    Args:
        events: List of baggage event dictionaries.
        catalog: Unity Catalog name.
        schema: Schema/database name.

    Returns:
        Path to the written file.
    """
    landing_path = LANDING_ZONE.format(catalog=catalog, schema=schema)
    os.makedirs(landing_path, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    filename = f"baggage_{timestamp}.json"
    filepath = os.path.join(landing_path, filename)

    with open(filepath, "w") as f:
        for event in events:
            event["recorded_at"] = datetime.now(timezone.utc).isoformat()
            f.write(json.dumps(event) + "\n")

    return filepath
