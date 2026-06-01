"""SITA FLIFO API client with OAuth2 and retry logic."""

import logging
import os
import time
from typing import Optional

import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = logging.getLogger(__name__)


class RateLimitError(Exception):
    pass


class FlifoClient:
    """Client for SITA FLIFO FlightInfo API v2.

    Handles OAuth2 client credentials auth, token caching, retry, and rate limiting.
    Active only when FLIFO_BASE_URL and FLIFO_CLIENT_ID are configured.
    """

    def __init__(self, base_url: str, client_id: str, client_secret: str):
        self._base_url = base_url.rstrip("/")
        self._client_id = client_id
        self._client_secret = client_secret
        self._token: Optional[str] = None
        self._token_expiry: float = 0
        # Skip OAuth when using embedded mock (no token endpoint needed)
        self._skip_auth = os.getenv("FLIFO_MOCK_MODE", "").lower() in ("true", "1", "yes")

    @property
    def is_configured(self) -> bool:
        return bool(self._base_url and self._client_id and self._client_secret)

    def _get_token(self) -> str:
        if self._skip_auth:
            return "embedded-mock-no-auth"
        if self._token and time.time() < self._token_expiry - 60:
            return self._token

        resp = requests.post(
            f"{self._base_url}/oauth/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            },
            timeout=30,
        )
        if resp.status_code == 401:
            raise PermissionError("FLIFO: invalid client credentials")
        resp.raise_for_status()

        data = resp.json()
        self._token = data["access_token"]
        self._token_expiry = time.time() + data.get("expires_in", 3600)
        logger.info("FLIFO: obtained access token")
        return self._token

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((requests.exceptions.ConnectionError,
                                       requests.exceptions.Timeout)),
        reraise=True,
    )
    def get_flights_by_airport(
        self,
        airport_iata: str,
        direction: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        limit: int = 50,
    ) -> dict:
        """Fetch flights for an airport from FLIFO API.

        Returns raw JSON response dict with 'flightRecords' key.
        """
        token = self._get_token()
        params = {"limit": limit}
        if direction:
            params["direction"] = direction
        if from_date:
            params["fromDate"] = from_date
        if to_date:
            params["toDate"] = to_date

        resp = requests.get(
            f"{self._base_url}/flightinfo/v2/flights/airport/{airport_iata}",
            headers={"Authorization": f"Bearer {token}"},
            params=params,
            timeout=30,
        )

        if resp.status_code == 429:
            raise RateLimitError("FLIFO API rate limit exceeded")
        if resp.status_code == 401:
            self._token = None
            raise PermissionError("FLIFO: token rejected, will retry")
        resp.raise_for_status()

        return resp.json()

    def get_flight_by_number(self, flight_number: str) -> dict:
        """Fetch a single flight by number."""
        token = self._get_token()
        resp = requests.get(
            f"{self._base_url}/flightinfo/v2/flights/{flight_number}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        if resp.status_code == 429:
            raise RateLimitError("FLIFO API rate limit exceeded")
        resp.raise_for_status()
        return resp.json()
