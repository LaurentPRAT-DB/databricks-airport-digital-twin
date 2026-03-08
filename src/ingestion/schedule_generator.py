"""Synthetic flight schedule generator for FIDS display.

Generates realistic daily flight schedules with:
- Peak hour distribution (6-9am, 4-7pm = 60%)
- Airline mix based on hub status
- Realistic delay patterns (15% delayed)
"""

import random
from datetime import datetime, timedelta, timezone
from typing import Optional

# Airline data with ICAO codes, names, and hub weighting
AIRLINES = {
    "UAL": {"name": "United Airlines", "weight": 0.35, "hubs": ["SFO", "ORD", "IAH", "EWR"]},
    "DAL": {"name": "Delta Air Lines", "weight": 0.15, "hubs": ["ATL", "DTW", "MSP", "SLC"]},
    "AAL": {"name": "American Airlines", "weight": 0.15, "hubs": ["DFW", "CLT", "MIA", "PHX"]},
    "SWA": {"name": "Southwest Airlines", "weight": 0.10, "hubs": ["DAL", "HOU", "BWI", "MDW"]},
    "ASA": {"name": "Alaska Airlines", "weight": 0.08, "hubs": ["SEA", "SFO", "LAX", "PDX"]},
    "JBU": {"name": "JetBlue Airways", "weight": 0.05, "hubs": ["JFK", "BOS", "FLL"]},
    "UAE": {"name": "Emirates", "weight": 0.04, "hubs": ["DXB"]},
    "BAW": {"name": "British Airways", "weight": 0.03, "hubs": ["LHR"]},
    "ANA": {"name": "All Nippon Airways", "weight": 0.03, "hubs": ["HND", "NRT"]},
    "CPA": {"name": "Cathay Pacific", "weight": 0.02, "hubs": ["HKG"]},
}

# Destination airports with distance category
DOMESTIC_AIRPORTS = [
    "LAX", "ORD", "DFW", "JFK", "ATL", "DEN", "SEA", "BOS", "PHX", "LAS",
    "MCO", "MIA", "CLT", "MSP", "DTW", "EWR", "PHL", "IAH", "SAN", "PDX",
]

INTERNATIONAL_AIRPORTS = [
    "LHR", "CDG", "FRA", "AMS", "HKG", "NRT", "SIN", "SYD", "DXB", "ICN",
]

# Aircraft types by category
NARROW_BODY = ["A320", "A321", "B737", "B738", "A319", "E175"]
WIDE_BODY = ["B777", "B787", "A330", "A350", "A380"]

# IATA delay codes with descriptions and weights
DELAY_CODES = {
    "61": ("Cargo/Mail", 0.05),
    "62": ("Cleaning/Catering", 0.12),
    "63": ("Baggage handling", 0.10),
    "67": ("Late crew", 0.08),
    "68": ("Late inbound aircraft", 0.15),
    "71": ("Weather at departure", 0.18),
    "72": ("Weather at destination", 0.12),
    "81": ("ATC restriction", 0.15),
    "41": ("Aircraft defect", 0.05),
}


def _select_airline() -> tuple[str, str]:
    """Select an airline based on weighted distribution."""
    codes = list(AIRLINES.keys())
    weights = [AIRLINES[code]["weight"] for code in codes]
    code = random.choices(codes, weights=weights, k=1)[0]
    return code, AIRLINES[code]["name"]


def _generate_flight_number(airline_code: str) -> str:
    """Generate a realistic flight number."""
    # Domestic flights typically 1-999, international 1-9999
    num = random.randint(1, 2999)
    return f"{airline_code}{num}"


def _select_destination(flight_type: str, airline_code: str) -> str:
    """Select destination based on airline and flight type."""
    # 70% domestic, 30% international
    if random.random() < 0.7:
        return random.choice(DOMESTIC_AIRPORTS)
    return random.choice(INTERNATIONAL_AIRPORTS)


def _select_aircraft(destination: str) -> str:
    """Select aircraft type based on route."""
    if destination in INTERNATIONAL_AIRPORTS:
        return random.choice(WIDE_BODY)
    return random.choice(NARROW_BODY)


def _generate_delay() -> tuple[int, Optional[str], Optional[str]]:
    """Generate realistic delay if applicable."""
    # 15% of flights delayed
    if random.random() > 0.15:
        return 0, None, None

    # Select delay code based on weights
    codes = list(DELAY_CODES.keys())
    weights = [DELAY_CODES[code][1] for code in codes]
    code = random.choices(codes, weights=weights, k=1)[0]
    reason = DELAY_CODES[code][0]

    # Delay duration: most 5-30 min, some longer
    if random.random() < 0.8:
        delay_minutes = random.randint(5, 30)
    else:
        delay_minutes = random.randint(30, 120)

    return delay_minutes, code, reason


def _get_flights_per_hour(hour: int) -> int:
    """Get number of flights for a given hour based on peak patterns."""
    # Morning peak: 6-10am (higher volume)
    if 6 <= hour < 10:
        return random.randint(18, 25)
    # Evening peak: 4-8pm (higher volume)
    if 16 <= hour < 20:
        return random.randint(18, 25)
    # Midday moderate
    if 10 <= hour < 16:
        return random.randint(10, 15)
    # Early morning
    if 5 <= hour < 6:
        return random.randint(5, 10)
    # Late evening
    if 20 <= hour < 23:
        return random.randint(8, 12)
    # Night (minimal)
    return random.randint(0, 3)


