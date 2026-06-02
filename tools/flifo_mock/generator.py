"""Flight record generator for FLIFO mock responses.

Generates realistic flight records matching FLIFO API shape.
Uses seeded random for deterministic replay given same airport+date.
"""

import random
import string
from datetime import datetime, timedelta, timezone
from typing import Optional

from tools.flifo_mock.models import (
    AircraftInfo,
    AirlineInfo,
    AirportPoint,
    CodeshareInfo,
    FlightRecord,
)

# FLIFO status codes with descriptions and time-relative weights
STATUS_CODES = {
    "SC": "Scheduled",
    "ON": "On Time",
    "DL": "Delayed",
    "BD": "Boarding",
    "GC": "Gate Closed",
    "DP": "Departed",
    "IA": "In Air",
    "AR": "Arrived",
    "CX": "Cancelled",
    "DV": "Diverted",
    "FC": "Final Call",
    "LN": "Landed",
    "TX": "Taxiing",
    "BG": "Baggage on Belt",
    "NI": "Next Information",
    "FE": "Flight Estimated",
    "FS": "Flight Suspended",
    "RE": "Return to Ramp",
    "OB": "Off Block",
    "AB": "Airborne",
    "FI": "Final",
    "GO": "Gate Open",
    "CD": "Check-in Closed",
    "CO": "Check-in Open",
    "NS": "New Schedule",
    "RS": "Return to Stand",
    "DE": "De-iced",
    "AX": "Arrival Cancelled",
}

# IATA delay reason codes
DELAY_CODES = {
    "00": "No delay",
    "11": "Late passenger",
    "13": "Cabin crew shortage",
    "15": "Boarding/gate processes",
    "19": "Reduced mobility passenger",
    "31": "Aircraft documentation",
    "32": "Loading/unloading",
    "33": "Baggage processing",
    "34": "Cargo processing",
    "41": "Aircraft defect",
    "42": "Scheduled maintenance",
    "61": "ATFM restriction",
    "63": "Airport/runway closure",
    "65": "Aerodrome capacity",
    "71": "De-icing",
    "72": "Snow/ice removal",
    "75": "Bird strike",
    "81": "ATC slot",
    "82": "ATC staffing",
    "84": "ATC equipment",
    "86": "Weather",
    "87": "Thunderstorms",
    "89": "Volcanic ash",
    "91": "Connecting crew from delayed flight",
    "93": "Operational requirements",
    "96": "Industrial action",
    "99": "Miscellaneous",
}

