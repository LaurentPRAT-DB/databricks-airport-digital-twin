#!/usr/bin/env python3
"""Download BTS and OurAirports raw CSV data for calibration profile building.

Downloads:
1. BTS T-100 Domestic Segment (all carriers) — ~50MB
2. BTS T-100 International Segment — ~20MB
3. BTS On-Time Performance (most recent year) — ~200MB
4. OurAirports airports.csv — ~2MB
5. OurAirports runways.csv — ~1MB

Data is saved to data/calibration/raw/.

Usage:
    python scripts/download_calibration_data.py [--bts] [--ourairports] [--all]
"""

import argparse
import logging
import sys
import urllib.request
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "calibration" / "raw"

# OurAirports data (always available, no auth needed)
OURAIRPORTS_URLS = {
    "airports.csv": "https://davidmegginson.github.io/ourairports-data/airports.csv",
    "runways.csv": "https://davidmegginson.github.io/ourairports-data/runways.csv",
}

# BTS data URLs (these require manual download from transtats.bts.gov)
# The script provides instructions since BTS requires form-based download
BTS_DOWNLOAD_INSTRUCTIONS = """
BTS data must be downloaded manually from https://www.transtats.bts.gov/

1. T-100 Domestic Segment (All Carriers):
   - Go to: https://www.transtats.bts.gov/DL_SelectFields.aspx?gnoession_VQ=FMH
   - Select all fields, download as CSV
   - Save as: {raw_dir}/T_T100_SEGMENT_ALL_CARRIER.csv

2. T-100 International Segment:
   - Go to: https://www.transtats.bts.gov/DL_SelectFields.aspx?gnoession_VQ=FMI
   - Select all fields, download as CSV
   - Save as: {raw_dir}/T_T100_INTERNATIONAL_SEGMENT.csv

3. On-Time Performance:
   - Go to: https://www.transtats.bts.gov/DL_SelectFields.aspx?gnoession_VQ=FGK
   - Select fields: ORIGIN, DEST, CRS_DEP_TIME, CRS_ARR_TIME, DEP_DELAY,
     CARRIER_DELAY, WEATHER_DELAY, NAS_DELAY, SECURITY_DELAY, LATE_AIRCRAFT_DELAY,
     UNIQUE_CARRIER
   - Download most recent 12 months as CSV
   - Save as: {raw_dir}/On_Time_Reporting_Carrier_On_Time_Performance.csv
"""


def download_ourairports():
    """Download OurAirports CSV files."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    for filename, url in OURAIRPORTS_URLS.items():
        dest = RAW_DIR / filename
        if dest.exists():
            logger.info("Already exists: %s", dest)
            continue

        logger.info("Downloading %s...", url)
        try:
            urllib.request.urlretrieve(url, dest)
            size_mb = dest.stat().st_size / (1024 * 1024)
            logger.info("  → Saved %s (%.1f MB)", dest, size_mb)
        except Exception as e:
            logger.error("  → Failed: %s", e)


def show_bts_instructions():
    """Show instructions for manual BTS data download."""
    print(BTS_DOWNLOAD_INSTRUCTIONS.format(raw_dir=RAW_DIR))


def main():
    parser = argparse.ArgumentParser(description="Download calibration data")
    parser.add_argument("--bts", action="store_true", help="Show BTS download instructions")
    parser.add_argument("--ourairports", action="store_true", help="Download OurAirports data")
    parser.add_argument("--all", action="store_true", help="Download everything available")
    args = parser.parse_args()

    if not (args.bts or args.ourairports or args.all):
        args.all = True

    if args.ourairports or args.all:
        download_ourairports()

    if args.bts or args.all:
        show_bts_instructions()

        # Check if BTS files already exist
        bts_files = [
            "T_T100_SEGMENT_ALL_CARRIER.csv",
            "T_T100_INTERNATIONAL_SEGMENT.csv",
            "On_Time_Reporting_Carrier_On_Time_Performance.csv",
        ]
        existing = [f for f in bts_files if (RAW_DIR / f).exists()]
        if existing:
            logger.info("BTS files already present: %s", ", ".join(existing))


if __name__ == "__main__":
    main()
