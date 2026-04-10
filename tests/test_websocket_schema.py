"""Tests that backend WebSocket delta fields match the frontend Flight interface.

The backend _DELTA_FIELDS set defines which flight fields are sent as deltas.
The frontend Flight interface in flight.ts defines the expected shape.
These must stay in sync — a field in _DELTA_FIELDS that doesn't exist in Flight
will cause silent data loss in the frontend.
"""

import re
from pathlib import Path

import pytest

from app.backend.api.websocket import _DELTA_FIELDS


# Parse frontend Flight interface fields from TypeScript
_FLIGHT_TS = Path("app/frontend/src/types/flight.ts")


def _parse_flight_interface_fields() -> set[str]:
    """Extract field names from the `export interface Flight { ... }` block."""
    if not _FLIGHT_TS.exists():
        pytest.skip("Frontend flight.ts not found")

    text = _FLIGHT_TS.read_text()
    # Find the Flight interface block
    match = re.search(
        r"export\s+interface\s+Flight\s*\{(.*?)\}",
        text,
        re.DOTALL,
    )
    if not match:
        pytest.fail("Could not find 'export interface Flight' in flight.ts")

    body = match.group(1)
    fields = set()
    for line in body.split("\n"):
        line = line.strip()
        if not line or line.startswith("//") or line.startswith("|"):
            continue
        # Match field declarations like:  icao24: string;  or  aircraft_type?: string;
        field_match = re.match(r"(\w+)\??:", line)
        if field_match:
            fields.add(field_match.group(1))
    return fields


class TestDeltaFieldsMatchFrontend:
    """Verify _DELTA_FIELDS are a subset of the frontend Flight interface."""

    def test_delta_fields_exist_in_flight_interface(self):
        """Every field in _DELTA_FIELDS must exist in the Flight TypeScript interface."""
        ts_fields = _parse_flight_interface_fields()
        missing = _DELTA_FIELDS - ts_fields
        assert not missing, (
            f"Backend _DELTA_FIELDS contain fields not in frontend Flight interface: {missing}. "
            f"Flight interface fields: {sorted(ts_fields)}"
        )

    def test_delta_fields_are_non_empty(self):
        assert len(_DELTA_FIELDS) > 0, "_DELTA_FIELDS should not be empty"

    def test_icao24_not_in_delta_fields(self):
        """icao24 is the identity key, not a delta field."""
        assert "icao24" not in _DELTA_FIELDS

    def test_flight_interface_has_icao24(self):
        """Frontend Flight must have icao24 as the identity key."""
        ts_fields = _parse_flight_interface_fields()
        assert "icao24" in ts_fields


class TestWebSocketMessageTypes:
    """Verify backend WebSocket message types match what the frontend expects."""

    def test_backend_sends_expected_message_types(self):
        """Check that the backend websocket.py defines handlers for expected message types."""
        ws_source = Path("app/backend/api/websocket.py").read_text()

        # These are the message types the frontend listens for
        expected_types = {"flight_delta", "mode_change", "airport_switch_progress"}
        for msg_type in expected_types:
            assert f'"{msg_type}"' in ws_source, (
                f"Backend websocket.py does not produce message type '{msg_type}'"
            )

    def test_frontend_handles_backend_message_types(self):
        """Check that the frontend useFlights.ts handles the message types the backend sends."""
        hooks_path = Path("app/frontend/src/hooks/useFlights.ts")
        if not hooks_path.exists():
            pytest.skip("Frontend useFlights.ts not found")

        source = hooks_path.read_text()
        expected_types = ["flight_delta", "airport_switch_progress", "airport_switch_complete"]
        for msg_type in expected_types:
            assert msg_type in source, (
                f"Frontend useFlights.ts does not handle message type '{msg_type}'"
            )


class TestComputeDeltas:
    """Verify _compute_deltas output keys are valid Flight fields."""

    def test_compute_deltas_output_keys_subset_of_flight(self):
        """Delta output keys must be a subset of Flight interface fields + icao24."""
        from app.backend.api.websocket import _compute_deltas

        ts_fields = _parse_flight_interface_fields()

        # Simulate a flight update
        prev = {
            "ABC123": {
                "icao24": "ABC123",
                "latitude": 37.0,
                "longitude": -122.0,
                "altitude": 10000,
                "heading": 90,
                "velocity": 250,
                "on_ground": False,
                "vertical_rate": 0,
                "flight_phase": "enroute",
                "callsign": "UAL123",
            }
        }
        current = [{
            "icao24": "ABC123",
            "latitude": 37.1,
            "longitude": -122.1,
            "altitude": 10500,
            "heading": 95,
            "velocity": 255,
            "on_ground": False,
            "vertical_rate": 500,
            "flight_phase": "enroute",
            "callsign": "UAL123",
        }]

        deltas, removed = _compute_deltas(prev, current)
        for delta in deltas:
            for key in delta:
                assert key in ts_fields, (
                    f"Delta key '{key}' not in Flight interface fields: {sorted(ts_fields)}"
                )
