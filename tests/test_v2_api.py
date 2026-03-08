"""Tests for V2 API endpoints: Schedule, Weather, GSE, Baggage."""

import pytest
from fastapi.testclient import TestClient
from datetime import datetime

from app.backend.main import app
from app.backend.models.schedule import ScheduledFlight, FlightStatus, FlightType
from app.backend.models.weather import METAR, FlightCategory, CloudLayer, SkyCondition
from app.backend.models.gse import GSEUnit, GSEType, GSEStatus, TurnaroundPhase
from app.backend.models.baggage import Bag, BagStatus, FlightBaggageStats


@pytest.fixture
def client():
    """Create a test client for the FastAPI app."""
    return TestClient(app)


# ==============================================================================
# Schedule/FIDS API Tests
# ==============================================================================

class TestScheduleEndpoints:
    """Tests for the schedule/FIDS API endpoints."""

    def test_arrivals_endpoint(self, client):
        """Test that arrivals endpoint returns scheduled flights."""
        response = client.get("/api/schedule/arrivals")

        assert response.status_code == 200
        data = response.json()

        # Verify response structure
        assert "flights" in data
        assert "count" in data
        assert "airport" in data
        assert "flight_type" in data
        assert data["flight_type"] == "arrival"

    def test_departures_endpoint(self, client):
        """Test that departures endpoint returns scheduled flights."""
        response = client.get("/api/schedule/departures")

        assert response.status_code == 200
        data = response.json()

        assert "flights" in data
        assert "count" in data
        assert data["flight_type"] == "departure"

    def test_arrivals_with_params(self, client):
        """Test arrivals with custom time window parameters."""
        response = client.get("/api/schedule/arrivals?hours_ahead=4&hours_behind=2&limit=20")

        assert response.status_code == 200
        data = response.json()
        assert data["count"] <= 20

    def test_departures_with_params(self, client):
        """Test departures with custom time window parameters."""
        response = client.get("/api/schedule/departures?hours_ahead=6&limit=30")

        assert response.status_code == 200
        data = response.json()
        assert data["count"] <= 30

    def test_schedule_flight_fields(self, client):
        """Test that scheduled flights have all required fields."""
        response = client.get("/api/schedule/arrivals?limit=10")
        assert response.status_code == 200

        data = response.json()
        if data["flights"]:
            flight = data["flights"][0]

            # Check required fields
            assert "flight_number" in flight
            assert "airline" in flight
            assert "airline_code" in flight
            assert "origin" in flight
            assert "destination" in flight
            assert "scheduled_time" in flight
            assert "status" in flight
            assert "gate" in flight
            assert "flight_type" in flight

    def test_schedule_status_values(self, client):
        """Test that flight status values are valid."""
        response = client.get("/api/schedule/arrivals?limit=50")
        assert response.status_code == 200

        data = response.json()
        valid_statuses = {"scheduled", "on_time", "delayed", "boarding", "departed", "arrived", "cancelled"}

        for flight in data["flights"]:
            assert flight["status"] in valid_statuses

    def test_schedule_delay_fields(self, client):
        """Test that delayed flights have delay information."""
        response = client.get("/api/schedule/arrivals?limit=100")
        assert response.status_code == 200

        data = response.json()
        for flight in data["flights"]:
            if flight["status"] == "delayed":
                assert flight["delay_minutes"] > 0
                # Estimated time should be set for delayed flights
                assert flight["estimated_time"] is not None

    def test_arrivals_invalid_params(self, client):
        """Test arrivals endpoint with invalid parameters."""
        # hours_ahead too large
        response = client.get("/api/schedule/arrivals?hours_ahead=100")
        assert response.status_code == 422

        # limit too large
        response = client.get("/api/schedule/arrivals?limit=500")
        assert response.status_code == 422

    def test_schedule_airport_codes(self, client):
        """Test that airport codes are valid 3-letter codes."""
        response = client.get("/api/schedule/arrivals?limit=20")
        assert response.status_code == 200

        data = response.json()
        for flight in data["flights"]:
            assert len(flight["origin"]) == 3
            assert len(flight["destination"]) == 3
            assert flight["origin"].isupper()
            assert flight["destination"].isupper()


