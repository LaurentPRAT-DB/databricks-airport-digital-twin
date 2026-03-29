"""Create the aircraft inpainting Model Serving endpoint.

Run after the model is registered in Unity Catalog via the registration job.

Usage:
    databricks bundle run inpainting_model_registration --target dev
    uv run python scripts/create_inpainting_endpoint.py
"""

import json
import subprocess
import sys

CATALOG = "serverless_stable_3n0ihb_catalog"
SCHEMA = "airport_digital_twin"
MODEL_NAME = f"{CATALOG}.{SCHEMA}.aircraft_inpainting_model"
ENDPOINT_NAME = "airport-dt-aircraft-inpainting-dev"
PROFILE = "FEVM_SERVERLESS_STABLE"


def run_cli(args: list[str]) -> dict | str:
    """Run a databricks CLI command and return parsed JSON or raw text."""
    result = subprocess.run(
        ["databricks"] + args + ["--profile", PROFILE],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"Error: {result.stderr}", file=sys.stderr)
        return {"error": result.stderr}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return result.stdout.strip()


def check_model_exists() -> bool:
    """Check if the model is registered in UC."""
    result = run_cli([
        "api", "get",
        f"/api/2.0/unity-catalog/models/{MODEL_NAME}",
    ])
    if isinstance(result, dict) and "error" not in result:
        print(f"Model found: {MODEL_NAME}")
        return True
    print(f"Model not found: {MODEL_NAME}")
    print("Run: databricks bundle run inpainting_model_registration --target dev")
    return False


def check_endpoint_exists() -> bool:
    """Check if the serving endpoint already exists."""
    result = run_cli([
        "serving-endpoints", "get", ENDPOINT_NAME,
    ])
    if isinstance(result, dict) and "name" in result:
        state = result.get("state", {}).get("ready", "UNKNOWN")
        print(f"Endpoint already exists: {ENDPOINT_NAME} (state: {state})")
        return True
    return False


def create_endpoint():
    """Create the serving endpoint."""
    config = {
        "name": ENDPOINT_NAME,
        "config": {
            "served_entities": [
                {
                    "entity_name": MODEL_NAME,
                    "entity_version": "1",
                    "workload_size": "Small",
                    "workload_type": "GPU_MEDIUM",
                    "scale_to_zero_enabled": True,
                }
            ],
        },
        "tags": [
            {"key": "project", "value": "airport-digital-twin"},
            {"key": "component", "value": "inpainting"},
        ],
    }

    print(f"Creating serving endpoint: {ENDPOINT_NAME}")
    print(f"  Model: {MODEL_NAME}")
    print(f"  Workload: GPU_MEDIUM (T4), scale-to-zero")

    result = run_cli([
        "api", "post",
        "/api/2.0/serving-endpoints",
        "--json", json.dumps(config),
    ])

    if isinstance(result, dict) and "name" in result:
        print(f"Endpoint created: {result['name']}")
        print(f"State: {result.get('state', {})}")
    else:
        print(f"Result: {result}")


if __name__ == "__main__":
    if not check_model_exists():
        sys.exit(1)

    if check_endpoint_exists():
        print("Endpoint already exists, no action needed.")
        sys.exit(0)

    create_endpoint()
    print("\nEndpoint creation initiated. Monitor with:")
    print(f"  databricks serving-endpoints get {ENDPOINT_NAME} --profile {PROFILE}")
