"""Synthetic flight data generator for fallback when API is unavailable."""

import random
from datetime import datetime
from typing import Dict, List, Any

from faker import Faker


fake = Faker()

# Common US airline callsign prefixes
CALLSIGN_PREFIXES = [
    "UAL",  # United Airlines
    "DAL",  # Delta Air Lines
    "AAL",  # American Airlines
    "SWA",  # Southwest Airlines
    "JBU",  # JetBlue Airways
    "ASA",  # Alaska Airlines
    "FFT",  # Frontier Airlines
    "SKW",  # SkyWest Airlines
]

# Test flights with trajectory history in Unity Catalog
# These flights have historical data for trajectory visualization
TEST_FLIGHTS_WITH_TRAJECTORY = [
    {"icao24": "a12345", "callsign": "UAL123"},
    {"icao24": "b67890", "callsign": "DAL456"},
    {"icao24": "c11111", "callsign": "SWA789"},
    {"icao24": "d22222", "callsign": "AAL100"},
    {"icao24": "e33333", "callsign": "JBU555"},
]


def generate_synthetic_flights(
    count: int = 50,
    bbox: Dict[str, float] | None = None,
) -> Dict[str, Any]:
    """
    Generate synthetic flight data matching OpenSky API response format.

    Creates realistic-looking flight positions within the specified bounding box.
    Used as fallback when the real API is unavailable.

    Args:
        count: Number of flights to generate (default 50).
        bbox: Bounding box dict with keys: lamin, lamax, lomin, lomax.
              Defaults to SFO area if not provided.

    Returns:
        Dict with 'time' (int) and 'states' (list of lists) matching
        the OpenSky /states/all response format.
    """
    if bbox is None:
        bbox = {
            "lamin": 36.0,
            "lamax": 39.0,
            "lomin": -124.0,
            "lomax": -121.0,
        }

    current_time = int(datetime.utcnow().timestamp())
    states: List[List[Any]] = []

    for i in range(count):
        # First 5 flights use test data with trajectory history
        if i < len(TEST_FLIGHTS_WITH_TRAJECTORY):
            test_flight = TEST_FLIGHTS_WITH_TRAJECTORY[i]
            icao24 = test_flight["icao24"]
            callsign = test_flight["callsign"].ljust(8)
        else:
            # Generate realistic ICAO24 (6 hex characters)
            icao24 = fake.hexify(text="^^^^^^", upper=False)

            # Generate callsign (airline prefix + flight number)
            prefix = random.choice(CALLSIGN_PREFIXES)
            flight_num = random.randint(100, 9999)
            callsign = f"{prefix}{flight_num}".ljust(8)  # Pad to 8 chars

        # Generate position within bounding box
        latitude = random.uniform(bbox["lamin"], bbox["lamax"])
        longitude = random.uniform(bbox["lomin"], bbox["lomax"])

        # Generate realistic flight parameters
        on_ground = random.random() < 0.1  # 10% on ground

        if on_ground:
            altitude = 0.0
            velocity = random.uniform(0, 50)  # Taxiing speed
            vertical_rate = 0.0
        else:
            altitude = random.uniform(1000, 12000)  # meters
            velocity = random.uniform(150, 280)  # m/s (cruising speed)
            vertical_rate = random.uniform(-10, 10)  # m/s

        heading = random.uniform(0, 360)

        # Build state vector in OpenSky API format (18 fields)
        state = [
            icao24,                                    # 0: icao24
            callsign,                                  # 1: callsign
            "United States",                           # 2: origin_country
            current_time - random.randint(0, 10),      # 3: time_position
            current_time - random.randint(0, 5),       # 4: last_contact
            longitude,                                 # 5: longitude
            latitude,                                  # 6: latitude
            altitude,                                  # 7: baro_altitude
            on_ground,                                 # 8: on_ground
            velocity,                                  # 9: velocity
            heading,                                   # 10: true_track
            vertical_rate,                             # 11: vertical_rate
            None,                                      # 12: sensors
            altitude + random.uniform(-50, 50),        # 13: geo_altitude
            f"{random.randint(1000, 7777):04d}",       # 14: squawk
            False,                                     # 15: spi
            0,                                         # 16: position_source (ADS-B)
            random.randint(2, 6),                      # 17: category
        ]
        states.append(state)

    return {
        "time": current_time,
        "states": states,
    }