def generate_daily_schedule(
    airport: str = "SFO",
    date: Optional[datetime] = None,
    include_past_hours: int = 2,
) -> list[dict]:
    """
    Generate a synthetic daily flight schedule.

    Args:
        airport: Airport IATA code (used as origin for departures, destination for arrivals)
        date: Date for schedule (defaults to today)
        include_past_hours: Include flights from past N hours (for realistic display)

    Returns:
        List of scheduled flight dictionaries
    """
    if date is None:
        date = datetime.now(timezone.utc)

    # Start from past hours for arrivals/departures that already happened
    start_hour = max(0, date.hour - include_past_hours)
    schedule = []

    # Generate flights for each hour
    for hour in range(start_hour, 24):
        flights_this_hour = _get_flights_per_hour(hour)

        for _ in range(flights_this_hour):
            # 50% arrivals, 50% departures
            is_arrival = random.random() < 0.5

            airline_code, airline_name = _select_airline()
            flight_number = _generate_flight_number(airline_code)

            if is_arrival:
                origin = _select_destination("arrival", airline_code)
                destination = airport
            else:
                origin = airport
                destination = _select_destination("departure", airline_code)

            aircraft = _select_aircraft(destination if is_arrival else origin)

            # Generate scheduled time within the hour
            minute = random.randint(0, 59)
            scheduled_time = date.replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )

            # Generate delay
            delay_minutes, delay_code, delay_reason = _generate_delay()
            estimated_time = None
            if delay_minutes > 0:
                estimated_time = scheduled_time + timedelta(minutes=delay_minutes)

            # Determine status based on time
            now = datetime.now(timezone.utc)
            effective_time = estimated_time or scheduled_time

            if effective_time < now - timedelta(minutes=15):
                status = "arrived" if is_arrival else "departed"
                actual_time = effective_time
            elif effective_time < now:
                status = "boarding" if not is_arrival else "arrived"
                actual_time = effective_time if status == "arrived" else None
            elif delay_minutes > 0:
                status = "delayed"
                actual_time = None
            else:
                status = "on_time"
                actual_time = None

            # Assign gate
            gate = f"{random.choice(['A', 'B', 'C', 'D', 'G'])}{random.randint(1, 30)}"

            flight = {
                "flight_number": flight_number,
                "airline": airline_name,
                "airline_code": airline_code,
                "origin": origin,
                "destination": destination,
                "scheduled_time": scheduled_time.isoformat(),
                "estimated_time": estimated_time.isoformat() if estimated_time else None,
                "actual_time": actual_time.isoformat() if actual_time else None,
                "gate": gate,
                "status": status,
                "delay_minutes": delay_minutes,
                "delay_reason": delay_reason,
                "aircraft_type": aircraft,
                "flight_type": "arrival" if is_arrival else "departure",
            }
            schedule.append(flight)

    # Sort by scheduled time
    schedule.sort(key=lambda x: x["scheduled_time"])
    return schedule


def get_arrivals(
    airport: str = "SFO",
    hours_ahead: int = 2,
    hours_behind: int = 1,
) -> list[dict]:
    """Get arrivals for the specified time window."""
    schedule = generate_daily_schedule(airport=airport, include_past_hours=hours_behind)
    now = datetime.now(timezone.utc)
    cutoff_future = now + timedelta(hours=hours_ahead)
    cutoff_past = now - timedelta(hours=hours_behind)

    arrivals = [
        f for f in schedule
        if f["flight_type"] == "arrival"
        and cutoff_past <= datetime.fromisoformat(f["scheduled_time"]) <= cutoff_future
    ]
    return arrivals


def get_departures(
    airport: str = "SFO",
    hours_ahead: int = 2,
    hours_behind: int = 1,
) -> list[dict]:
    """Get departures for the specified time window."""
    schedule = generate_daily_schedule(airport=airport, include_past_hours=hours_behind)
    now = datetime.now(timezone.utc)
    cutoff_future = now + timedelta(hours=hours_ahead)
    cutoff_past = now - timedelta(hours=hours_behind)

    departures = [
        f for f in schedule
        if f["flight_type"] == "departure"
        and cutoff_past <= datetime.fromisoformat(f["scheduled_time"]) <= cutoff_future
    ]
    return departures


# Cache for consistent schedule within same minute
_schedule_cache: dict = {}
_cache_minute: Optional[int] = None


def get_cached_schedule(airport: str = "SFO") -> list[dict]:
    """Get cached schedule (regenerates every minute for freshness)."""
    global _schedule_cache, _cache_minute
    current_minute = datetime.now(timezone.utc).minute

    if _cache_minute != current_minute or airport not in _schedule_cache:
        _schedule_cache[airport] = generate_daily_schedule(airport=airport)
        _cache_minute = current_minute

    return _schedule_cache[airport]
