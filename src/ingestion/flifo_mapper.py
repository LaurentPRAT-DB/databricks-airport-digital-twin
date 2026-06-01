"""Maps FLIFO API responses to internal schedule dict format."""

from typing import Optional

# FLIFO status code → internal FlightStatus enum value
_STATUS_MAP = {
    "SC": "scheduled",
    "ON": "on_time",
    "DL": "delayed",
    "BD": "boarding",
    "FC": "final_call",
    "GC": "gate_closed",
    "DP": "departed",
    "IA": "departed",
    "AB": "departed",
    "OB": "departed",
    "AR": "arrived",
    "LN": "arrived",
    "TX": "arrived",
    "BG": "arrived",
    "CX": "cancelled",
    "DV": "delayed",
    "GO": "scheduled",
    "FE": "scheduled",
    "NS": "scheduled",
    "CO": "scheduled",
    "CD": "gate_closed",
    "DE": "scheduled",
    "RE": "delayed",
    "RS": "delayed",
    "FI": "arrived",
    "NI": "scheduled",
    "FS": "cancelled",
    "AX": "cancelled",
}


def map_flifo_record(record: dict, airport_iata: str) -> dict:
    """Convert a single FLIFO flightRecord to internal schedule dict.

    The internal dict format matches what schedule_service._dict_to_scheduled_flight expects.
    """
    airline = record.get("airline", {})
    departure = record.get("departure", {})
    arrival = record.get("arrival", {})
    aircraft = record.get("aircraft", {})

    # Determine direction relative to our airport
    if arrival.get("iataCode", "").upper() == airport_iata.upper():
        flight_type = "arrival"
        scheduled_time = arrival.get("scheduledTime")
        estimated_time = arrival.get("estimatedTime")
        actual_time = arrival.get("actualTime")
        origin = departure.get("iataCode", "???")
        destination = arrival.get("iataCode", airport_iata)
        gate = arrival.get("gate")
        terminal = arrival.get("terminal")
        belt = arrival.get("baggageBelt")
    else:
        flight_type = "departure"
        scheduled_time = departure.get("scheduledTime")
        estimated_time = departure.get("estimatedTime")
        actual_time = departure.get("actualTime")
        origin = departure.get("iataCode", airport_iata)
        destination = arrival.get("iataCode", "???")
        gate = departure.get("gate")
        terminal = departure.get("terminal")
        belt = None

    status_code = record.get("statusCode", "SC")
    status = _STATUS_MAP.get(status_code, "scheduled")
    delay_minutes = record.get("delayMinutes", 0)
    delay_code = record.get("delayCode")

    codeshares = None
    raw_cs = record.get("codeshares")
    if raw_cs:
        codeshares = [cs.get("flightNumber") for cs in raw_cs if cs.get("flightNumber")]

    return {
        "flight_number": record.get("flightNumber", "???"),
        "airline": airline.get("name", "Unknown"),
        "airline_code": airline.get("icaoCode", airline.get("iataCode", "???")),
        "origin": origin,
        "destination": destination,
        "scheduled_time": scheduled_time,
        "estimated_time": estimated_time,
        "actual_time": actual_time,
        "gate": gate,
        "terminal": terminal,
        "stand": None,
        "belt": belt,
        "registration": aircraft.get("registration"),
        "codeshares": codeshares,
        "status": status,
        "delay_minutes": delay_minutes,
        "delay_reason": delay_code,
        "aircraft_type": aircraft.get("icaoType") or aircraft.get("iataType"),
        "flight_type": flight_type,
        "data_source": "flifo",
    }


def map_flifo_response(response: dict, airport_iata: str, direction: Optional[str] = None) -> list[dict]:
    """Convert full FLIFO API response to list of internal schedule dicts.

    Args:
        response: Raw FLIFO response with 'flightRecords' key
        airport_iata: Our airport code (to determine arrival vs departure)
        direction: Optional filter ("arrival" or "departure")
    """
    records = response.get("flightRecords", [])
    mapped = [map_flifo_record(r, airport_iata) for r in records]

    if direction:
        mapped = [f for f in mapped if f["flight_type"] == direction]

    return mapped
