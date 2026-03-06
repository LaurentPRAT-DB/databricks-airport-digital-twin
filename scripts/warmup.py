#!/usr/bin/env python3
"""
Service warm-up script for Airport Digital Twin.

Pre-warms all API endpoints to avoid cold-start delays during demo.
Makes multiple requests to each endpoint to warm caches and load models.

Usage:
    python scripts/warmup.py
    python scripts/warmup.py --url https://airport-digital-twin-dev.aws.databricksapps.com
    python scripts/warmup.py --requests 5  # Number of warmup requests per endpoint
"""

import argparse
import statistics
import sys
import time
from dataclasses import dataclass

import httpx


@dataclass
class WarmupResult:
    """Result of warming up an endpoint."""
    endpoint: str
    requests_made: int
    avg_response_ms: float
    min_response_ms: float
    max_response_ms: float
    success_rate: float
    is_warm: bool  # True if avg response < threshold


def warmup_endpoint(
    client: httpx.Client,
    url: str,
    num_requests: int = 3,
    threshold_ms: float = 2000.0
) -> WarmupResult:
    """Warm up a single endpoint with multiple requests."""
    response_times = []
    successes = 0

    for i in range(num_requests):
        start = time.time()
        try:
            resp = client.get(url, timeout=30.0)
            elapsed = (time.time() - start) * 1000
            response_times.append(elapsed)
            if resp.status_code in (200, 401):  # 401 is OK for deployed app
                successes += 1
        except Exception:
            elapsed = (time.time() - start) * 1000
            response_times.append(elapsed)

        # Small delay between requests
        if i < num_requests - 1:
            time.sleep(0.5)

    avg_ms = statistics.mean(response_times) if response_times else 0
    min_ms = min(response_times) if response_times else 0
    max_ms = max(response_times) if response_times else 0

    return WarmupResult(
        endpoint=url,
        requests_made=num_requests,
        avg_response_ms=avg_ms,
        min_response_ms=min_ms,
        max_response_ms=max_ms,
        success_rate=successes / num_requests if num_requests > 0 else 0,
        is_warm=avg_ms < threshold_ms
    )


def run_warmup(base_url: str, num_requests: int = 3) -> list[WarmupResult]:
    """Warm up all API endpoints."""
    endpoints = [
        "/health",
        "/api/flights",
        "/api/predictions/delays",
        "/api/predictions/congestion",
        "/api/predictions/bottlenecks",
    ]

    results = []
    with httpx.Client() as client:
        for endpoint in endpoints:
            url = f"{base_url}{endpoint}"
            print(f"  Warming up {endpoint}...", end=" ", flush=True)
            result = warmup_endpoint(client, url, num_requests)
            status = "✅" if result.is_warm else "⚠️"
            print(f"{status} avg {result.avg_response_ms:.0f}ms")
            results.append(result)

    return results


def print_summary(results: list[WarmupResult], total_time: float) -> bool:
    """Print warmup summary and return True if all endpoints are warm."""
    all_warm = all(r.is_warm for r in results)

    print("\n" + "=" * 60)
    print("  WARMUP SUMMARY")
    print("=" * 60 + "\n")

    for r in results:
        status = "✅" if r.is_warm else "⚠️"
        endpoint_name = r.endpoint.split("/")[-1] or "health"
        print(f"  {status} {endpoint_name.upper()}")
        print(f"     Requests: {r.requests_made} ({r.success_rate*100:.0f}% success)")
        print(f"     Response: avg={r.avg_response_ms:.0f}ms min={r.min_response_ms:.0f}ms max={r.max_response_ms:.0f}ms")
        print()

    print("-" * 60)
    print(f"  Total warmup time: {total_time:.1f}s")
    if all_warm:
        print("  ✅ ALL ENDPOINTS WARMED - Ready for demo!")
    else:
        print("  ⚠️ SOME ENDPOINTS SLOW - May experience initial latency")
    print("-" * 60 + "\n")

    return all_warm


def main():
    parser = argparse.ArgumentParser(description="Warm up Airport Digital Twin services")
    parser.add_argument(
        "--url",
        default="http://localhost:8000",
        help="Base URL of the application (default: http://localhost:8000)"
    )
    parser.add_argument(
        "--requests",
        type=int,
        default=3,
        help="Number of warmup requests per endpoint (default: 3)"
    )
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("  AIRPORT DIGITAL TWIN - SERVICE WARMUP")
    print("=" * 60 + "\n")
    print(f"  Target: {args.url}")
    print(f"  Requests per endpoint: {args.requests}")
    print()

    start_time = time.time()
    results = run_warmup(args.url, args.requests)
    total_time = time.time() - start_time

    all_warm = print_summary(results, total_time)
    sys.exit(0 if all_warm else 1)


if __name__ == "__main__":
    main()
