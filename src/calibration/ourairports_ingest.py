"""OurAirports data ingestion for global airport metadata.

Parses the free CSV data from ourairports.com/data/ to supplement
airport profiles with metadata (coordinates, elevation, type, country)
for airports not covered by BTS data.

Data: https://ourairports.com/data/
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def parse_airports_csv(csv_path: Path) -> dict[str, dict]:
    """Parse OurAirports airports.csv into a lookup dict.

    Returns:
        Dict keyed by ICAO code with airport metadata:
        {
            "KSFO": {
                "icao": "KSFO",
                "iata": "SFO",
                "name": "San Francisco International Airport",
                "latitude": 37.6213,
                "longitude": -122.379,
                "elevation_ft": 13,
                "type": "large_airport",
                "country": "US",
                "continent": "NA",
            }
        }
    """
    airports: dict[str, dict] = {}

    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            icao = row.get("ident", "").strip()
            if not icao:
                continue

            iata = row.get("iata_code", "").strip()
            airports[icao] = {
                "icao": icao,
                "iata": iata,
                "name": row.get("name", "").strip(),
                "latitude": _safe_float(row.get("latitude_deg", "0")),
                "longitude": _safe_float(row.get("longitude_deg", "0")),
                "elevation_ft": _safe_int(row.get("elevation_ft", "0")),
                "type": row.get("type", "").strip(),
                "country": row.get("iso_country", "").strip(),
                "continent": row.get("continent", "").strip(),
            }

    logger.info("Parsed %d airports from OurAirports CSV", len(airports))
    return airports


def parse_runways_csv(csv_path: Path) -> dict[str, list[dict]]:
    """Parse OurAirports runways.csv into a lookup dict.

    Returns:
        Dict keyed by airport ICAO code, value is list of runway dicts.
    """
    runways: dict[str, list[dict]] = {}

    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            airport_ref = row.get("airport_ident", "").strip()
            if not airport_ref:
                continue

            runway = {
                "length_ft": _safe_int(row.get("length_ft", "0")),
                "width_ft": _safe_int(row.get("width_ft", "0")),
                "surface": row.get("surface", "").strip(),
                "lighted": row.get("lighted", "0").strip() == "1",
                "closed": row.get("closed", "0").strip() == "1",
                "le_ident": row.get("le_ident", "").strip(),
                "he_ident": row.get("he_ident", "").strip(),
            }
            runways.setdefault(airport_ref, []).append(runway)

    logger.info("Parsed runways for %d airports", len(runways))
    return runways


def get_airport_metadata(
    icao: str,
    airports_csv: Optional[Path] = None,
) -> Optional[dict]:
    """Get metadata for a single airport from OurAirports data.

    Args:
        icao: ICAO code (e.g., "EGLL")
        airports_csv: Path to airports.csv

    Returns:
        Airport metadata dict or None if not found
    """
    if airports_csv is None or not airports_csv.exists():
        return None

    airports = parse_airports_csv(airports_csv)
    return airports.get(icao)


def _safe_int(val: str) -> int:
    try:
        return int(float(val.strip().replace(",", "")))
    except (ValueError, AttributeError):
        return 0


def _safe_float(val: str) -> float:
    try:
        return float(val.strip().replace(",", ""))
    except (ValueError, AttributeError):
        return 0.0