# Airlines with IATA/ICAO codes, names, and typical route data
AIRLINES = [
    {"iata": "UA", "icao": "UAL", "name": "United Airlines", "weight": 0.20, "hubs": ["SFO", "ORD", "IAH", "EWR", "DEN"]},
    {"iata": "DL", "icao": "DAL", "name": "Delta Air Lines", "weight": 0.12, "hubs": ["ATL", "DTW", "MSP", "SLC", "JFK"]},
    {"iata": "AA", "icao": "AAL", "name": "American Airlines", "weight": 0.12, "hubs": ["DFW", "CLT", "MIA", "PHX", "ORD"]},
    {"iata": "WN", "icao": "SWA", "name": "Southwest Airlines", "weight": 0.08, "hubs": ["DAL", "HOU", "BWI", "MDW", "LAS"]},
    {"iata": "AS", "icao": "ASA", "name": "Alaska Airlines", "weight": 0.06, "hubs": ["SEA", "SFO", "LAX", "PDX"]},
    {"iata": "B6", "icao": "JBU", "name": "JetBlue Airways", "weight": 0.04, "hubs": ["JFK", "BOS", "FLL"]},
    {"iata": "NK", "icao": "NKS", "name": "Spirit Airlines", "weight": 0.02, "hubs": ["FLL", "LAS", "MCO"]},
    {"iata": "EK", "icao": "UAE", "name": "Emirates", "weight": 0.03, "hubs": ["DXB"]},
    {"iata": "BA", "icao": "BAW", "name": "British Airways", "weight": 0.03, "hubs": ["LHR", "LGW"]},
    {"iata": "NH", "icao": "ANA", "name": "All Nippon Airways", "weight": 0.02, "hubs": ["HND", "NRT"]},
    {"iata": "CX", "icao": "CPA", "name": "Cathay Pacific", "weight": 0.02, "hubs": ["HKG"]},
    {"iata": "LH", "icao": "DLH", "name": "Lufthansa", "weight": 0.03, "hubs": ["FRA", "MUC"]},
    {"iata": "AF", "icao": "AFR", "name": "Air France", "weight": 0.02, "hubs": ["CDG", "ORY"]},
    {"iata": "KL", "icao": "KLM", "name": "KLM Royal Dutch", "weight": 0.02, "hubs": ["AMS"]},
    {"iata": "JL", "icao": "JAL", "name": "Japan Airlines", "weight": 0.02, "hubs": ["NRT", "HND"]},
    {"iata": "SQ", "icao": "SIA", "name": "Singapore Airlines", "weight": 0.02, "hubs": ["SIN"]},
    {"iata": "QF", "icao": "QFA", "name": "Qantas", "weight": 0.01, "hubs": ["SYD", "MEL"]},
    {"iata": "TK", "icao": "THY", "name": "Turkish Airlines", "weight": 0.02, "hubs": ["IST"]},
    {"iata": "AC", "icao": "ACA", "name": "Air Canada", "weight": 0.02, "hubs": ["YYZ", "YVR"]},
    {"iata": "AM", "icao": "AMX", "name": "Aeromexico", "weight": 0.02, "hubs": ["MEX"]},
    {"iata": "KE", "icao": "KAL", "name": "Korean Air", "weight": 0.01, "hubs": ["ICN"]},
    {"iata": "EY", "icao": "ETD", "name": "Etihad Airways", "weight": 0.01, "hubs": ["AUH"]},
    {"iata": "SV", "icao": "SVA", "name": "Saudia", "weight": 0.01, "hubs": ["JED", "RUH"]},
    {"iata": "AI", "icao": "AIC", "name": "Air India", "weight": 0.01, "hubs": ["DEL", "BOM"]},
]

# Common destinations by region
DESTINATIONS = {
    "domestic_us": ["LAX", "JFK", "ORD", "ATL", "DEN", "DFW", "SEA", "BOS", "MIA", "PHX", "LAS", "MCO", "MSP", "DTW", "CLT", "EWR", "IAH", "SLC", "DCA", "SAN"],
    "europe": ["LHR", "CDG", "FRA", "AMS", "MAD", "FCO", "MUC", "ZRH", "IST", "BCN", "DUB", "VIE", "CPH", "OSL", "ARN"],
    "asia_pacific": ["HND", "NRT", "HKG", "SIN", "ICN", "PVG", "PEK", "BKK", "SYD", "MEL", "TPE", "DEL", "BOM"],
    "middle_east": ["DXB", "DOH", "AUH", "JED", "RUH", "AMM", "BAH", "KWI"],
    "americas": ["YYZ", "YVR", "MEX", "GRU", "SCL", "BOG", "LIM", "EZE", "CUN"],
}

# Aircraft types with IATA/ICAO codes
AIRCRAFT_TYPES = [
    {"iata": "320", "icao": "A320", "weight": 0.20},
    {"iata": "321", "icao": "A321", "weight": 0.12},
    {"iata": "738", "icao": "B738", "weight": 0.15},
    {"iata": "73H", "icao": "B38M", "weight": 0.10},
    {"iata": "789", "icao": "B789", "weight": 0.08},
    {"iata": "77W", "icao": "B77W", "weight": 0.06},
    {"iata": "359", "icao": "A359", "weight": 0.05},
    {"iata": "388", "icao": "A388", "weight": 0.02},
    {"iata": "E75", "icao": "E75L", "weight": 0.08},
    {"iata": "CR9", "icao": "CRJ9", "weight": 0.05},
    {"iata": "223", "icao": "A220", "weight": 0.04},
    {"iata": "764", "icao": "B764", "weight": 0.03},
    {"iata": "333", "icao": "A333", "weight": 0.02},
]


