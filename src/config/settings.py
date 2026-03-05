"""Configuration settings for the Airport Digital Twin."""

import os
from typing import Optional


class Settings:
    """Application settings loaded from environment variables."""

    def __init__(self):
        # OpenSky API credentials (optional - for authenticated access)
        self.OPENSKY_CLIENT_ID: Optional[str] = os.getenv("OPENSKY_CLIENT_ID")
        self.OPENSKY_CLIENT_SECRET: Optional[str] = os.getenv("OPENSKY_CLIENT_SECRET")

        # Landing zone path for raw data
        self.LANDING_PATH: str = os.getenv("LANDING_PATH", "/mnt/data/landing")

        # Polling interval in seconds
        self.POLL_INTERVAL_SECONDS: int = int(os.getenv("POLL_INTERVAL_SECONDS", "30"))

        # SFO area bounding box (approx 500km x 500km = 1 API credit per query)
        self.SFO_BBOX: dict = {
            "lamin": 36.0,   # South latitude
            "lamax": 39.0,   # North latitude
            "lomin": -124.0, # West longitude
            "lomax": -121.0  # East longitude
        }


# Module-level singleton for easy imports
settings = Settings()
