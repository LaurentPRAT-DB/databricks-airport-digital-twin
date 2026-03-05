"""OpenSky Network API client with OAuth2 authentication and retry logic."""

import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from typing import Optional, List

from src.schemas.opensky import OpenSkyResponse
from src.config.settings import settings


class RateLimitError(Exception):
    """Raised when API rate limit is exceeded (HTTP 429)."""
    pass


class OpenSkyClient:
    """
    Client for OpenSky Network API with authentication and retry support.

    Supports both anonymous and authenticated access. Authenticated users
    get higher rate limits (4000-8000 credits/day vs 400 anonymous).

    Usage:
        client = OpenSkyClient()
        response = client.get_states(bbox={"lamin": 36, "lamax": 39, "lomin": -124, "lomax": -121})
    """

    BASE_URL = "https://opensky-network.org/api"
    AUTH_URL = "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"

    def __init__(self):
        """Initialize client with optional credentials from settings."""
        self.client_id = settings.OPENSKY_CLIENT_ID
        self.client_secret = settings.OPENSKY_CLIENT_SECRET
        self._token: Optional[str] = None

    def _get_token(self) -> Optional[str]:
        """
        Get OAuth2 access token using client credentials flow.

        Returns None if credentials are not configured (anonymous access).
        Token is cached for subsequent requests within the same client instance.
        """
        if not self.client_id or not self.client_secret:
            return None

        if self._token:
            return self._token

        try:
            response = requests.post(
                self.AUTH_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
                timeout=30,
            )
            if response.ok:
                self._token = response.json().get("access_token")
            return self._token
        except requests.RequestException:
            return None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((requests.exceptions.ConnectionError,
                                       requests.exceptions.Timeout,
                                       requests.exceptions.HTTPError)),
        reraise=True,
    )
    def get_states(
        self,
        bbox: Optional[dict] = None,
        icao24: Optional[List[str]] = None,
    ) -> OpenSkyResponse:
        """
        Fetch current aircraft state vectors from OpenSky API.

        Args:
            bbox: Bounding box dict with keys: lamin, lamax, lomin, lomax
                  Using a small bbox (<25 sq deg) reduces API credit usage.
            icao24: Optional list of ICAO24 addresses to filter results.

        Returns:
            OpenSkyResponse containing timestamp and list of state vectors.

        Raises:
            RateLimitError: If API returns 429 (rate limit exceeded).
            requests.HTTPError: For other HTTP errors after retries exhausted.
        """
        params = {}

        if bbox:
            params.update(bbox)

        if icao24:
            # OpenSky API accepts multiple icao24 parameters
            params["icao24"] = icao24

        headers = {}
        token = self._get_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"

        response = requests.get(
            f"{self.BASE_URL}/states/all",
            params=params,
            headers=headers,
            timeout=30,
        )

        # Handle rate limiting specifically
        if response.status_code == 429:
            raise RateLimitError(
                f"OpenSky API rate limit exceeded. "
                f"Remaining credits: {response.headers.get('x-rate-limit-remaining', 'unknown')}"
            )

        response.raise_for_status()

        return OpenSkyResponse(**response.json())