# ==============================================================================
# Weather API Tests
# ==============================================================================

class TestWeatherEndpoints:
    """Tests for the weather API endpoints."""

    def test_current_weather_endpoint(self, client):
        """Test that current weather endpoint returns METAR data."""
        response = client.get("/api/weather/current")

        assert response.status_code == 200
        data = response.json()

        # Verify response structure
        assert "metar" in data
        assert "station" in data
        assert "timestamp" in data

    def test_weather_with_station(self, client):
        """Test weather endpoint with custom station."""
        response = client.get("/api/weather/current?station=KLAX")

        assert response.status_code == 200
        data = response.json()
        assert data["station"] == "KLAX"

    def test_metar_fields(self, client):
        """Test that METAR has all required fields."""
        response = client.get("/api/weather/current")
        assert response.status_code == 200

        metar = response.json()["metar"]

        # Check required fields
        assert "station" in metar
        assert "observation_time" in metar
        assert "wind_speed_kts" in metar
        assert "visibility_sm" in metar
        assert "temperature_c" in metar
        assert "dewpoint_c" in metar
        assert "altimeter_inhg" in metar
        assert "flight_category" in metar
        assert "clouds" in metar

    def test_flight_category_values(self, client):
        """Test that flight category is valid."""
        response = client.get("/api/weather/current")
        assert response.status_code == 200

        metar = response.json()["metar"]
        valid_categories = {"VFR", "MVFR", "IFR", "LIFR"}
        assert metar["flight_category"] in valid_categories

    def test_wind_values(self, client):
        """Test that wind values are reasonable."""
        response = client.get("/api/weather/current")
        assert response.status_code == 200

        metar = response.json()["metar"]

        # Wind direction 0-360 or None for variable
        if metar["wind_direction"] is not None:
            assert 0 <= metar["wind_direction"] <= 360

        # Wind speed reasonable (0-100 kts)
        assert 0 <= metar["wind_speed_kts"] <= 100

        # Gust should be greater than speed if present
        if metar["wind_gust_kts"] is not None:
            assert metar["wind_gust_kts"] > metar["wind_speed_kts"]

    def test_visibility_values(self, client):
        """Test that visibility values are reasonable."""
        response = client.get("/api/weather/current")
        assert response.status_code == 200

        metar = response.json()["metar"]

        # Visibility 0-10+ SM
        assert 0 <= metar["visibility_sm"] <= 15

    def test_temperature_values(self, client):
        """Test that temperature values are reasonable."""
        response = client.get("/api/weather/current")
        assert response.status_code == 200

        metar = response.json()["metar"]

        # Temperature in reasonable range
        assert -50 <= metar["temperature_c"] <= 50
        assert -50 <= metar["dewpoint_c"] <= 50

        # Dewpoint should be <= temperature
        assert metar["dewpoint_c"] <= metar["temperature_c"]

    def test_altimeter_values(self, client):
        """Test that altimeter values are reasonable."""
        response = client.get("/api/weather/current")
        assert response.status_code == 200

        metar = response.json()["metar"]

        # Altimeter range (standard is 29.92)
        assert 28.0 <= metar["altimeter_inhg"] <= 31.0

    def test_cloud_layers(self, client):
        """Test that cloud layers have valid structure."""
        response = client.get("/api/weather/current")
        assert response.status_code == 200

        metar = response.json()["metar"]
        valid_coverage = {"SKC", "FEW", "SCT", "BKN", "OVC"}

        for cloud in metar["clouds"]:
            assert "coverage" in cloud
            assert "altitude_ft" in cloud
            assert cloud["coverage"] in valid_coverage
            assert 0 <= cloud["altitude_ft"] <= 50000

    def test_raw_metar_string(self, client):
        """Test that raw METAR string is present and formatted."""
        response = client.get("/api/weather/current")
        assert response.status_code == 200

        metar = response.json()["metar"]
        assert "raw_metar" in metar
        assert metar["raw_metar"] is not None

        # Raw METAR should start with station identifier
        assert metar["raw_metar"].startswith(metar["station"])

    def test_taf_present(self, client):
        """Test that TAF forecast is included."""
        response = client.get("/api/weather/current")
        assert response.status_code == 200

        data = response.json()
        assert "taf" in data

        if data["taf"]:
            taf = data["taf"]
            assert "station" in taf
            assert "valid_from" in taf
            assert "valid_to" in taf
            assert "forecast_text" in taf


