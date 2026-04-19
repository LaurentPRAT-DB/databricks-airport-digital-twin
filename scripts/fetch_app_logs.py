"""Fetch recent errors/warnings from the deployed Airport Digital Twin app.

Uses the Databricks CLI token for auth. Designed for Claude Code's devloop
to diagnose post-deploy runtime issues.

Usage:
    uv run python scripts/fetch_app_logs.py [--limit N] [--profile PROFILE] [--url URL]
"""

import argparse
import json
import subprocess
import sys
import urllib.request
import urllib.error

APP_URL = "https://airport-digital-twin-dev-7474645572615955.aws.databricksapps.com"
DB_PROFILE = "FEVM_SERVERLESS_STABLE"


def get_databricks_token(profile: str) -> str:
    result = subprocess.run(
        ["databricks", "auth", "token", "--profile", profile],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"Failed to get Databricks token: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    return json.loads(result.stdout)["access_token"]


def main():
    parser = argparse.ArgumentParser(description="Fetch recent app errors")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--profile", default=DB_PROFILE)
    parser.add_argument("--url", default=APP_URL)
    args = parser.parse_args()

    token = get_databricks_token(args.profile)
    url = f"{args.url}/api/debug/recent-errors?limit={args.limit}"

    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    })

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        print(f"HTTP {e.code}: {body}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Request failed: {e}", file=sys.stderr)
        sys.exit(1)

    # Display results
    n_err = data.get("error_count", 0)
    n_warn = data.get("warning_count", 0)
    total = data.get("total_buffered", 0)

    print(f"Ring buffer: {total} total lines, {n_err} errors, {n_warn} warnings\n")

    if data.get("errors"):
        print(f"=== ERRORS ({len(data['errors'])}) ===")
        for line in data["errors"]:
            print(f"  {line}")
        print()

    if data.get("warnings"):
        print(f"=== WARNINGS ({len(data['warnings'])}) ===")
        for line in data["warnings"][-20:]:  # cap output
            print(f"  {line}")
        if len(data["warnings"]) > 20:
            print(f"  ... and {len(data['warnings']) - 20} more")
        print()

    if n_err == 0 and n_warn == 0:
        print("No errors or warnings in the buffer.")


if __name__ == "__main__":
    main()
