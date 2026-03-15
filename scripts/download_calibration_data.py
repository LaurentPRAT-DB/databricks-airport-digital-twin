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
import zipfile
import io
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "calibration" / "raw"

# OurAirports data (always available, no auth needed)
OURAIRPORTS_URLS = {
    "airports.csv": "https://davidmegginson.github.io/ourairports-data/airports.csv",
    "runways.csv": "https://davidmegginson.github.io/ourairports-data/runways.csv",
}

# BTS bulk download URLs — these are direct zip downloads from the BTS data library.
# They may be blocked by BTS (requires browser session), so we try and fall back.
BTS_BULK_URLS = {
    "T_T100_SEGMENT_ALL_CARRIER.csv": (
        "https://transtats.bts.gov/PREZIP/T_T100_SEGMENT_ALL_CARRIER.zip",
        "T_T100 Domestic Segment (All Carriers)",
    ),
    "T_T100_INTERNATIONAL_SEGMENT.csv": (
        "https://transtats.bts.gov/PREZIP/T_T100_INTERNATIONAL_SEGMENT.zip",
        "T_T100 International Segment",
    ),
}

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
            logger.info("  -> Saved %s (%.1f MB)", dest, size_mb)
        except Exception as e:
            logger.error("  -> Failed: %s", e)


def _try_download_bts_zip(csv_filename: str, url: str, label: str) -> bool:
    """Try to download a BTS zip file and extract the CSV.

    Returns True if successful, False otherwise.
    """
    dest = RAW_DIR / csv_filename
    if dest.exists():
        logger.info("Already exists: %s", dest)
        return True

    logger.info("Attempting download: %s ...", label)
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; AirportDigitalTwin/1.0)",
        })
        with urllib.request.urlopen(req, timeout=60) as response:
            if response.status != 200:
                return False
            data = response.read()

        # Check if it's actually a zip file
        if not data[:2] == b"PK":
            logger.warning("  -> Response is not a zip file (BTS may require browser session)")
            return False

        # Extract CSV from zip
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            csv_names = [n for n in zf.namelist() if n.endswith(".csv")]
            if not csv_names:
                logger.warning("  -> No CSV found in zip")
                return False
            # Extract the first (usually only) CSV
            with zf.open(csv_names[0]) as src, open(dest, "wb") as dst:
                dst.write(src.read())

        size_mb = dest.stat().st_size / (1024 * 1024)
        logger.info("  -> Saved %s (%.1f MB)", dest, size_mb)
        return True

    except Exception as e:
        logger.warning("  -> Download failed: %s", e)
        return False


def download_bts():
    """Try to download BTS data programmatically, fall back to instructions."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    any_downloaded = False
    any_failed = False

    for csv_filename, (url, label) in BTS_BULK_URLS.items():
        if _try_download_bts_zip(csv_filename, url, label):
            any_downloaded = True
        else:
            any_failed = True

    # On-Time Performance doesn't have a simple bulk URL, always manual
    ontime_file = RAW_DIR / "On_Time_Reporting_Carrier_On_Time_Performance.csv"
    if ontime_file.exists():
        logger.info("Already exists: %s", ontime_file)
    else:
        any_failed = True

    if any_failed:
        logger.info("")
        logger.info("Some BTS files need manual download.")
        logger.info("However, known_profiles will be used as a high-quality fallback.")
        print(BTS_DOWNLOAD_INSTRUCTIONS.format(raw_dir=RAW_DIR))

    # Check what we have
    bts_files = [
        "T_T100_SEGMENT_ALL_CARRIER.csv",
        "T_T100_INTERNATIONAL_SEGMENT.csv",
        "On_Time_Reporting_Carrier_On_Time_Performance.csv",
    ]
    existing = [f for f in bts_files if (RAW_DIR / f).exists()]
    if existing:
        logger.info("BTS files present: %s", ", ".join(existing))
    missing = [f for f in bts_files if not (RAW_DIR / f).exists()]
    if missing:
        logger.info("BTS files missing: %s", ", ".join(missing))
        logger.info(
            "Profiles will use known_profiles (hand-researched real stats) "
            "for airports without BTS data."
        )


def main():
    parser = argparse.ArgumentParser(description="Download calibration data")
    parser.add_argument("--bts", action="store_true", help="Download BTS data (or show instructions)")
    parser.add_argument("--ourairports", action="store_true", help="Download OurAirports data")
    parser.add_argument("--all", action="store_true", help="Download everything available")
    args = parser.parse_args()

    if not (args.bts or args.ourairports or args.all):
        args.all = True

    if args.ourairports or args.all:
        download_ourairports()

    if args.bts or args.all:
        download_bts()


if __name__ == "__main__":
    main()