def _generate_registration(airline: dict, rng: random.Random) -> str:
    """Generate plausible aircraft registration."""
    country_prefixes = {
        "UA": "N", "DL": "N", "AA": "N", "WN": "N", "AS": "N", "B6": "N", "NK": "N",
        "BA": "G-", "LH": "D-A", "AF": "F-", "KL": "PH-",
        "EK": "A6-", "SQ": "9V-", "QF": "VH-", "NH": "JA", "JL": "JA",
        "AC": "C-", "TK": "TC-", "KE": "HL", "EY": "A6-",
    }
    prefix = country_prefixes.get(airline["iata"], "N")
    suffix = "".join(rng.choices(string.digits + string.ascii_uppercase, k=4))
    return f"{prefix}{suffix}"


def _pick_status_for_time(minutes_to_scheduled: float, direction: str, rng: random.Random) -> tuple[str, str, int, Optional[str]]:
    """Pick realistic status based on time relative to scheduled.

    Returns (statusCode, statusDescription, delayMinutes, delayCode).
    """
    if minutes_to_scheduled > 120:
        return "SC", "Scheduled", 0, None

    if minutes_to_scheduled > 60:
        if rng.random() < 0.85:
            return "ON", "On Time", 0, None
        delay = rng.choice([15, 20, 30, 45, 60])
        code = rng.choice(["81", "86", "41", "61"])
        return "DL", "Delayed", delay, code

    if minutes_to_scheduled > 30:
        r = rng.random()
        if r < 0.70:
            return "ON", "On Time", 0, None
        if r < 0.85:
            delay = rng.choice([10, 15, 20, 30])
            code = rng.choice(["81", "86", "41", "15"])
            return "DL", "Delayed", delay, code
        if r < 0.90:
            return "CX", "Cancelled", 0, "96"
        if direction == "departure":
            return "GO", "Gate Open", 0, None
        return "FE", "Flight Estimated", 0, None

    if minutes_to_scheduled > 10:
        if direction == "departure":
            r = rng.random()
            if r < 0.40:
                return "BD", "Boarding", 0, None
            if r < 0.55:
                return "FC", "Final Call", 0, None
            if r < 0.70:
                return "GC", "Gate Closed", 0, None
            if r < 0.85:
                return "ON", "On Time", 0, None
            delay = rng.choice([10, 15, 20])
            return "DL", "Delayed", delay, rng.choice(["81", "86", "15"])
        else:
            r = rng.random()
            if r < 0.50:
                return "IA", "In Air", 0, None
            if r < 0.70:
                return "ON", "On Time", 0, None
            delay = rng.choice([10, 15, 20])
            return "DL", "Delayed", delay, rng.choice(["81", "86"])

    if minutes_to_scheduled > -10:
        if direction == "departure":
            r = rng.random()
            if r < 0.40:
                return "DP", "Departed", 0, None
            if r < 0.60:
                return "OB", "Off Block", 0, None
            if r < 0.75:
                return "GC", "Gate Closed", 0, None
            delay = rng.choice([5, 10, 15])
            return "DL", "Delayed", delay, rng.choice(["81", "32", "41"])
        else:
            r = rng.random()
            if r < 0.35:
                return "LN", "Landed", 0, None
            if r < 0.55:
                return "TX", "Taxiing", 0, None
            if r < 0.70:
                return "AR", "Arrived", 0, None
            if r < 0.85:
                return "IA", "In Air", 0, None
            delay = rng.choice([5, 10, 15])
            return "DL", "Delayed", delay, rng.choice(["86", "63"])

    if minutes_to_scheduled > -60:
        if direction == "departure":
            r = rng.random()
            if r < 0.80:
                return "DP", "Departed", 0, None
            if r < 0.90:
                return "AB", "Airborne", 0, None
            return "DL", "Delayed", rng.choice([15, 25, 40]), rng.choice(["41", "81"])
        else:
            r = rng.random()
            if r < 0.60:
                return "AR", "Arrived", 0, None
            if r < 0.80:
                return "BG", "Baggage on Belt", 0, None
            if r < 0.90:
                return "LN", "Landed", 0, None
            return "DL", "Delayed", rng.choice([15, 20, 30]), "86"

    # Past > 60min
    if direction == "departure":
        return "DP", "Departed", 0, None
    return "AR", "Arrived", 0, None


