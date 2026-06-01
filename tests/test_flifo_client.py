"""Tests for FLIFO client."""

import pytest
from unittest.mock import patch, MagicMock

from src.ingestion.flifo_client import FlifoClient, RateLimitError


class TestFlifoClient:
    def setup_method(self):
        self.client = FlifoClient(
            base_url="http://localhost:8089",
            client_id="test",
            client_secret="test",
        )

    def test_is_configured(self):
        assert self.client.is_configured is True

    def test_not_configured_when_empty(self):
        client = FlifoClient("", "", "")
        assert client.is_configured is False

    @patch("src.ingestion.flifo_client.requests.post")
    def test_get_token(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.ok = True
        mock_resp.json.return_value = {"access_token": "abc123", "expires_in": 3600}
        mock_post.return_value = mock_resp

        token = self.client._get_token()
        assert token == "abc123"
        mock_post.assert_called_once()

    @patch("src.ingestion.flifo_client.requests.post")
    def test_get_token_invalid_creds(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_post.return_value = mock_resp

        with pytest.raises(PermissionError):
            self.client._get_token()

    @patch("src.ingestion.flifo_client.requests.get")
    @patch("src.ingestion.flifo_client.requests.post")
    def test_get_flights_by_airport(self, mock_post, mock_get):
        mock_token_resp = MagicMock()
        mock_token_resp.status_code = 200
        mock_token_resp.json.return_value = {"access_token": "tok", "expires_in": 3600}
        mock_post.return_value = mock_token_resp

        mock_flight_resp = MagicMock()
        mock_flight_resp.status_code = 200
        mock_flight_resp.json.return_value = {
            "flightRecords": [{"flightNumber": "UA123"}],
            "totalRecords": 1,
        }
        mock_get.return_value = mock_flight_resp

        result = self.client.get_flights_by_airport("SFO", direction="arrival")
        assert result["flightRecords"][0]["flightNumber"] == "UA123"

    @patch("src.ingestion.flifo_client.requests.get")
    @patch("src.ingestion.flifo_client.requests.post")
    def test_rate_limit_raises(self, mock_post, mock_get):
        mock_token_resp = MagicMock()
        mock_token_resp.status_code = 200
        mock_token_resp.json.return_value = {"access_token": "tok", "expires_in": 3600}
        mock_post.return_value = mock_token_resp

        mock_flight_resp = MagicMock()
        mock_flight_resp.status_code = 429
        mock_get.return_value = mock_flight_resp

        with pytest.raises(RateLimitError):
            self.client.get_flights_by_airport("SFO")