# ==============================================================================
# GSE (Ground Support Equipment) API Tests
# ==============================================================================

class TestGSEEndpoints:
    """Tests for the GSE API endpoints."""

    def test_gse_status_endpoint(self, client):
        """Test that GSE status endpoint returns fleet data."""
        response = client.get("/api/gse/status")

        assert response.status_code == 200
        data = response.json()

        # Verify response structure
        assert "total_units" in data
        assert "available" in data
        assert "in_service" in data
        assert "maintenance" in data
        assert "units" in data
        assert "timestamp" in data

    def test_gse_fleet_counts(self, client):
        """Test that GSE fleet counts are consistent."""
        response = client.get("/api/gse/status")
        assert response.status_code == 200

        data = response.json()

        # Sum of available + in_service + maintenance should equal total
        total_from_sum = data["available"] + data["in_service"] + data["maintenance"]
        assert total_from_sum == data["total_units"]

    def test_gse_unit_fields(self, client):
        """Test that GSE units have required fields."""
        response = client.get("/api/gse/status")
        assert response.status_code == 200

        data = response.json()
        if data["units"]:
            unit = data["units"][0]

            assert "unit_id" in unit
            assert "gse_type" in unit
            assert "status" in unit

    def test_gse_type_values(self, client):
        """Test that GSE types are valid."""
        response = client.get("/api/gse/status")
        assert response.status_code == 200

        valid_types = {
            "pushback_tug", "fuel_truck", "belt_loader", "passenger_stairs",
            "catering_truck", "lavatory_truck", "ground_power", "air_start"
        }

        data = response.json()
        for unit in data["units"]:
            assert unit["gse_type"] in valid_types

    def test_gse_status_values(self, client):
        """Test that GSE status values are valid."""
        response = client.get("/api/gse/status")
        assert response.status_code == 200

        valid_statuses = {"available", "en_route", "servicing", "returning", "maintenance"}

        data = response.json()
        for unit in data["units"]:
            assert unit["status"] in valid_statuses

    def test_turnaround_endpoint(self, client):
        """Test that turnaround endpoint returns status."""
        response = client.get("/api/turnaround/abc123")

        assert response.status_code == 200
        data = response.json()

        # Verify response structure
        assert "turnaround" in data
        assert "timestamp" in data

    def test_turnaround_fields(self, client):
        """Test that turnaround has all required fields."""
        response = client.get("/api/turnaround/test123?gate=A5&aircraft_type=B737")
        assert response.status_code == 200

        turnaround = response.json()["turnaround"]

        assert "icao24" in turnaround
        assert "gate" in turnaround
        assert "current_phase" in turnaround
        assert "phase_progress_pct" in turnaround
        assert "total_progress_pct" in turnaround
        assert "estimated_departure" in turnaround
        assert "assigned_gse" in turnaround

    def test_turnaround_with_params(self, client):
        """Test turnaround with gate and aircraft type parameters."""
        response = client.get("/api/turnaround/xyz789?gate=B12&aircraft_type=A320")
        assert response.status_code == 200

        turnaround = response.json()["turnaround"]
        assert turnaround["icao24"] == "xyz789"
        assert turnaround["gate"] == "B12"
        assert turnaround["aircraft_type"] == "A320"

    def test_turnaround_phase_values(self, client):
        """Test that turnaround phase is valid."""
        response = client.get("/api/turnaround/test456")
        assert response.status_code == 200

        valid_phases = {
            "arrival_taxi", "chocks_on", "deboarding", "unloading",
            "cleaning", "catering", "refueling", "loading",
            "boarding", "chocks_off", "pushback", "departure_taxi", "complete"
        }

        turnaround = response.json()["turnaround"]
        assert turnaround["current_phase"] in valid_phases

    def test_turnaround_progress_values(self, client):
        """Test that progress percentages are valid."""
        response = client.get("/api/turnaround/test789")
        assert response.status_code == 200

        turnaround = response.json()["turnaround"]

        assert 0 <= turnaround["phase_progress_pct"] <= 100
        assert 0 <= turnaround["total_progress_pct"] <= 100

    def test_turnaround_gse_assigned(self, client):
        """Test that turnaround has GSE units assigned."""
        response = client.get("/api/turnaround/testgse")
        assert response.status_code == 200

        turnaround = response.json()["turnaround"]
        assert isinstance(turnaround["assigned_gse"], list)


