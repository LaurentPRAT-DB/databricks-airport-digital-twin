"""Download simulation data from UC Volume for local validation testing.

Usage:
  uv run python scripts/download_simulation_data.py              # all airports, d1 only
  uv run python scripts/download_simulation_data.py --airport sfo  # single airport
  uv run python scripts/download_simulation_data.py --all        # all 4 configs per airport
  uv run python scripts/download_simulation_data.py --list       # list available files
"""

import argparse
import os
import sys
from pathlib import Path

UC_CATALOG = "serverless_stable_3n0ihb_catalog"
UC_SCHEMA = "airport_digital_twin"
UC_VOLUME = "simulation_data"
VOLUME_BASE = f"/Volumes/{UC_CATALOG}/{UC_SCHEMA}/{UC_VOLUME}"

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "cache" / "simulations"

AIRPORTS = [
    "ams", "atl", "bos", "cdg", "clt", "den", "dfw", "dtw", "dxb", "ewr",
    "fra", "gru", "hkg", "iah", "icn", "jfk", "jnb", "las", "lax", "lhr",
    "mco", "mia", "msp", "nrt", "ord", "pdx", "phl", "phx", "san", "sea",
    "sfo", "sin", "syd",
]

CONFIGS = ["normal_d1", "normal_d2", "normal_d3", "weather"]


def get_client():
    try:
        from databricks.sdk import WorkspaceClient
        return WorkspaceClient()
    except Exception as e:
        print(f"ERROR: Cannot create Databricks client: {e}")
        print("Make sure you have valid Databricks auth configured.")
        sys.exit(1)


def list_files(client):
    """List available simulation files on the Volume."""
    print(f"Listing files in {VOLUME_BASE}...")
    try:
        files = client.files.list_directory_contents(VOLUME_BASE)
        sim_files = []
        for f in files:
            if f.path and f.path.endswith(".json") and not f.path.endswith(".md"):
                name = os.path.basename(f.path)
                size_mb = (f.file_size or 0) / (1024 * 1024)
                sim_files.append((name, size_mb))
        sim_files.sort()
        print(f"\n{len(sim_files)} JSON files found:\n")
        for name, size in sim_files:
            print(f"  {name:50s} {size:7.1f} MB")
        return sim_files
    except Exception as e:
        print(f"ERROR listing files: {e}")
        return []


def download_file(client, filename: str, force: bool = False) -> bool:
    """Download a single file from the Volume."""
    output_path = OUTPUT_DIR / filename
    if output_path.exists() and not force:
        size_mb = output_path.stat().st_size / (1024 * 1024)
        print(f"  SKIP {filename} (already exists, {size_mb:.1f} MB)")
        return True

    remote_path = f"{VOLUME_BASE}/{filename}"
    try:
        print(f"  Downloading {filename}...", end="", flush=True)
        resp = client.files.download(remote_path)
        content = resp.contents.read()
        output_path.write_bytes(content)
        size_mb = len(content) / (1024 * 1024)
        print(f" {size_mb:.1f} MB")
        return True
    except Exception as e:
        print(f" FAILED: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Download simulation data from UC Volume")
    parser.add_argument("--airport", type=str, help="Single airport IATA code (e.g., sfo)")
    parser.add_argument("--all", action="store_true", help="Download all 4 configs per airport")
    parser.add_argument("--list", action="store_true", help="List available files without downloading")
    parser.add_argument("--force", action="store_true", help="Re-download even if file exists")
    args = parser.parse_args()

    client = get_client()

    if args.list:
        list_files(client)
        return

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    airports = [args.airport.lower()] if args.airport else AIRPORTS
    configs = CONFIGS if args.all else ["normal_d1"]

    total = len(airports) * len(configs)
    downloaded = 0
    skipped = 0
    failed = 0

    print(f"Downloading {total} files to {OUTPUT_DIR}/\n")

    for airport in airports:
        for config in configs:
            filename = f"cal_{airport}_{config}.json"
            result = download_file(client, filename, force=args.force)
            if result:
                output_path = OUTPUT_DIR / filename
                if output_path.exists():
                    downloaded += 1
                else:
                    skipped += 1
            else:
                failed += 1

    print(f"\nDone: {downloaded} downloaded, {skipped} skipped, {failed} failed")


if __name__ == "__main__":
    main()