def _pick_destination(airline: dict, airport_iata: str, direction: str, rng: random.Random) -> str:
    """Pick plausible origin/destination for a flight."""
    if direction == "arrival":
        # Pick an origin — could be airline hub or random destination
        if rng.random() < 0.4 and airline["hubs"]:
            candidates = [h for h in airline["hubs"] if h != airport_iata]
            if candidates:
                return rng.choice(candidates)

    all_dests = []
    for region_list in DESTINATIONS.values():
        all_dests.extend(region_list)
    candidates = [d for d in all_dests if d != airport_iata]
    return rng.choice(candidates)


def _generate_flight_number(airline: dict, rng: random.Random) -> str:
    """Generate realistic flight number."""
    num = rng.randint(1, 9999)
    return f"{airline['iata']}{num}"


def _load_airport_weights(airport_iata: str) -> Optional[dict[str, float]]:
    """Load airline weights from calibration profile if available.

    Returns dict of IATA code → weight, or None if no profile found.
    """
    try:
        from src.calibration.profile import AirportProfileLoader
        from src.ingestion.callsign_reconciler import to_iata

        loader = AirportProfileLoader()
        icao = f"K{airport_iata}" if len(airport_iata) == 3 else airport_iata
        profile = loader.get_profile(icao)

        if not profile or not profile.airline_shares:
            return None

        # Convert ICAO codes to IATA codes
        weights: dict[str, float] = {}
        for icao_code, share in profile.airline_shares.items():
            iata_code = to_iata(f"{icao_code}100")
            if iata_code:
                iata_code = iata_code[:-3]  # Strip the "100" flight number
                weights[iata_code] = share
            else:
                weights[icao_code] = share

        return weights if weights else None
    except Exception:
        return None