# ==============================================================================
# Baggage API Tests
# ==============================================================================

class TestBaggageEndpoints:
    """Tests for the baggage API endpoints."""

    def test_baggage_stats_endpoint(self, client):
        """Test that baggage stats endpoint returns data."""
        response = client.get("/api/baggage/stats")

        assert response.status_code == 200
        data = response.json()

        # Verify response structure
        assert "total_bags_today" in data
        assert "bags_in_system" in data
        assert "misconnect_rate_pct" in data
        assert "avg_processing_time_min" in data
        assert "timestamp" in data

    def test_baggage_stats_values(self, client):
        """Test that baggage stats values are reasonable."""
        response = client.get("/api/baggage/stats")
        assert response.status_code == 200

        data = response.json()

        # Positive counts
        assert data["total_bags_today"] >= 0
        assert data["bags_in_system"] >= 0

        # Misconnect rate should be low (typically 1-3%)
        assert 0 <= data["misconnect_rate_pct"] <= 10

        # Processing time reasonable
        assert 10 <= data["avg_processing_time_min"] <= 60

    def test_flight_baggage_endpoint(self, client):
        """Test that flight baggage endpoint returns stats."""
        response = client.get("/api/baggage/flight/UA123")

        assert response.status_code == 200
        data = response.json()

        # Verify response structure
        assert "stats" in data
        assert "bags" in data
        assert "timestamp" in data

    def test_flight_baggage_stats_fields(self, client):
        """Test that flight baggage stats have required fields."""
        response = client.get("/api/baggage/flight/DL456")
        assert response.status_code == 200

        stats = response.json()["stats"]

        assert "flight_number" in stats
        assert "total_bags" in stats
        assert "loaded" in stats
        assert "loading_progress_pct" in stats
        assert "connecting_bags" in stats
        assert "misconnects" in stats

    def test_flight_baggage_with_aircraft_type(self, client):
        """Test flight baggage with aircraft type parameter."""
        response = client.get("/api/baggage/flight/AA789?aircraft_type=B777")
        assert response.status_code == 200

        stats = response.json()["stats"]
        # Wide body should have more bags
        assert stats["total_bags"] > 100

    def test_flight_baggage_include_bags(self, client):
        """Test flight baggage with individual bags included."""
        response = client.get("/api/baggage/flight/SW100?include_bags=true")
        assert response.status_code == 200

        data = response.json()
        assert len(data["bags"]) > 0

        if data["bags"]:
            bag = data["bags"][0]
            assert "bag_id" in bag
            assert "flight_number" in bag
            assert "status" in bag

    def test_flight_baggage_stats_consistency(self, client):
        """Test that baggage stats are consistent."""
        response = client.get("/api/baggage/flight/TEST1")
        assert response.status_code == 200

        stats = response.json()["stats"]

        # Progress should be 0-100
        assert 0 <= stats["loading_progress_pct"] <= 100

        # Connecting bags should be subset of total
        assert stats["connecting_bags"] <= stats["total_bags"]

        # Misconnects should be subset of connecting
        assert stats["misconnects"] <= stats["connecting_bags"]

    def test_baggage_alerts_endpoint(self, client):
        """Test that baggage alerts endpoint returns data."""
        response = client.get("/api/baggage/alerts")

        assert response.status_code == 200
        data = response.json()

        # Verify response structure
        assert "alerts" in data
        assert "count" in data
        assert "timestamp" in data
        assert data["count"] == len(data["alerts"])

    def test_baggage_alert_fields(self, client):
        """Test that baggage alerts have required fields."""
        response = client.get("/api/baggage/alerts")
        assert response.status_code == 200

        data = response.json()
        if data["alerts"]:
            alert = data["alerts"][0]

            assert "alert_id" in alert
            assert "alert_type" in alert
            assert "bag_id" in alert
            assert "flight_number" in alert
            assert "message" in alert
            assert "created_at" in alert

    def test_baggage_bag_status_values(self, client):
        """Test that bag status values are valid."""
        response = client.get("/api/baggage/flight/STATTEST?include_bags=true")
        assert response.status_code == 200

        valid_statuses = {
            "checked_in", "security_screening", "sorted", "loaded",
            "in_transit", "unloaded", "on_carousel", "claimed",
            "misconnect", "lost"
        }

        data = response.json()
        for bag in data["bags"]:
            assert bag["status"] in valid_statuses


