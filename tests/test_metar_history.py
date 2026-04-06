"""Tests for historical METAR weather data fetcher."""

import pytest
from datetime import date
from unittest.mock import AsyncMock, patch

from app.backend.services.metar_history import (
    parse_metar,
    fetch_historical_metar,
    _to_weather_snapshot,
)


# ── METAR parser tests ───────────────────────────────────────────────────


class TestParseMetar:
    def test_standard_metar(self):
        raw = "KSFO 060856Z 28012KT 10SM FEW020 SCT250 14/08 A3012"
        r = parse_metar(raw)
        assert r["wind_direction"] == 280
        assert r["wind_speed_kts"] == 12
        assert r["wind_gust_kts"] is None
        assert r["visibility_sm"] == 10.0
        assert r["temperature_c"] == 14.0
        assert r["dewpoint_c"] == 8.0
        assert r["flight_category"] == "VFR"

    def test_wind_with_gusts(self):
        raw = "KJFK 061553Z 32018G28KT 10SM SCT040 BKN250 08/M02 A2998"
        r = parse_metar(raw)
        assert r["wind_direction"] == 320
        assert r["wind_speed_kts"] == 18
        assert r["wind_gust_kts"] == 28

    def test_variable_wind(self):
        raw = "KLAX 060453Z VRB03KT 10SM CLR 16/10 A3010"
        r = parse_metar(raw)
        assert r["wind_direction"] == 0  # VRB -> 0
        assert r["wind_speed_kts"] == 3

    def test_low_visibility_ifr(self):
        raw = "KSFO 061200Z 18006KT 2SM BR OVC005 12/11 A3010"
        r = parse_metar(raw)
        assert r["visibility_sm"] == 2.0
        assert r["ceiling_ft"] == 500
        assert r["flight_category"] == "IFR"

    def test_very_low_visibility_lifr(self):
        raw = "KSFO 060700Z 00000KT 1/4SM FG VV002 10/10 A3008"
        r = parse_metar(raw)
        assert r["visibility_sm"] == 0.25
        assert r["ceiling_ft"] == 200
        assert r["flight_category"] == "LIFR"

    def test_fractional_visibility(self):
        raw = "KORD 061800Z 27015KT 1 1/2SM -SN BKN010 OVC020 M02/M06 A2980"
        r = parse_metar(raw)
        assert r["visibility_sm"] == 1.5

    def test_mvfr_ceiling(self):
        raw = "KDEN 061400Z 16010KT 5SM HZ BKN025 18/04 A3020"
        r = parse_metar(raw)
        assert r["ceiling_ft"] == 2500
        assert r["flight_category"] == "MVFR"

    def test_negative_temperature(self):
        raw = "KORD 061200Z 36008KT 10SM SCT250 M05/M12 A3015"
        r = parse_metar(raw)
        assert r["temperature_c"] == -5.0
        assert r["dewpoint_c"] == -12.0

    def test_no_ceiling_clear_sky(self):
        raw = "KLAX 061800Z 25008KT 10SM CLR 22/08 A3012"
        r = parse_metar(raw)
        assert r["ceiling_ft"] is None
        assert r["flight_category"] == "VFR"

    def test_empty_metar(self):
        r = parse_metar("")
        assert r["wind_speed_kts"] == 0
        assert r["visibility_sm"] == 10.0
        assert r["flight_category"] == "VFR"


class TestToWeatherSnapshot:
    def test_snapshot_format(self):
        snap = _to_weather_snapshot(
            "2026-04-06T08:56:00+00:00",
            "KSFO 060856Z 28012KT 10SM FEW020 14/08 A3012",
        )
        assert snap["time"] == "2026-04-06T08:56:00+00:00"
        assert snap["wind_speed_kts"] == 12
        assert snap["visibility_sm"] == 10.0
        assert snap["flight_category"] == "VFR"
        assert "raw_metar" in snap
        assert "KSFO" in snap["raw_metar"]


# ── Fetch tests (mocked HTTP) ────────────────────────────────────────────


class TestFetchHistoricalMetar:
    async def test_successful_fetch(self):
        csv_response = (
            "station,valid,metar\n"
            "SFO,2026-04-06 08:56,KSFO 060856Z 28012KT 10SM FEW020 14/08 A3012\n"
            "SFO,2026-04-06 09:56,KSFO 060956Z 27010KT 10SM SCT025 15/09 A3014\n"
        )

        mock_resp = AsyncMock()
        mock_resp.text = csv_response
        mock_resp.raise_for_status = lambda: None

        with patch("app.backend.services.metar_history.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_resp
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value = mock_instance

            result = await fetch_historical_metar("KSFO", date(2026, 4, 6))

        assert len(result) == 2
        assert result[0]["wind_speed_kts"] == 12
        assert result[1]["wind_speed_kts"] == 10

    async def test_strips_k_prefix_for_us_airports(self):
        mock_resp = AsyncMock()
        mock_resp.text = "station,valid,metar\n"
        mock_resp.raise_for_status = lambda: None

        with patch("app.backend.services.metar_history.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_resp
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value = mock_instance

            await fetch_historical_metar("KSFO", date(2026, 4, 6))

            call_kwargs = mock_instance.get.call_args
            assert call_kwargs[1]["params"]["station"] == "SFO"

    async def test_keeps_non_us_station_code(self):
        mock_resp = AsyncMock()
        mock_resp.text = "station,valid,metar\n"
        mock_resp.raise_for_status = lambda: None

        with patch("app.backend.services.metar_history.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_resp
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value = mock_instance

            await fetch_historical_metar("EGLL", date(2026, 4, 6))

            call_kwargs = mock_instance.get.call_args
            assert call_kwargs[1]["params"]["station"] == "EGLL"

    async def test_http_error_returns_empty(self):
        import httpx

        with patch("app.backend.services.metar_history.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.side_effect = httpx.HTTPError("Connection failed")
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value = mock_instance

            result = await fetch_historical_metar("KSFO", date(2026, 4, 6))

        assert result == []

    async def test_skips_missing_metar_lines(self):
        csv_response = (
            "station,valid,metar\n"
            "SFO,2026-04-06 08:56,M\n"
            "SFO,2026-04-06 09:56,KSFO 060956Z 27010KT 10SM SCT025 15/09 A3014\n"
        )

        mock_resp = AsyncMock()
        mock_resp.text = csv_response
        mock_resp.raise_for_status = lambda: None

        with patch("app.backend.services.metar_history.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_resp
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value = mock_instance

            result = await fetch_historical_metar("KSFO", date(2026, 4, 6))

        assert len(result) == 1
