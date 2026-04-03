"""Tests for OpenSky Network service."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.backend.services.opensky_service import (
    OpenSkyService,
    determine_flight_phase as _determine_flight_phase,
    M_TO_FT as _M_TO_FT,
    MS_TO_KTS as _MS_TO_KTS,
    MS_TO_FTMIN as _MS_TO_FTMIN,
)


# ── Flight phase determination ──

class TestDetermineFlightPhase:
    def test_on_ground(self):
        assert _determine_flight_phase(0, 0, True) == "ground"

    def test_on_ground_overrides_altitude(self):
        assert _determine_flight_phase(5000, 500, True) == "ground"

    def test_takeoff(self):
        assert _determine_flight_phase(1500, 1000, False) == "takeoff"

    def test_landing(self):
        assert _determine_flight_phase(1500, -1000, False) == "landing"

    def test_approaching(self):
        assert _determine_flight_phase(8000, -800, False) == "approaching"

    def test_departing(self):
        assert _determine_flight_phase(8000, 800, False) == "departing"

    def test_climb(self):
        assert _determine_flight_phase(15000, 500, False) == "climb"

    def test_descent(self):
        assert _determine_flight_phase(15000, -500, False) == "descent"

    def test_cruise(self):
        assert _determine_flight_phase(35000, 50, False) == "cruise"


# ── OpenSky state vector to flight conversion ──

# Minimal valid OpenSky state vector (17 fields)
def _make_state(
    icao24="abc123",
    callsign="UAL123  ",
    lat=37.6,
    lon=-122.4,
    baro_alt=3000.0,
    on_ground=False,
    velocity=200.0,
    heading=270.0,
    vrate=5.0,
    last_contact=1700000000,
):
    return [
        icao24,       # 0: icao24
        callsign,     # 1: callsign
        "US",         # 2: origin_country
        1700000000,   # 3: time_position
        last_contact, # 4: last_contact
        lon,          # 5: longitude
        lat,          # 6: latitude
        baro_alt,     # 7: baro_altitude (meters)
        on_ground,    # 8: on_ground
        velocity,     # 9: velocity (m/s)
        heading,      # 10: true_track
        vrate,        # 11: vertical_rate (m/s)
        None,         # 12: sensors
        3100.0,       # 13: geo_altitude
        None,         # 14: squawk
        False,        # 15: spi
        0,            # 16: position_source
    ]


class TestStateToFlight:
    def setup_method(self):
        self.service = OpenSkyService()

    def test_basic_conversion(self):
        state = _make_state()
        result = self.service._state_to_flight(state)
        assert result is not None
        assert result["icao24"] == "abc123"
        assert result["callsign"] == "UAL123"
        assert result["latitude"] == 37.6
        assert result["longitude"] == -122.4
        assert result["data_source"] == "opensky"

    def test_altitude_conversion(self):
        state = _make_state(baro_alt=1000.0)
        result = self.service._state_to_flight(state)
        assert abs(result["altitude"] - 1000.0 * _M_TO_FT) < 0.1

    def test_velocity_conversion(self):
        state = _make_state(velocity=150.0)
        result = self.service._state_to_flight(state)
        assert abs(result["velocity"] - 150.0 * _MS_TO_KTS) < 0.1

    def test_vertical_rate_conversion(self):
        state = _make_state(vrate=10.0)
        result = self.service._state_to_flight(state)
        assert abs(result["vertical_rate"] - 10.0 * _MS_TO_FTMIN) < 0.1

    def test_on_ground(self):
        state = _make_state(on_ground=True)
        result = self.service._state_to_flight(state)
        assert result["on_ground"] is True
        assert result["flight_phase"] == "ground"

    def test_missing_position_returns_none(self):
        state = _make_state(lat=None)
        result = self.service._state_to_flight(state)
        assert result is None

    def test_missing_longitude_returns_none(self):
        state = _make_state(lon=None)
        result = self.service._state_to_flight(state)
        assert result is None

    def test_short_state_returns_none(self):
        result = self.service._state_to_flight(["abc123", "UAL123"])
        assert result is None

    def test_empty_callsign_uses_icao24(self):
        state = _make_state(callsign="        ")
        result = self.service._state_to_flight(state)
        assert result["callsign"] == "ABC123"

    def test_none_callsign_uses_icao24(self):
        state = _make_state(callsign=None)
        result = self.service._state_to_flight(state)
        assert result["callsign"] == "ABC123"


# ── HTTP fetch tests ──

class TestFetchFlights:
    @pytest.fixture
    def service(self):
        return OpenSkyService()

    async def test_successful_fetch(self, service):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "time": 1700000000,
            "states": [_make_state(), _make_state(icao24="def456", callsign="DAL789  ")],
        }

        with patch.object(service._client, "get", new_callable=AsyncMock, return_value=mock_response):
            flights = await service.fetch_flights(37.6, -122.4)

        assert len(flights) == 2
        assert flights[0]["icao24"] == "abc123"
        assert flights[1]["icao24"] == "def456"
        assert service._last_flight_count == 2
        assert service._last_error is None

    async def test_rate_limited(self, service):
        mock_response = MagicMock()
        mock_response.status_code = 429

        with patch.object(service._client, "get", new_callable=AsyncMock, return_value=mock_response):
            flights = await service.fetch_flights(37.6, -122.4)

        assert flights == []
        assert service._last_error == "Rate limited"

    async def test_network_error(self, service):
        with patch.object(
            service._client, "get",
            new_callable=AsyncMock,
            side_effect=Exception("Connection refused"),
        ):
            flights = await service.fetch_flights(37.6, -122.4)

        assert flights == []
        assert "Connection refused" in service._last_error

    async def test_empty_states(self, service):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"time": 1700000000, "states": None}

        with patch.object(service._client, "get", new_callable=AsyncMock, return_value=mock_response):
            flights = await service.fetch_flights(37.6, -122.4)

        assert flights == []

    async def test_bounding_box_params(self, service):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"time": 1700000000, "states": []}

        with patch.object(service._client, "get", new_callable=AsyncMock, return_value=mock_response) as mock_get:
            await service.fetch_flights(40.0, -74.0, radius_deg=0.3)

        call_kwargs = mock_get.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params")
        assert abs(params["lamin"] - 39.7) < 0.01
        assert abs(params["lamax"] - 40.3) < 0.01
        assert abs(params["lomin"] - (-74.3)) < 0.01
        assert abs(params["lomax"] - (-73.7)) < 0.01


# ── Status ──

class TestFetchFlightsAuth:
    """Tests for authenticated requests."""

    async def test_auth_passed_to_client(self):
        service = OpenSkyService(username="user", password="pass")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"time": 1700000000, "states": []}

        with patch.object(service._client, "get", new_callable=AsyncMock, return_value=mock_response) as mock_get:
            await service.fetch_flights(37.6, -122.4)

        call_kwargs = mock_get.call_args.kwargs
        assert call_kwargs["auth"] == ("user", "pass")

    async def test_no_auth_when_no_credentials(self):
        service = OpenSkyService()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"time": 1700000000, "states": []}

        with patch.object(service._client, "get", new_callable=AsyncMock, return_value=mock_response) as mock_get:
            await service.fetch_flights(37.6, -122.4)

        call_kwargs = mock_get.call_args.kwargs
        assert "auth" not in call_kwargs


class TestFetchFlightsEdgeCases:
    """Edge cases for fetch_flights."""

    async def test_http_status_error(self):
        """HTTPStatusError (e.g., 500) returns empty list."""
        import httpx
        service = OpenSkyService()
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server Error", request=MagicMock(), response=mock_response,
        )

        with patch.object(service._client, "get", new_callable=AsyncMock, return_value=mock_response):
            flights = await service.fetch_flights(37.6, -122.4)

        assert flights == []
        assert "HTTP 500" in service._last_error

    async def test_skips_invalid_states_in_batch(self):
        """Flights with missing position are skipped; valid ones are kept."""
        service = OpenSkyService()
        good_state = _make_state(icao24="good1")
        bad_state = _make_state(icao24="bad1", lat=None)
        short_state = ["short"]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "time": 1700000000,
            "states": [good_state, bad_state, short_state],
        }

        with patch.object(service._client, "get", new_callable=AsyncMock, return_value=mock_response):
            flights = await service.fetch_flights(37.6, -122.4)

        assert len(flights) == 1
        assert flights[0]["icao24"] == "good1"

    async def test_custom_radius(self):
        """Custom radius_deg is applied correctly."""
        service = OpenSkyService()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"time": 1700000000, "states": []}

        with patch.object(service._client, "get", new_callable=AsyncMock, return_value=mock_response) as mock_get:
            await service.fetch_flights(50.0, 8.0, radius_deg=1.0)

        params = mock_get.call_args.kwargs["params"]
        assert abs(params["lamin"] - 49.0) < 0.01
        assert abs(params["lamax"] - 51.0) < 0.01


class TestStateToFlightEdgeCases:
    """Additional edge cases for state vector conversion."""

    def setup_method(self):
        self.service = OpenSkyService()

    def test_none_baro_altitude(self):
        """None altitude defaults to 0."""
        state = _make_state(baro_alt=None)
        # Patch the state directly since _make_state uses default
        state[7] = None
        result = self.service._state_to_flight(state)
        assert result is not None
        assert result["altitude"] == 0.0

    def test_none_velocity(self):
        """None velocity defaults to 0."""
        state = _make_state()
        state[9] = None
        result = self.service._state_to_flight(state)
        assert result is not None
        assert result["velocity"] == 0.0

    def test_none_vertical_rate(self):
        """None vertical_rate defaults to 0."""
        state = _make_state()
        state[11] = None
        result = self.service._state_to_flight(state)
        assert result is not None
        assert result["vertical_rate"] == 0.0

    def test_none_heading(self):
        """None heading is passed through."""
        state = _make_state()
        state[10] = None
        result = self.service._state_to_flight(state)
        assert result is not None
        assert result["heading"] is None

    def test_last_contact_preserved(self):
        """last_contact timestamp is preserved as last_seen."""
        state = _make_state(last_contact=1700001234)
        result = self.service._state_to_flight(state)
        assert result["last_seen"] == 1700001234

    def test_output_has_all_required_fields(self):
        """All FlightPosition-compatible fields are present."""
        state = _make_state()
        result = self.service._state_to_flight(state)
        required = {
            "icao24", "callsign", "latitude", "longitude", "altitude",
            "velocity", "heading", "on_ground", "vertical_rate", "last_seen",
            "data_source", "flight_phase", "aircraft_type", "assigned_gate",
            "origin_airport", "destination_airport",
        }
        assert set(result.keys()) == required


class TestGetStatus:
    def test_status_no_fetches(self):
        service = OpenSkyService()
        status = service.get_status()
        assert status["available"] is True
        assert status["last_fetch_time"] is None
        assert status["last_flight_count"] == 0
        assert status["authenticated"] is False

    def test_status_with_auth(self):
        service = OpenSkyService(username="user", password="pass")
        status = service.get_status()
        assert status["authenticated"] is True

    async def test_status_after_successful_fetch(self):
        """Status reflects data from last successful fetch."""
        service = OpenSkyService()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "time": 1700000000,
            "states": [_make_state(), _make_state(icao24="def456")],
        }

        with patch.object(service._client, "get", new_callable=AsyncMock, return_value=mock_response):
            await service.fetch_flights(37.6, -122.4)

        status = service.get_status()
        assert status["last_flight_count"] == 2
        assert status["last_fetch_time"] is not None
        assert status["last_error"] is None

    async def test_status_after_error(self):
        """Status reflects error from last failed fetch."""
        service = OpenSkyService()
        with patch.object(
            service._client, "get",
            new_callable=AsyncMock,
            side_effect=Exception("Timeout"),
        ):
            await service.fetch_flights(37.6, -122.4)

        status = service.get_status()
        assert "Timeout" in status["last_error"]


class TestSingleton:
    """Test singleton accessor."""

    def test_get_opensky_service_returns_same_instance(self):
        from app.backend.services.opensky_service import get_opensky_service
        import app.backend.services.opensky_service as mod
        # Reset singleton
        mod._opensky_service = None
        s1 = get_opensky_service()
        s2 = get_opensky_service()
        assert s1 is s2
        mod._opensky_service = None  # cleanup