# ==============================================================================
# Model Validation Tests
# ==============================================================================

class TestScheduleModels:
    """Tests for schedule data models."""

    def test_scheduled_flight_model(self):
        """Test ScheduledFlight model with valid data."""
        flight = ScheduledFlight(
            flight_number="UA123",
            airline="United Airlines",
            airline_code="UAL",
            origin="LAX",
            destination="SFO",
            scheduled_time=datetime.now(),
            status=FlightStatus.ON_TIME,
            flight_type=FlightType.ARRIVAL,
        )

        assert flight.flight_number == "UA123"
        assert flight.status == FlightStatus.ON_TIME
        assert flight.flight_type == FlightType.ARRIVAL

    def test_flight_status_enum(self):
        """Test FlightStatus enum values."""
        assert FlightStatus.ON_TIME.value == "on_time"
        assert FlightStatus.DELAYED.value == "delayed"
        assert FlightStatus.CANCELLED.value == "cancelled"


class TestWeatherModels:
    """Tests for weather data models."""

    def test_metar_model(self):
        """Test METAR model with valid data."""
        metar = METAR(
            station="KSFO",
            observation_time=datetime.now(),
            wind_direction=280,
            wind_speed_kts=12,
            visibility_sm=10.0,
            temperature_c=15,
            dewpoint_c=8,
            altimeter_inhg=30.05,
            flight_category=FlightCategory.VFR,
        )

        assert metar.station == "KSFO"
        assert metar.flight_category == FlightCategory.VFR

    def test_flight_category_enum(self):
        """Test FlightCategory enum values."""
        assert FlightCategory.VFR.value == "VFR"
        assert FlightCategory.IFR.value == "IFR"
        assert FlightCategory.LIFR.value == "LIFR"

    def test_cloud_layer_model(self):
        """Test CloudLayer model."""
        cloud = CloudLayer(
            coverage=SkyCondition.SCT,
            altitude_ft=4500,
        )

        assert cloud.coverage == SkyCondition.SCT
        assert cloud.altitude_ft == 4500


class TestGSEModels:
    """Tests for GSE data models."""

    def test_gse_unit_model(self):
        """Test GSEUnit model with valid data."""
        unit = GSEUnit(
            unit_id="TUG-001",
            gse_type=GSEType.PUSHBACK_TUG,
            status=GSEStatus.AVAILABLE,
        )

        assert unit.unit_id == "TUG-001"
        assert unit.gse_type == GSEType.PUSHBACK_TUG
        assert unit.status == GSEStatus.AVAILABLE

    def test_gse_type_enum(self):
        """Test GSEType enum values."""
        assert GSEType.FUEL_TRUCK.value == "fuel_truck"
        assert GSEType.BELT_LOADER.value == "belt_loader"

    def test_turnaround_phase_enum(self):
        """Test TurnaroundPhase enum values."""
        assert TurnaroundPhase.REFUELING.value == "refueling"
        assert TurnaroundPhase.BOARDING.value == "boarding"


