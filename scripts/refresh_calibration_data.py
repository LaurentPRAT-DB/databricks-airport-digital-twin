#!/usr/bin/env python3
"""Refresh calibration data: download latest sources and rebuild profiles.

Orchestrates the full calibration pipeline:
1. Download latest OTP PREZIP + OurAirports data
2. Rebuild profiles for all airports
3. Log what changed (diff old vs new profile stats)

Usage:
    python scripts/refresh_calibration_data.py
    python scripts/refresh_calibration_data.py --airports SFO JFK
    python scripts/refresh_calibration_data.py --otp-months 6 --skip-download
"""

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

PROFILES_DIR = Path(__file__).resolve().parent.parent / "data" / "calibration" / "profiles"
DATA_SOURCES_FILE = Path(__file__).resolve().parent.parent / "data" / "calibration" / "data_sources.json"


def _load_existing_stats(airports: list[str]) -> dict[str, dict]:
    """Snapshot key stats from existing profiles for diff reporting."""
    stats: dict[str, dict] = {}
    for iata in airports:
        from src.calibration.profile import _iata_to_icao
        icao = _iata_to_icao(iata)
        path = PROFILES_DIR / f"{icao}.json"
        if path.exists():
            data = json.loads(path.read_text())
            stats[iata] = {
                "turnaround_median_min": data.get("turnaround_median_min", 0),
                "taxi_out_mean_min": data.get("taxi_out_mean_min", 0),
                "taxi_in_mean_min": data.get("taxi_in_mean_min", 0),
                "delay_rate": data.get("delay_rate", 0),
                "sample_size": data.get("sample_size", 0),
            }
    return stats


def _report_diff(old: dict[str, dict], airports: list[str]) -> None:
    """Report changes between old and new profiles."""
    from src.calibration.profile import _iata_to_icao
    changes = 0
    for iata in airports:
        icao = _iata_to_icao(iata)
        path = PROFILES_DIR / f"{icao}.json"
        if not path.exists():
            continue
        new_data = json.loads(path.read_text())
        new_stats = {
            "turnaround_median_min": new_data.get("turnaround_median_min", 0),
            "taxi_out_mean_min": new_data.get("taxi_out_mean_min", 0),
            "taxi_in_mean_min": new_data.get("taxi_in_mean_min", 0),
            "delay_rate": new_data.get("delay_rate", 0),
            "sample_size": new_data.get("sample_size", 0),
        }
        old_stats = old.get(iata, {})
        if old_stats != new_stats:
            changes += 1
            logger.info("  %s changed:", iata)
            for key in new_stats:
                o = old_stats.get(key, "N/A")
                n = new_stats[key]
                if o != n:
                    logger.info("    %s: %s → %s", key, o, n)

    logger.info("Total: %d/%d profiles changed", changes, len(airports))


def _update_data_sources_timestamp() -> None:
    """Update last_refreshed in data_sources.json."""
    if not DATA_SOURCES_FILE.exists():
        return
    try:
        cfg = json.loads(DATA_SOURCES_FILE.read_text())
        cfg["last_refreshed"] = date.today().isoformat()
        for entry in cfg.get("sources", {}).values():
            if "last_downloaded" in entry:
                entry["last_downloaded"] = date.today().isoformat()
        DATA_SOURCES_FILE.write_text(json.dumps(cfg, indent=2) + "\n")
        logger.info("Updated data_sources.json timestamps")
    except Exception as e:
        logger.warning("Could not update data_sources.json: %s", e)


def main():
    parser = argparse.ArgumentParser(description="Refresh calibration data and rebuild profiles")
    parser.add_argument("--airports", nargs="+", help="Specific airports to rebuild (IATA codes)")
    parser.add_argument("--otp-months", type=int, default=12, help="Months of OTP data (default: 12)")
    parser.add_argument("--skip-download", action="store_true", help="Skip download, just rebuild profiles")
    args = parser.parse_args()

    from src.calibration.profile_builder import US_AIRPORTS, INTERNATIONAL_AIRPORTS
    airports = args.airports or (US_AIRPORTS + INTERNATIONAL_AIRPORTS)

    # Step 1: Download latest data
    if not args.skip_download:
        logger.info("=== Step 1: Downloading latest data ===")
        from scripts.download_calibration_data import download_ourairports, download_otp_prezip
        download_ourairports()
        download_otp_prezip(args.otp_months)

    # Step 2: Snapshot old profiles
    logger.info("=== Step 2: Snapshotting existing profiles ===")
    old_stats = _load_existing_stats(airports)

    # Step 3: Rebuild profiles
    logger.info("=== Step 3: Rebuilding profiles ===")
    from src.calibration.profile_builder import build_profiles
    build_profiles(airports=airports)

    # Step 4: Report changes
    logger.info("=== Step 4: Change report ===")
    _report_diff(old_stats, airports)

    # Step 5: Update timestamps
    _update_data_sources_timestamp()

    logger.info("=== Refresh complete ===")


if __name__ == "__main__":
    main()
