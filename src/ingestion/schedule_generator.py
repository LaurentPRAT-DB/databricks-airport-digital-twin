"""Synthetic flight schedule generator for FIDS display.

Generates realistic daily flight schedules with:
- Peak hour distribution (6-9am, 4-7pm = 60%)
- Airline mix based on hub status
- Realistic delay patterns (15% delayed)

When an AirportProfile is provided, distributions are sampled from
real-data-calibrated profiles instead of hardcoded constants.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Optional, TYPE_CHECKING

from src.ingestion.fallback import get_gates

if TYPE_CHECKING:
    from src.calibration.profile import AirportProfile, AirportProfileLoader

# Airline data with ICAO codes, names, and hub weighting
AIRLINES = {
    # US carriers (~75% of SFO traffic)
    "UAL": {"name": "United Airlines", "weight": 0.31, "hubs": ["SFO", "ORD", "IAH", "EWR"]},
    "DAL": {"name": "Delta Air Lines", "weight": 0.10, "hubs": ["ATL", "DTW", "MSP", "SLC"]},
    "AAL": {"name": "American Airlines", "weight": 0.10, "hubs": ["DFW", "CLT", "MIA", "PHX"]},
    "SWA": {"name": "Southwest Airlines", "weight": 0.08, "hubs": ["DAL", "HOU", "BWI", "MDW"]},
    "ASA": {"name": "Alaska Airlines", "weight": 0.06, "hubs": ["SEA", "SFO", "LAX", "PDX"]},
    "JBU": {"name": "JetBlue Airways", "weight": 0.03, "hubs": ["JFK", "BOS", "FLL"]},
    "NKS": {"name": "Spirit Airlines", "weight": 0.02, "hubs": ["FLL", "LAS", "MCO"]},
    "FFT": {"name": "Frontier Airlines", "weight": 0.02, "hubs": ["DEN", "LAS", "MCO"]},
    "HAL": {"name": "Hawaiian Airlines", "weight": 0.01, "hubs": ["HNL"]},
    "AAY": {"name": "Allegiant Air", "weight": 0.01, "hubs": ["LAS"]},
    "SCX": {"name": "Sun Country Airlines", "weight": 0.01, "hubs": ["MSP"]},
    # International carriers (~25% of SFO traffic)
    "UAE": {"name": "Emirates", "weight": 0.03, "hubs": ["DXB"]},
    "BAW": {"name": "British Airways", "weight": 0.02, "hubs": ["LHR"]},
    "ANA": {"name": "All Nippon Airways", "weight": 0.02, "hubs": ["HND", "NRT"]},
    "CPA": {"name": "Cathay Pacific", "weight": 0.02, "hubs": ["HKG"]},
    "DLH": {"name": "Lufthansa", "weight": 0.02, "hubs": ["FRA", "MUC"]},
    "AFR": {"name": "Air France", "weight": 0.01, "hubs": ["CDG"]},
    "KLM": {"name": "KLM Royal Dutch", "weight": 0.01, "hubs": ["AMS"]},
    "JAL": {"name": "Japan Airlines", "weight": 0.01, "hubs": ["NRT", "HND"]},
    "SIA": {"name": "Singapore Airlines", "weight": 0.01, "hubs": ["SIN"]},
    "QFA": {"name": "Qantas", "weight": 0.01, "hubs": ["SYD", "MEL"]},
    "KAL": {"name": "Korean Air", "weight": 0.01, "hubs": ["ICN"]},
    "THY": {"name": "Turkish Airlines", "weight": 0.01, "hubs": ["IST"]},
    "ETD": {"name": "Etihad Airways", "weight": 0.01, "hubs": ["AUH"]},
    "ACA": {"name": "Air Canada", "weight": 0.01, "hubs": ["YYZ", "YVR"]},
    "AMX": {"name": "Aeromexico", "weight": 0.01, "hubs": ["MEX"]},
    "TAM": {"name": "LATAM Airlines", "weight": 0.01, "hubs": ["GRU", "SCL"]},
    "SAA": {"name": "South African Airways", "weight": 0.005, "hubs": ["JNB"]},
    "EVA": {"name": "EVA Air", "weight": 0.005, "hubs": ["TPE"]},
    "FDB": {"name": "flydubai", "weight": 0.005, "hubs": ["DXB"]},
    "VIR": {"name": "Virgin Atlantic", "weight": 0.005, "hubs": ["LHR"]},
    "RYR": {"name": "Ryanair", "weight": 0.005, "hubs": ["STN", "DUB"]},
    "EZY": {"name": "easyJet", "weight": 0.005, "hubs": ["LGW", "LTN"]},
}

# Destination airports with distance category
DOMESTIC_AIRPORTS = [
    "LAX", "ORD", "DFW", "JFK", "ATL", "DEN", "SEA", "BOS", "PHX", "LAS",
    "MCO", "MIA", "CLT", "MSP", "DTW", "EWR", "PHL", "IAH", "SAN", "PDX",
]

INTERNATIONAL_AIRPORTS = [
    "LHR", "CDG", "FRA", "AMS", "HKG", "NRT", "SIN", "SYD", "DXB", "ICN",
]

# Country-based domestic airports for international hubs where
# domestic_route_shares may be empty in the calibrated profile.
COUNTRY_DOMESTIC_AIRPORTS: dict[str, list[str]] = {
    "DE": ["MUC", "DUS", "HAM", "BER", "STR", "CGN"],
    "FR": ["ORY", "NCE", "LYS", "MRS", "TLS", "BOD"],
    "JP": ["HND", "KIX", "FUK", "CTS", "OKA", "NGO"],
    "KR": ["GMP", "PUS", "CJU", "TAE", "KWJ"],
    "GB": ["LGW", "MAN", "EDI", "BHX", "GLA", "BRS"],
    "NL": ["EIN", "RTM", "MST"],
    "AE": ["AUH", "SHJ", "DWC"],
    "SG": [],
    "HK": [],
    "AU": ["MEL", "BNE", "PER", "ADL", "CBR", "OOL"],
    "BR": ["CGH", "GIG", "BSB", "CNF", "SSA", "CWB"],
    "ZA": ["CPT", "DUR", "PLZ", "BFN"],
    "TR": ["SAW", "ESB", "AYT", "ADB", "ADA"],
    "CA": ["YYZ", "YVR", "YUL", "YOW", "YEG", "YWG"],
    "MX": ["CUN", "GDL", "MTY", "TIJ", "CJS"],
    "TW": ["TSA", "KHH", "RMQ", "TNN"],
    "CL": ["SCL", "CCP", "PMC", "IQQ"],
}

AIRPORT_COUNTRY: dict[str, str] = {
    "FRA": "DE", "MUC": "DE",
    "CDG": "FR", "ORY": "FR",
    "NRT": "JP", "HND": "JP",
    "ICN": "KR", "GMP": "KR",
    "LHR": "GB", "LGW": "GB", "STN": "GB",
    "AMS": "NL",
    "DXB": "AE", "AUH": "AE",
    "SIN": "SG",
    "HKG": "HK",
    "SYD": "AU", "MEL": "AU",
    "GRU": "BR", "GIG": "BR",
    "JNB": "ZA", "CPT": "ZA",
    "IST": "TR",
    "YYZ": "CA", "YVR": "CA",
    "MEX": "MX",
    "TPE": "TW",
    "SCL": "CL",
}

# Real airport coordinates (lat, lon) for all origin/destination airports
AIRPORT_COORDINATES = {
    # Home airport
    "SFO": (37.6213, -122.379),
    # Domestic
    "LAX": (33.9425, -118.408),
    "ORD": (41.9742, -87.9073),
    "DFW": (32.8998, -97.0403),
    "JFK": (40.6413, -73.7781),
    "ATL": (33.6407, -84.4277),
    "DEN": (39.8561, -104.6737),
    "SEA": (47.4502, -122.3088),
    "BOS": (42.3656, -71.0096),
    "PHX": (33.4373, -112.0078),
    "LAS": (36.0840, -115.1537),
    "MCO": (28.4312, -81.3081),
    "MIA": (25.7959, -80.2870),
    "CLT": (35.2140, -80.9431),
    "MSP": (44.8848, -93.2223),
    "DTW": (42.2124, -83.3534),
    "EWR": (40.6895, -74.1745),
    "PHL": (39.8744, -75.2424),
    "IAH": (29.9902, -95.3368),
    "SAN": (32.7338, -117.1933),
    "PDX": (45.5898, -122.5951),
    # International
    "LHR": (51.4700, -0.4543),
    "CDG": (49.0097, 2.5479),
    "FRA": (50.0379, 8.5622),
    "AMS": (52.3105, 4.7683),
    "HKG": (22.3080, 113.9185),
    "NRT": (35.7647, 140.3864),
    "SIN": (1.3644, 103.9915),
    "SYD": (-33.9461, 151.1772),
    "DXB": (25.2532, 55.3657),
    "ICN": (37.4602, 126.4407),
    "GRU": (-23.4356, -46.4731),
    "JNB": (-26.1367, 28.2411),
    "CPT": (-33.9715, 18.6021),
}

# Aircraft types by category
NARROW_BODY = ["A320", "A321", "B737", "B738", "A319", "E175"]
WIDE_BODY = ["B777", "B787", "A330", "A350", "A380"]

# Turnaround times by aircraft category (minutes)
NARROW_BODY_TURNAROUND = 45
WIDE_BODY_TURNAROUND = 90
GATE_COOLDOWN_BUFFER = 10  # minutes between consecutive occupations

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


def _select_airline(profile: AirportProfile | None = None) -> tuple[str, str]:
    """Select an airline based on weighted distribution.

    If a calibrated profile is provided, sample from its airline_shares.
    Otherwise fall back to the hardcoded AIRLINES dict.
    """
    if profile and profile.airline_shares:
        codes = list(profile.airline_shares.keys())
        weights = list(profile.airline_shares.values())
        code = random.choices(codes, weights=weights, k=1)[0]
        # Look up full name from AIRLINES dict, fall back to code
        name = AIRLINES[code]["name"] if code in AIRLINES else code
        return code, name

    codes = list(AIRLINES.keys())
    weights = [AIRLINES[code]["weight"] for code in codes]
    code = random.choices(codes, weights=weights, k=1)[0]
    return code, AIRLINES[code]["name"]


def _generate_flight_number(airline_code: str) -> str:
    """Generate a realistic flight number."""
    # Domestic flights typically 1-999, international 1-9999
    num = random.randint(1, 2999)
    return f"{airline_code}{num}"


def _select_destination(
    flight_type: str, airline_code: str,
    profile: AirportProfile | None = None,
    airport: str | None = None,
) -> str:
    """Select destination based on airline and flight type.

    If a calibrated profile is provided, sample from its route shares
    and domestic_ratio. Otherwise fall back to uniform random choice.

    When domestic_route_shares is empty (common for international hubs like
    FRA, CDG, NRT, ICN), falls back to country-based domestic airports.
    """
    if profile and (profile.domestic_route_shares or profile.international_route_shares):
        is_domestic = random.random() < profile.domestic_ratio
        if is_domestic and profile.domestic_route_shares:
            routes = list(profile.domestic_route_shares.keys())
            weights = list(profile.domestic_route_shares.values())
            return random.choices(routes, weights=weights, k=1)[0]
        elif is_domestic and not profile.domestic_route_shares:
            # No calibrated domestic routes — use country-based fallback
            iata = airport or ""
            country = AIRPORT_COUNTRY.get(iata)
            if country and COUNTRY_DOMESTIC_AIRPORTS.get(country):
                candidates = [a for a in COUNTRY_DOMESTIC_AIRPORTS[country] if a != iata]
                if candidates:
                    return random.choice(candidates)
            # Country has no domestic airports (SG, HK) — fall through to international
        if profile.international_route_shares:
            routes = list(profile.international_route_shares.keys())
            weights = list(profile.international_route_shares.values())
            return random.choices(routes, weights=weights, k=1)[0]

    # Fallback: 70% domestic, 30% international, uniform random
    if random.random() < 0.7:
        return random.choice(DOMESTIC_AIRPORTS)
    return random.choice(INTERNATIONAL_AIRPORTS)


def _select_aircraft(
    destination: str,
    airline_code: str | None = None,
    profile: AirportProfile | None = None,
) -> str:
    """Select aircraft type based on route and optional profile fleet mix.

    If a calibrated profile is provided with fleet_mix for this airline,
    sample from the fleet distribution. Otherwise fall back to narrow/wide
    body selection based on route type.
    """
    if profile and airline_code and airline_code in profile.fleet_mix:
        fleet = profile.fleet_mix[airline_code]
        if fleet:
            types = list(fleet.keys())
            weights = list(fleet.values())
            return random.choices(types, weights=weights, k=1)[0]

    # Fallback: wide body for international, narrow body for domestic
    if destination in INTERNATIONAL_AIRPORTS:
        return random.choice(WIDE_BODY)
    return random.choice(NARROW_BODY)


def _generate_delay_details(
    profile: AirportProfile | None = None,
) -> tuple[int, str, str]:
    """Generate delay details (minutes, code, reason) without rate check.

    Always returns a delay. The caller is responsible for deciding which
    flights get delayed (Bernoulli flip or two-pass assignment).
    """
    import math

    # Select delay code based on weights
    if profile and profile.delay_distribution:
        codes = list(profile.delay_distribution.keys())
        weights = list(profile.delay_distribution.values())
    else:
        codes = list(DELAY_CODES.keys())
        weights = [DELAY_CODES[code][1] for code in codes]

    code = random.choices(codes, weights=weights, k=1)[0]
    reason = DELAY_CODES[code][0] if code in DELAY_CODES else f"Delay code {code}"

    # Delay duration: log-normal distribution (realistic right-skewed delays)
    mean_delay = profile.mean_delay_minutes if profile else 20.0
    sigma = 0.8
    mu = math.log(max(mean_delay, 5.0)) - sigma * sigma / 2.0
    delay_minutes = max(5, min(120, round(random.lognormvariate(mu, sigma))))

    return delay_minutes, code, reason


def _generate_delay(
    profile: AirportProfile | None = None,
) -> tuple[int, Optional[str], Optional[str]]:
    """Generate realistic delay if applicable (single-flight Bernoulli).

    If a calibrated profile is provided, use its delay_rate and
    delay_distribution instead of the hardcoded 15% rate.

    Note: generate_daily_schedule() uses the two-pass method instead
    for tighter delay-rate accuracy. This function is kept for
    backward compatibility with other callers.
    """
    delay_rate = profile.delay_rate if profile else 0.15

    if random.random() > delay_rate:
        return 0, None, None

    return _generate_delay_details(profile=profile)


# Per-airport traffic profiles
# Each profile is a 24-element list of (min, max) flights per hour.
# "us_dual_peak": US domestic — morning + evening peaks (SFO, JFK, etc.)
# "3bank_hub": Gulf hub — 3 connect banks per day (DXB)
# "slot_constrained": European slot-limited — flat plateau (LHR)
# "curfew_compressed": Curfew airport — compressed into 06:00-22:00 (NRT, SYD)
TRAFFIC_PROFILES: dict[str, list[tuple[int, int]]] = {
    "us_dual_peak": [
        (0, 2), (0, 2), (0, 1), (0, 1), (1, 3), (5, 10),    # 00-05
        (18, 25), (18, 25), (18, 25), (18, 25), (10, 15), (10, 15),  # 06-11
        (10, 15), (10, 15), (10, 15), (10, 15), (18, 25), (18, 25),  # 12-17
        (18, 25), (18, 25), (8, 12), (8, 12), (5, 8), (0, 3),       # 18-23
    ],
    "3bank_hub": [
        (0, 2), (2, 5), (5, 10), (8, 12), (8, 12), (5, 8),    # 00-05: Bank 1 prep
        (20, 28), (22, 30), (22, 30), (10, 15), (8, 12), (5, 8),  # 06-11: Bank 1
        (8, 12), (20, 28), (22, 30), (22, 30), (10, 15), (8, 12),  # 12-17: Bank 2
        (5, 8), (18, 25), (20, 28), (22, 30), (15, 20), (8, 12),  # 18-23: Bank 3
    ],
    "slot_constrained": [
        (0, 2), (0, 1), (0, 1), (0, 1), (2, 5), (8, 12),     # 00-05
        (14, 18), (14, 18), (14, 18), (14, 18), (14, 18), (14, 18),  # 06-11: flat plateau
        (14, 18), (14, 18), (14, 18), (14, 18), (14, 18), (14, 18),  # 12-17: flat plateau
        (14, 18), (14, 18), (10, 14), (8, 12), (5, 8), (2, 5),      # 18-23
    ],
    "curfew_compressed": [
        (0, 0), (0, 0), (0, 0), (0, 0), (0, 0), (0, 1),       # 00-05: curfew
        (15, 22), (20, 28), (20, 28), (15, 20), (12, 18), (12, 18),  # 06-11: morning rush
        (12, 18), (12, 18), (15, 20), (18, 25), (20, 28), (20, 28),  # 12-17: evening rush
        (15, 22), (12, 18), (8, 12), (5, 8), (2, 5), (0, 0),        # 18-23: wind down
    ],
}

# Day-of-week traffic multipliers (0=Monday..6=Sunday)
# Weekdays are baseline; Saturdays have reduced traffic; Sundays slightly reduced.
DAY_OF_WEEK_TRAFFIC_FACTOR: dict[int, float] = {
    0: 1.0,   # Monday
    1: 1.0,   # Tuesday
    2: 1.0,   # Wednesday
    3: 1.0,   # Thursday
    4: 1.0,   # Friday
    5: 0.82,  # Saturday: -18% overall (leisure pattern)
    6: 0.90,  # Sunday: -10% (redeye recovery)
}

# Saturday peak hour shift: morning peak starts 1h later
DAY_OF_WEEK_PEAK_SHIFT: dict[int, int] = {
    5: 1,  # Saturday: shift morning peak +1 hour
}

# Current traffic profile (set by simulation engine based on airport characteristics)
_current_profile: str = "us_dual_peak"


def set_traffic_profile(profile: str) -> None:
    """Set the traffic profile directly (e.g. 'us_dual_peak', '3bank_hub')."""
    global _current_profile
    if profile in TRAFFIC_PROFILES:
        _current_profile = profile


def set_traffic_airport(airport: str, runway_count: int = 2, has_curfew: bool = False) -> None:
    """Derive and set the traffic profile from airport characteristics.

    Instead of hardcoding per IATA code, the profile is selected based on
    observable airport properties (runway count as a size proxy, curfew presence).
    """
    global _current_profile
    if has_curfew:
        _current_profile = "curfew_compressed"
    elif runway_count >= 4:
        _current_profile = "3bank_hub"  # large hub pattern
    elif runway_count == 2:
        _current_profile = "us_dual_peak"
    else:
        _current_profile = "slot_constrained"  # small single-runway → flat


def _get_flights_per_hour(
    hour: int,
    profile: str | None = None,
    airport_profile: AirportProfile | None = None,
    day_of_week: int | None = None,
) -> int:
    """Get number of flights for a given hour based on traffic profile.

    If an AirportProfile with hourly_profile is given, use it as relative
    weights to distribute flights. Otherwise fall back to TRAFFIC_PROFILES.

    When ``day_of_week`` is provided (0=Mon..6=Sun) the count is scaled by
    DAY_OF_WEEK_TRAFFIC_FACTOR and the hour is shifted by
    DAY_OF_WEEK_PEAK_SHIFT (e.g. Saturday morning peak starts 1h later).
    """
    effective_hour = hour
    if day_of_week is not None:
        effective_hour = hour - DAY_OF_WEEK_PEAK_SHIFT.get(day_of_week, 0)
        if effective_hour < 0:
            effective_hour = 0

    # If we have a calibrated hourly profile, return a relative weight
    # (caller uses this as a weight for distributing total flights)
    if airport_profile and airport_profile.hourly_profile and len(airport_profile.hourly_profile) == 24:
        # Return weight scaled to approximate flight count range (0-30)
        weight = airport_profile.hourly_profile[effective_hour % 24]
        max_weight = max(airport_profile.hourly_profile)
        if max_weight > 0:
            scaled = weight / max_weight * 25  # scale to ~25 max
            noise_range = max(0.5, scaled * 0.15)  # 15% proportional noise
            base = max(0, int(scaled + random.uniform(-noise_range, noise_range)))
        else:
            base = 0
    else:
        p = profile or _current_profile
        if p not in TRAFFIC_PROFILES:
            p = "us_dual_peak"
        lo, hi = TRAFFIC_PROFILES[p][effective_hour % 24]
        base = random.randint(lo, hi)

    # Apply day-of-week traffic factor
    if day_of_week is not None:
        factor = DAY_OF_WEEK_TRAFFIC_FACTOR.get(day_of_week, 1.0)
        base = max(0, round(base * factor))

    return base


def _get_turnaround_minutes(aircraft_type: str) -> int:
    """Get turnaround time based on aircraft type."""
    if aircraft_type in WIDE_BODY:
        return WIDE_BODY_TURNAROUND
    return NARROW_BODY_TURNAROUND


def _assign_gate_with_occupancy(
    gates: list[str],
    gate_timeline: dict[str, list[tuple[datetime, datetime]]],
    scheduled_time: datetime,
    is_arrival: bool,
    aircraft_type: str,
) -> str:
    """Assign a gate ensuring no overlapping occupancy.

    Args:
        gates: Available gate names
        gate_timeline: Dict mapping gate -> list of (start, end) occupation windows
        scheduled_time: Scheduled arrival/departure time
        is_arrival: Whether this is an arrival (True) or departure (False)
        aircraft_type: Aircraft type to determine turnaround duration

    Returns:
        Assigned gate name (updates gate_timeline in place)
    """
    if not gates:
        return "A1"

    turnaround = _get_turnaround_minutes(aircraft_type)
    buffer = GATE_COOLDOWN_BUFFER

    # Compute the occupation window for this flight
    if is_arrival:
        occ_start = scheduled_time
        occ_end = scheduled_time + timedelta(minutes=turnaround)
    else:
        occ_start = scheduled_time - timedelta(minutes=turnaround)
        occ_end = scheduled_time

    # Add buffer
    check_start = occ_start - timedelta(minutes=buffer)
    check_end = occ_end + timedelta(minutes=buffer)

    def _overlap_count(gate: str) -> int:
        """Count how many existing windows overlap with the proposed window."""
        count = 0
        for existing_start, existing_end in gate_timeline.get(gate, []):
            if existing_start < check_end and existing_end > check_start:
                count += 1
        return count

    # Try to find a gate with zero conflicts
    candidates = [(g, _overlap_count(g)) for g in gates]
    # Sort by conflict count, then random tiebreak
    random.shuffle(candidates)
    candidates.sort(key=lambda x: x[1])

    gate = candidates[0][0]

    # Record the occupation
    if gate not in gate_timeline:
        gate_timeline[gate] = []
    gate_timeline[gate].append((occ_start, occ_end))

    return gate


def generate_daily_schedule(
    airport: str = "SFO",
    date: Optional[datetime] = None,
    include_past_hours: int = 2,
    profile: AirportProfile | None = None,
) -> list[dict]:
    """
    Generate a synthetic daily flight schedule.

    Args:
        airport: Airport IATA code (used as origin for departures, destination for arrivals)
        date: Date for schedule (defaults to today)
        include_past_hours: Include flights from past N hours (for realistic display)
        profile: Optional calibrated AirportProfile for realistic distributions

    Returns:
        List of scheduled flight dictionaries
    """
    if date is None:
        date = datetime.now(timezone.utc)

    # Start from past hours for arrivals/departures that already happened
    start_hour = max(0, date.hour - include_past_hours)
    schedule = []

    # Track gate occupancy to prevent overlapping assignments
    available_gates = list(get_gates().keys())
    gate_timeline: dict[str, list[tuple[datetime, datetime]]] = {}

    # Generate flights for each hour
    for hour in range(start_hour, 24):
        flights_this_hour = _get_flights_per_hour(hour, airport_profile=profile)

        for _ in range(flights_this_hour):
            # 50% arrivals, 50% departures
            is_arrival = random.random() < 0.5

            airline_code, airline_name = _select_airline(profile=profile)
            flight_number = _generate_flight_number(airline_code)

            if is_arrival:
                origin = _select_destination("arrival", airline_code, profile=profile, airport=airport)
                destination = airport
            else:
                origin = airport
                destination = _select_destination("departure", airline_code, profile=profile, airport=airport)

            remote_airport = origin if is_arrival else destination
            aircraft = _select_aircraft(
                remote_airport, airline_code=airline_code, profile=profile,
            )

            # Generate scheduled time within the hour
            minute = random.randint(0, 59)
            scheduled_time = date.replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )

            # Assign gate with occupancy tracking (no double-booking)
            gate = _assign_gate_with_occupancy(
                available_gates, gate_timeline, scheduled_time,
                is_arrival, aircraft,
            )

            flight = {
                "flight_number": flight_number,
                "airline": airline_name,
                "airline_code": airline_code,
                "origin": origin,
                "destination": destination,
                "scheduled_time": scheduled_time.isoformat(),
                "estimated_time": None,
                "actual_time": None,
                "gate": gate,
                "status": "on_time",
                "delay_minutes": 0,
                "delay_reason": None,
                "aircraft_type": aircraft,
                "flight_type": "arrival" if is_arrival else "departure",
            }
            schedule.append(flight)

    # --- Two-pass delay assignment ---
    # Assign exact number of delayed flights to match profile delay_rate.
    delay_rate = profile.delay_rate if profile else 0.15
    n_delayed = round(len(schedule) * delay_rate)
    if n_delayed > 0:
        delayed_indices = random.sample(range(len(schedule)), min(n_delayed, len(schedule)))
        now = datetime.now(timezone.utc)
        for idx in delayed_indices:
            flight = schedule[idx]
            delay_minutes, delay_code, delay_reason = _generate_delay_details(profile=profile)
            scheduled_time = datetime.fromisoformat(flight["scheduled_time"])
            estimated_time = scheduled_time + timedelta(minutes=delay_minutes)
            flight["delay_minutes"] = delay_minutes
            flight["delay_reason"] = delay_reason
            flight["estimated_time"] = estimated_time.isoformat()

    # --- Assign statuses based on time ---
    now = datetime.now(timezone.utc)
    for flight in schedule:
        scheduled_time = datetime.fromisoformat(flight["scheduled_time"])
        estimated_time = (
            datetime.fromisoformat(flight["estimated_time"])
            if flight["estimated_time"]
            else None
        )
        effective_time = estimated_time or scheduled_time
        is_arrival = flight["flight_type"] == "arrival"

        if effective_time < now - timedelta(minutes=15):
            flight["status"] = "arrived" if is_arrival else "departed"
            flight["actual_time"] = effective_time.isoformat()
        elif effective_time < now:
            flight["status"] = "boarding" if not is_arrival else "arrived"
            flight["actual_time"] = effective_time.isoformat() if is_arrival else None
        elif flight["delay_minutes"] > 0:
            flight["status"] = "delayed"
        else:
            flight["status"] = "on_time"

    # Sort by scheduled time
    schedule.sort(key=lambda x: x["scheduled_time"])
    return schedule


def get_arrivals(
    airport: str = "SFO",
    hours_ahead: int = 2,
    hours_behind: int = 1,
) -> list[dict]:
    """Get arrivals for the specified time window."""
    schedule = get_cached_schedule(airport=airport)
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
    schedule = get_cached_schedule(airport=airport)
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

# Lazy-loaded profile loader singleton
_profile_loader: Optional["AirportProfileLoader"] = None


def _get_profile_loader() -> "AirportProfileLoader":
    """Get or create the singleton profile loader."""
    global _profile_loader
    if _profile_loader is None:
        from src.calibration.profile import AirportProfileLoader
        _profile_loader = AirportProfileLoader()
    return _profile_loader


def get_cached_schedule(airport: str = "SFO") -> list[dict]:
    """Get cached schedule (regenerates every minute for freshness).

    Automatically loads the calibrated AirportProfile for the requested
    airport, falling back gracefully if no profile is available.
    """
    global _schedule_cache, _cache_minute
    current_minute = datetime.now(timezone.utc).minute

    if _cache_minute != current_minute or airport not in _schedule_cache:
        profile = _get_profile_loader().get_profile(airport)
        _schedule_cache[airport] = generate_daily_schedule(
            airport=airport, profile=profile,
        )
        _cache_minute = current_minute

    return _schedule_cache[airport]


def find_scheduled_departure(callsign: str, airport: str = "SFO") -> Optional[dict]:
    """Find a scheduled departure matching a callsign.

    Searches the cached schedule for a departure whose flight number
    shares the same airline prefix (first 3 chars) as the callsign.
    Returns the best match dict with 'scheduled_time' and 'estimated_time',
    or None if no match found.
    """
    schedule = get_cached_schedule(airport=airport)
    if not callsign or len(callsign) < 3:
        return None

    airline_prefix = callsign[:3]

    # First try exact match on flight_number
    for f in schedule:
        if f["flight_type"] != "departure":
            continue
        if f["flight_number"] == callsign:
            return f

    # Fall back to next departure by same airline prefix
    now = datetime.now(timezone.utc)
    best = None
    for f in schedule:
        if f["flight_type"] != "departure":
            continue
        if not f["flight_number"].startswith(airline_prefix):
            continue
        sched_time = datetime.fromisoformat(f["scheduled_time"])
        if sched_time > now:
            if best is None or sched_time < datetime.fromisoformat(best["scheduled_time"]):
                best = f

    return best


def get_future_schedule(
    airport: str = "SFO",
    after: datetime | None = None,
    flight_type: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """Get scheduled flights after a cutoff time.

    Args:
        airport: Airport IATA code
        after: Only return flights scheduled after this time (defaults to now)
        flight_type: Filter by "arrival" or "departure" (None for both)
        limit: Maximum number of flights to return

    Returns:
        List of future flight schedule dicts, sorted by scheduled_time
    """
    if after is None:
        after = datetime.now(timezone.utc)

    schedule = get_cached_schedule(airport=airport)
    future = []
    for f in schedule:
        sched_time = datetime.fromisoformat(f["scheduled_time"])
        if sched_time <= after:
            continue
        if flight_type and f["flight_type"] != flight_type:
            continue
        future.append(f)
        if len(future) >= limit:
            break

    return future
