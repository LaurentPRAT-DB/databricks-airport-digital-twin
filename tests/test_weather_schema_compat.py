"""Tests that synthetic and real weather data produce compatible schemas.

weather_generator.generate_metar() produces synthetic METAR data.
metar_history.parse_metar() + _to_weather_snapshot() parses real METAR strings.
Both must produce dicts that validate against WeatherSnapshot.
"""

import pytest

from src.ingestion.weather_generator import generate_metar
from src.ingestion.weather_types import FlightCategory, WeatherSnapshot

# Use a real METAR string for parse_metar testing
_SAMPLE_METAR = "KSFO 091756Z 28012G18KT 10SM SCT035 BKN060 18/10 A3012 RMK AO2"


class TestWeatherGeneratorSchema:
    """Verify generate_metar() output is a superset of WeatherSnapshot fields."""

    def test_output_contains_all_snapshot_fields(self):
        result = generate_metar(station="KSFO")
        snapshot_fields = set(WeatherSnapshot.model_fields.keys())
        missing = snapshot_fields - set(result.keys())
        assert not missing, f"generate_metar() missing WeatherSnapshot fields: {missing}"

    def test_output_validates_as_snapshot(self):
        result = generate_metar(station="KSFO")
        snapshot = WeatherSnapshot(**{k: result[k] for k in WeatherSnapshot.model_fields})
        assert snapshot.flight_category in ("VFR", "MVFR", "IFR", "LIFR")

    def test_flight_category_is_valid_literal(self):
        result = generate_metar(station="KSFO")
        assert result["flight_category"] in ("VFR", "MVFR", "IFR", "LIFR")

    def test_wind_speed_is_int(self):
        result = generate_metar(station="KSFO")
        assert isinstance(result["wind_speed_kts"], int)

    def test_visibility_is_numeric(self):
        result = generate_metar(station="KSFO")
        assert isinstance(result["visibility_sm"], (int, float))


class TestMetarHistorySchema:
    """Verify parse_metar() + _to_weather_snapshot() output matches WeatherSnapshot."""

    def test_parse_metar_contains_snapshot_fields(self):
        from app.backend.services.metar_history import parse_metar

        result = parse_metar(_SAMPLE_METAR)
        snapshot_fields = set(WeatherSnapshot.model_fields.keys()) - {"raw_metar"}
        missing = snapshot_fields - set(result.keys())
        assert not missing, f"parse_metar() missing WeatherSnapshot fields: {missing}"

    def test_to_weather_snapshot_validates(self):
        from app.backend.services.metar_history import _to_weather_snapshot

        result = _to_weather_snapshot("2026-04-09T17:56:00+00:00", _SAMPLE_METAR)
        snapshot = WeatherSnapshot(**{k: result[k] for k in WeatherSnapshot.model_fields if k in result})
        assert snapshot.flight_category in ("VFR", "MVFR", "IFR", "LIFR")
        assert snapshot.raw_metar == _SAMPLE_METAR.strip()

    def test_parse_metar_flight_category_valid(self):
        from app.backend.services.metar_history import parse_metar

        result = parse_metar(_SAMPLE_METAR)
        assert result["flight_category"] in ("VFR", "MVFR", "IFR", "LIFR")

    def test_parse_metar_wind_values(self):
        from app.backend.services.metar_history import parse_metar

        result = parse_metar(_SAMPLE_METAR)
        assert result["wind_speed_kts"] == 12
        assert result["wind_gust_kts"] == 18
        assert result["wind_direction"] == 280


class TestCrossCompatibility:
    """Verify both paths produce dicts with the same key types."""

    def test_shared_field_types_match(self):
        """Both sources must produce the same Python types for shared fields.

        int and float are treated as compatible for numeric weather values
        (temperature_c, dewpoint_c, visibility_sm) since Pydantic coerces both.
        """
        gen = generate_metar(station="KSFO")

        from app.backend.services.metar_history import parse_metar

        parsed = parse_metar(_SAMPLE_METAR)

        numeric_fields = {"temperature_c", "dewpoint_c", "visibility_sm", "wind_speed_kts", "wind_gust_kts"}
        shared_keys = set(WeatherSnapshot.model_fields.keys()) - {"raw_metar"}
        for key in shared_keys:
            gen_val = gen.get(key)
            parsed_val = parsed.get(key)
            if gen_val is not None and parsed_val is not None:
                if key in numeric_fields:
                    assert isinstance(gen_val, (int, float)), (
                        f"generator '{key}' should be numeric, got {type(gen_val).__name__}"
                    )
                    assert isinstance(parsed_val, (int, float)), (
                        f"parser '{key}' should be numeric, got {type(parsed_val).__name__}"
                    )
                else:
                    assert type(gen_val) == type(parsed_val), (
                        f"Type mismatch for '{key}': generator={type(gen_val).__name__}, "
                        f"parser={type(parsed_val).__name__}"
                    )
