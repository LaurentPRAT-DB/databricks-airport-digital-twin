"""Local API smoke test — fast sanity check for all critical endpoints.

Uses FastAPI TestClient (no network, no deploy needed). Outputs a structured
JSON report that Claude Code can parse to diagnose issues.

Usage:
    uv run python scripts/test_api_local.py
"""

import json
import os
import sys
import time
from pathlib import Path

# Ensure project root is on sys.path when running as script
_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from fastapi.testclient import TestClient

from app.backend.main import app

REPORT_DIR = Path("test-results")
REPORT_DIR.mkdir(exist_ok=True)

client = TestClient(app)


def check(name: str, method: str, url: str, expect_status: int = 200, expect_keys: list[str] | None = None):
    """Run one endpoint check and return result dict."""
    start = time.monotonic()
    try:
        resp = getattr(client, method)(url)
        elapsed_ms = round((time.monotonic() - start) * 1000)
        body = None
        try:
            body = resp.json()
        except Exception:
            body = resp.text[:500]

        ok = resp.status_code == expect_status
        missing_keys = []
        if ok and expect_keys and isinstance(body, dict):
            missing_keys = [k for k in expect_keys if k not in body]
            if missing_keys:
                ok = False

        return {
            "name": name,
            "url": url,
            "status": "pass" if ok else "fail",
            "http_status": resp.status_code,
            "elapsed_ms": elapsed_ms,
            "missing_keys": missing_keys,
            "response_sample": _sample(body),
        }
    except Exception as e:
        elapsed_ms = round((time.monotonic() - start) * 1000)
        return {
            "name": name,
            "url": url,
            "status": "error",
            "error": str(e),
            "elapsed_ms": elapsed_ms,
        }


def _sample(body):
    """Truncate response body for report readability."""
    if body is None:
        return None
    if isinstance(body, dict):
        # Show keys + first few values
        keys = list(body.keys())[:10]
        sample = {}
        for k in keys:
            v = body[k]
            if isinstance(v, list):
                sample[k] = f"[{len(v)} items]"
            elif isinstance(v, str) and len(v) > 100:
                sample[k] = v[:100] + "..."
            else:
                sample[k] = v
        return sample
    if isinstance(body, list):
        return f"[{len(body)} items]"
    return str(body)[:200]


def main():
    results = []

    results.append(check("health", "get", "/health", 200, ["status", "airport"]))
    results.append(check("ready", "get", "/api/ready", 200, ["ready", "status"]))
    results.append(check("flights", "get", "/api/flights", 200, ["flights"]))
    results.append(check("weather", "get", "/api/weather", 200))
    results.append(check("schedule_departures", "get", "/api/schedule/departures", 200, ["flights"]))
    results.append(check("schedule_arrivals", "get", "/api/schedule/arrivals", 200, ["flights"]))
    results.append(check("predictions", "get", "/api/predictions", 200))
    results.append(check("gates", "get", "/api/gates", 200))
    results.append(check("simulation_files", "get", "/api/simulation/files", 200))
    results.append(check("airport_config", "get", "/api/airport/config", 200))

    passed = sum(1 for r in results if r["status"] == "pass")
    failed = sum(1 for r in results if r["status"] == "fail")
    errors = sum(1 for r in results if r["status"] == "error")

    report = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "summary": {"pass": passed, "fail": failed, "error": errors, "total": len(results)},
        "results": results,
    }

    report_path = REPORT_DIR / "api_local_report.json"
    report_path.write_text(json.dumps(report, indent=2))

    # Console output
    for r in results:
        icon = {"pass": "\033[32mPASS\033[0m", "fail": "\033[31mFAIL\033[0m", "error": "\033[31mERROR\033[0m"}[r["status"]]
        extra = ""
        if r.get("missing_keys"):
            extra = f" (missing: {r['missing_keys']})"
        elif r.get("error"):
            extra = f" ({r['error'][:60]})"
        print(f"  [{icon}] {r['name']:25s} {r.get('http_status', '???'):>3} {r['elapsed_ms']:>5}ms{extra}")

    print(f"\n{'='*50}")
    print(f"Results: \033[32m{passed} passed\033[0m, \033[31m{failed} failed\033[0m, {errors} errors")
    print(f"Report: {report_path}")
    print(f"{'='*50}")

    sys.exit(0 if failed == 0 and errors == 0 else 1)


if __name__ == "__main__":
    main()