def generate_flights(
    airport_iata: str,
    direction: Optional[str] = None,
    from_time: Optional[datetime] = None,
    to_time: Optional[datetime] = None,
    count: int = 30,
    seed: Optional[int] = None,
) -> list[FlightRecord]:
    """Generate FLIFO-shaped flight records for an airport.

    Args:
        airport_iata: Airport IATA code (e.g., "SFO")
        direction: "arrival" or "departure" or None (both)
        from_time: Window start (default: now - 2h)
        to_time: Window end (default: now + 4h)
        count: Number of flights to generate
        seed: Random seed for deterministic replay
    """
    now = datetime.now(timezone.utc)
    if from_time is None:
        from_time = now - timedelta(hours=2)
    if to_time is None:
        to_time = now + timedelta(hours=4)

    if seed is None:
        seed = hash(f"{airport_iata}:{now.date().isoformat()}")

    rng = random.Random(seed)

    # Use airport profile weights if available, otherwise hardcoded
    profile_weights = _load_airport_weights(airport_iata)
    if profile_weights:
        # Build airline list from profile — match against known airlines
        airline_list = []
        weight_list = []
        for airline in AIRLINES:
            w = profile_weights.get(airline["iata"], 0.0)
            if w > 0:
                airline_list.append(airline)
                weight_list.append(w)
        # Add remaining airlines at minimal weight for variety
        if airline_list:
            min_w = min(weight_list) * 0.1
            for airline in AIRLINES:
                if airline["iata"] not in profile_weights:
                    airline_list.append(airline)
                    weight_list.append(min_w)
        else:
            airline_list = AIRLINES
            weight_list = [a["weight"] for a in AIRLINES]
    else:
        airline_list = AIRLINES
        weight_list = [a["weight"] for a in AIRLINES]

    weights = weight_list

    records: list[FlightRecord] = []
    window_seconds = int((to_time - from_time).total_seconds())

    for _ in range(count):
        airline = rng.choices(airline_list, weights=weights, k=1)[0]
        flight_dir = direction or rng.choice(["arrival", "departure"])

        # Distribute flights with peak-hour weighting
        offset_seconds = rng.randint(0, window_seconds)
        scheduled = from_time + timedelta(seconds=offset_seconds)

        # Peak hour boost (6-9am, 4-7pm local — approximate UTC)
        hour = scheduled.hour
        if hour in range(6, 10) or hour in range(16, 20):
            if rng.random() < 0.3:
                scheduled = scheduled.replace(minute=rng.randint(0, 59))

        flight_number = _generate_flight_number(airline, rng)
        other_airport = _pick_destination(airline, airport_iata, flight_dir, rng)

        # Determine times
        minutes_to_scheduled = (scheduled - now).total_seconds() / 60
        status_code, status_desc, delay_min, delay_code = _pick_status_for_time(
            minutes_to_scheduled, flight_dir, rng
        )

        estimated = None
        actual = None
        if delay_min > 0:
            estimated = (scheduled + timedelta(minutes=delay_min)).strftime("%Y-%m-%dT%H:%M:%SZ")
        if status_code in ("AR", "DP", "LN", "BG", "AB", "OB"):
            actual_offset = rng.randint(-3, delay_min + 5) if delay_min else rng.randint(-3, 3)
            actual = (scheduled + timedelta(minutes=actual_offset)).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Gate/terminal/belt
        terminal = str(rng.randint(1, 4)) if rng.random() < 0.85 else None
        gate = f"{rng.choice('ABCDEFG')}{rng.randint(1, 60)}" if rng.random() < 0.80 else None
        belt = str(rng.randint(1, 12)) if (flight_dir == "arrival" and status_code in ("AR", "BG", "LN") and rng.random() < 0.7) else None

        # Aircraft
        aircraft_type = rng.choices(AIRCRAFT_TYPES, weights=[a["weight"] for a in AIRCRAFT_TYPES], k=1)[0]
        registration = _generate_registration(airline, rng)

        # Codeshares (20% of flights)
        codeshares: list[CodeshareInfo] = []
        if rng.random() < 0.20:
            cs_airline = rng.choice([a for a in AIRLINES if a["iata"] != airline["iata"]])
            cs_num = rng.randint(1000, 9999)
            codeshares.append(CodeshareInfo(
                flightNumber=f"{cs_airline['iata']}{cs_num}",
                airline={"iataCode": cs_airline["iata"]},
            ))

        # Flight duration estimate (for departure/arrival time calc)
        flight_duration_min = rng.randint(60, 720)

        scheduled_str = scheduled.strftime("%Y-%m-%dT%H:%M:%SZ")

        if flight_dir == "arrival":
            dep_time = (scheduled - timedelta(minutes=flight_duration_min)).strftime("%Y-%m-%dT%H:%M:%SZ")
            departure = AirportPoint(
                iataCode=other_airport,
                icaoCode=f"K{other_airport}" if len(other_airport) == 3 else other_airport,
                scheduledTime=dep_time,
            )
            arrival = AirportPoint(
                iataCode=airport_iata,
                icaoCode=f"K{airport_iata}" if len(airport_iata) == 3 else airport_iata,
                scheduledTime=scheduled_str,
                estimatedTime=estimated,
                actualTime=actual,
                terminal=terminal,
                gate=gate,
                baggageBelt=belt,
            )
        else:
            arr_time = (scheduled + timedelta(minutes=flight_duration_min)).strftime("%Y-%m-%dT%H:%M:%SZ")
            departure = AirportPoint(
                iataCode=airport_iata,
                icaoCode=f"K{airport_iata}" if len(airport_iata) == 3 else airport_iata,
                scheduledTime=scheduled_str,
                estimatedTime=estimated,
                actualTime=actual,
                terminal=terminal,
                gate=gate,
            )
            arrival = AirportPoint(
                iataCode=other_airport,
                icaoCode=f"K{other_airport}" if len(other_airport) == 3 else other_airport,
                scheduledTime=arr_time,
            )

        updated_at = (now - timedelta(minutes=rng.randint(1, 30))).strftime("%Y-%m-%dT%H:%M:%SZ")

        record = FlightRecord(
            flightNumber=flight_number,
            airline=AirlineInfo(iataCode=airline["iata"], icaoCode=airline["icao"], name=airline["name"]),
            departure=departure,
            arrival=arrival,
            statusCode=status_code,
            statusDescription=status_desc,
            delayMinutes=delay_min,
            delayCode=delay_code,
            aircraft=AircraftInfo(registration=registration, iataType=aircraft_type["iata"], icaoType=aircraft_type["icao"]),
            codeshares=codeshares,
            updatedAt=updated_at,
        )
        records.append(record)

    # Sort by scheduled time
    def _sort_key(r: FlightRecord) -> str:
        if direction == "arrival" or (direction is None and r.arrival.iataCode == airport_iata):
            return r.arrival.scheduledTime
        return r.departure.scheduledTime
    records.sort(key=_sort_key)

    return records
