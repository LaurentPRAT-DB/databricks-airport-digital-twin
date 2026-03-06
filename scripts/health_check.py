#!/usr/bin/env python3
"""
Pre-demo health check script for Airport Digital Twin.

Validates all services are operational before a demo presentation.
Exit code 0 = all services healthy, 1 = one or more services unhealthy.

Usage:
    python scripts/health_check.py
    python scripts/health_check.py --url https://airport-digital-twin-dev.aws.databricksapps.com
    python scripts/health_check.py --json  # Output as JSON
"""

import argparse
import json
import sys
import time
from dataclasses import dataclass
from typing import Optional

import httpx


@dataclass
class ServiceStatus:
    """Status of a single service check."""
    name: str
    healthy: bool
    response_time_ms: float
    message: str
    details: Optional[dict] = None


def check_health_endpoint(client: httpx.Client, base_url: str) -> ServiceStatus:
    """Check the /health endpoint."""
    start = time.time()
    try:
        resp = client.get(f"{base_url}/health", timeout=10.0)
        elapsed = (time.time() - start) * 1000

        if resp.status_code == 200:
            return ServiceStatus(
                name="health",
                healthy=True,
                response_time_ms=elapsed,
                message="Backend is healthy",
                details=resp.json() if resp.headers.get("content-type", "").startswith("application/json") else None
            )
        else:
            return ServiceStatus(
                name="health",
                healthy=False,
                response_time_ms=elapsed,
                message=f"Health check failed with status {resp.status_code}"
            )
    except Exception as e:
        elapsed = (time.time() - start) * 1000
        return ServiceStatus(
            name="health",
            healthy=False,
            response_time_ms=elapsed,
            message=f"Health check error: {str(e)}"
        )


def check_flights_endpoint(client: httpx.Client, base_url: str) -> ServiceStatus:
    """Check the /api/flights endpoint."""
    start = time.time()
    try:
        resp = client.get(f"{base_url}/api/flights", timeout=15.0)
        elapsed = (time.time() - start) * 1000

        if resp.status_code == 200:
            data = resp.json()
            flight_count = data.get("count", 0)
            data_source = data.get("data_source", "unknown")
            return ServiceStatus(
                name="flights",
                healthy=True,
                response_time_ms=elapsed,
                message=f"Flights API returned {flight_count} flights ({data_source})",
                details={"count": flight_count, "data_source": data_source}
            )
        elif resp.status_code == 401:
            return ServiceStatus(
                name="flights",
                healthy=True,  # 401 means the endpoint exists but needs auth
                response_time_ms=elapsed,
                message="Flights API requires authentication (expected for deployed app)"
            )
        else:
            return ServiceStatus(
                name="flights",
                healthy=False,
                response_time_ms=elapsed,
                message=f"Flights API failed with status {resp.status_code}"
            )
    except Exception as e:
        elapsed = (time.time() - start) * 1000
        return ServiceStatus(
            name="flights",
            healthy=False,
            response_time_ms=elapsed,
            message=f"Flights API error: {str(e)}"
        )


def check_predictions_endpoint(client: httpx.Client, base_url: str) -> ServiceStatus:
    """Check the /api/predictions/delays endpoint."""
    start = time.time()
    try:
        resp = client.get(f"{base_url}/api/predictions/delays", timeout=15.0)
        elapsed = (time.time() - start) * 1000

        if resp.status_code == 200:
            data = resp.json()
            delay_count = data.get("count", 0)
            return ServiceStatus(
                name="predictions",
                healthy=True,
                response_time_ms=elapsed,
                message=f"Predictions API returned {delay_count} delay predictions",
                details={"count": delay_count}
            )
        elif resp.status_code == 401:
            return ServiceStatus(
                name="predictions",
                healthy=True,
                response_time_ms=elapsed,
                message="Predictions API requires authentication (expected for deployed app)"
            )
        else:
            return ServiceStatus(
                name="predictions",
                healthy=False,
                response_time_ms=elapsed,
                message=f"Predictions API failed with status {resp.status_code}"
            )
    except Exception as e:
        elapsed = (time.time() - start) * 1000
        return ServiceStatus(
            name="predictions",
            healthy=False,
            response_time_ms=elapsed,
            message=f"Predictions API error: {str(e)}"
        )


def check_congestion_endpoint(client: httpx.Client, base_url: str) -> ServiceStatus:
    """Check the /api/predictions/congestion endpoint."""
    start = time.time()
    try:
        resp = client.get(f"{base_url}/api/predictions/congestion", timeout=15.0)
        elapsed = (time.time() - start) * 1000

        if resp.status_code == 200:
            data = resp.json()
            area_count = data.get("count", 0)
            return ServiceStatus(
                name="congestion",
                healthy=True,
                response_time_ms=elapsed,
                message=f"Congestion API returned {area_count} areas",
                details={"count": area_count}
            )
        elif resp.status_code == 401:
            return ServiceStatus(
                name="congestion",
                healthy=True,
                response_time_ms=elapsed,
                message="Congestion API requires authentication (expected for deployed app)"
            )
        else:
            return ServiceStatus(
                name="congestion",
                healthy=False,
                response_time_ms=elapsed,
                message=f"Congestion API failed with status {resp.status_code}"
            )
    except Exception as e:
        elapsed = (time.time() - start) * 1000
        return ServiceStatus(
            name="congestion",
            healthy=False,
            response_time_ms=elapsed,
            message=f"Congestion API error: {str(e)}"
        )


def run_health_check(base_url: str) -> list[ServiceStatus]:
    """Run all health checks and return results."""
    with httpx.Client() as client:
        results = [
            check_health_endpoint(client, base_url),
            check_flights_endpoint(client, base_url),
            check_predictions_endpoint(client, base_url),
            check_congestion_endpoint(client, base_url),
        ]
    return results


def print_results(results: list[ServiceStatus], as_json: bool = False) -> bool:
    """Print results and return True if all healthy."""
    all_healthy = all(r.healthy for r in results)

    if as_json:
        output = {
            "healthy": all_healthy,
            "services": [
                {
                    "name": r.name,
                    "healthy": r.healthy,
                    "response_time_ms": round(r.response_time_ms, 2),
                    "message": r.message,
                    "details": r.details
                }
                for r in results
            ]
        }
        print(json.dumps(output, indent=2))
    else:
        print("\n" + "=" * 60)
        print("  AIRPORT DIGITAL TWIN - HEALTH CHECK")
        print("=" * 60 + "\n")

        for r in results:
            status_icon = "✅" if r.healthy else "❌"
            print(f"  {status_icon} {r.name.upper()}")
            print(f"     Response: {r.response_time_ms:.0f}ms")
            print(f"     {r.message}")
            print()

        print("-" * 60)
        if all_healthy:
            print("  ✅ ALL SERVICES HEALTHY - Ready for demo!")
        else:
            print("  ❌ SOME SERVICES UNHEALTHY - Check issues above")
        print("-" * 60 + "\n")

    return all_healthy


def main():
    parser = argparse.ArgumentParser(description="Health check for Airport Digital Twin")
    parser.add_argument(
        "--url",
        default="http://localhost:8000",
        help="Base URL of the application (default: http://localhost:8000)"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON"
    )
    args = parser.parse_args()

    results = run_health_check(args.url)
    all_healthy = print_results(results, as_json=args.json)

    sys.exit(0 if all_healthy else 1)


if __name__ == "__main__":
    main()