class TestBaggageModels:
    """Tests for baggage data models."""

    def test_bag_model(self):
        """Test Bag model with valid data."""
        bag = Bag(
            bag_id="UA123-0001",
            flight_number="UA123",
            status=BagStatus.LOADED,
        )

        assert bag.bag_id == "UA123-0001"
        assert bag.status == BagStatus.LOADED

    def test_bag_status_enum(self):
        """Test BagStatus enum values."""
        assert BagStatus.CHECKED_IN.value == "checked_in"
        assert BagStatus.MISCONNECT.value == "misconnect"

    def test_flight_baggage_stats_model(self):
        """Test FlightBaggageStats model."""
        stats = FlightBaggageStats(
            flight_number="DL456",
            total_bags=180,
            loaded=150,
            loading_progress_pct=83,
            connecting_bags=25,
            misconnects=1,
        )

        assert stats.flight_number == "DL456"
        assert stats.loading_progress_pct == 83


# ==============================================================================
# Performance Tests
# ==============================================================================

class TestV2APIPerformance:
    """Tests for V2 API endpoint performance."""

    def test_schedule_performance(self, client):
        """Test that schedule endpoints respond quickly."""
        import time

        endpoints = [
            "/api/schedule/arrivals",
            "/api/schedule/departures",
        ]

        for endpoint in endpoints:
            start = time.time()
            response = client.get(endpoint)
            elapsed = time.time() - start

            assert response.status_code == 200
            assert elapsed < 1.0, f"{endpoint} took {elapsed:.2f}s (> 1s limit)"

    def test_weather_performance(self, client):
        """Test that weather endpoint responds quickly."""
        import time

        start = time.time()
        response = client.get("/api/weather/current")
        elapsed = time.time() - start

        assert response.status_code == 200
        assert elapsed < 0.5, f"Weather took {elapsed:.2f}s (> 0.5s limit)"

    def test_gse_performance(self, client):
        """Test that GSE endpoints respond quickly."""
        import time

        endpoints = [
            "/api/gse/status",
            "/api/turnaround/perftest",
        ]

        for endpoint in endpoints:
            start = time.time()
            response = client.get(endpoint)
            elapsed = time.time() - start

            assert response.status_code == 200
            assert elapsed < 0.5, f"{endpoint} took {elapsed:.2f}s (> 0.5s limit)"

    def test_baggage_performance(self, client):
        """Test that baggage endpoints respond quickly."""
        import time

        endpoints = [
            "/api/baggage/stats",
            "/api/baggage/flight/PERF123",
            "/api/baggage/alerts",
        ]

        for endpoint in endpoints:
            start = time.time()
            response = client.get(endpoint)
            elapsed = time.time() - start

            assert response.status_code == 200
            assert elapsed < 1.0, f"{endpoint} took {elapsed:.2f}s (> 1s limit)"


# ==============================================================================
# Integration Tests
# ==============================================================================

class TestV2Integration:
    """Integration tests across V2 features."""

    def test_all_v2_endpoints_available(self, client):
        """Test that all V2 endpoints return 200."""
        endpoints = [
            "/api/schedule/arrivals",
            "/api/schedule/departures",
            "/api/weather/current",
            "/api/gse/status",
            "/api/turnaround/test",
            "/api/baggage/stats",
            "/api/baggage/flight/TEST",
            "/api/baggage/alerts",
        ]

        for endpoint in endpoints:
            response = client.get(endpoint)
            assert response.status_code == 200, f"{endpoint} returned {response.status_code}"

    def test_v2_endpoints_return_json(self, client):
        """Test that all V2 endpoints return valid JSON."""
        endpoints = [
            "/api/schedule/arrivals",
            "/api/weather/current",
            "/api/gse/status",
            "/api/baggage/stats",
        ]

        for endpoint in endpoints:
            response = client.get(endpoint)
            assert response.status_code == 200

            # Should not raise JSONDecodeError
            data = response.json()
            assert isinstance(data, dict)

    def test_schedule_with_weather_correlation(self, client):
        """Test that schedule and weather can be queried together."""
        arrivals = client.get("/api/schedule/arrivals").json()
        weather = client.get("/api/weather/current").json()

        # Both should have timestamps
        assert "timestamp" in arrivals
        assert "timestamp" in weather

        # Weather affects delays (conceptual - not enforced in synthetic data)
        assert arrivals["count"] >= 0
        assert weather["metar"]["flight_category"] in {"VFR", "MVFR", "IFR", "LIFR"}
