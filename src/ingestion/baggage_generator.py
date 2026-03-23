"""Synthetic baggage data generator for baggage handling system.

Generates realistic baggage data with:
- 1.2 bags per passenger average
- 82% aircraft load factor
- 15% connecting bags
- 2% misconnect rate
"""

import random
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional

# Aircraft capacity reference
AIRCRAFT_CAPACITY = {
    "A319": 140,
    "A320": 180,
    "A321": 220,
    "A330": 300,
    "A350": 350,
    "A380": 550,
    "B737": 160,
    "B738": 175,
    "B777": 380,
    "B787": 300,
    "E175": 76,
}

# Bag status progression with typical timing (minutes from check-in)
BAG_STATUS_TIMING = {
    "checked_in": 0,
    "security_screening": 5,
    "sorted": 15,
    "loaded": 35,
    "in_transit": 0,  # During flight
    "unloaded": 10,   # After arrival
    "on_carousel": 25,
    "claimed": 40,
}


def _get_aircraft_capacity(aircraft_type: str) -> int:
    """Get passenger capacity for aircraft type."""
    return AIRCRAFT_CAPACITY.get(aircraft_type, 180)


def _generate_bag_id(flight_number: str, index: int) -> str:
    """Generate a unique bag ID."""
    return f"{flight_number}-{index:04d}"


def _generate_passenger_name() -> str:
    """Generate anonymized passenger identifier."""
    first_names = ["A", "B", "C", "D", "E", "F", "G", "H", "J", "K", "L", "M", "N", "P", "R", "S", "T", "W"]
    last_names = [
        "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
        "Davis", "Rodriguez", "Martinez", "Anderson", "Taylor", "Thomas", "Lee"
    ]
    return f"{random.choice(first_names)}. {random.choice(last_names)}"


def _determine_bag_status(
    check_in_time: datetime,
    flight_time: datetime,
    is_arrival: bool,
    current_time: Optional[datetime] = None,
) -> str:
    """Determine bag status based on timing."""
    if current_time is None:
        current_time = datetime.now(timezone.utc)

    if is_arrival:
        # Arrival bag status
        minutes_since_arrival = (current_time - flight_time).total_seconds() / 60
        if minutes_since_arrival < 0:
            return "in_transit"
        elif minutes_since_arrival < 10:
            return "unloaded"
        elif minutes_since_arrival < 25:
            return "on_carousel"
        else:
            return "claimed"
    else:
        # Departure bag status
        minutes_to_departure = (flight_time - current_time).total_seconds() / 60
        if minutes_to_departure < 0:
            return "in_transit"
        elif minutes_to_departure < 15:
            return "loaded"
        elif minutes_to_departure < 30:
            return "sorted"
        elif minutes_to_departure < 60:
            return "security_screening"
        else:
            return "checked_in"


def generate_bags_for_flight(
    flight_number: str,
    aircraft_type: str = "A320",
    origin: str = "SFO",
    destination: str = "LAX",
    scheduled_time: Optional[datetime] = None,
    is_arrival: bool = True,
    load_factor: float = 0.82,
    bags_per_passenger: float = 1.2,
    connecting_rate: float = 0.15,
    misconnect_rate: float = 0.02,
) -> list[dict]:
    """
    Generate synthetic baggage for a flight.

    Args:
        flight_number: Flight number (e.g., UA123)
        aircraft_type: Aircraft type code
        origin: Origin airport
        destination: Destination airport
        scheduled_time: Scheduled arrival/departure time
        is_arrival: Whether this is an arrival (True) or departure (False)
        load_factor: Passenger load factor (0-1)
        bags_per_passenger: Average bags per passenger
        connecting_rate: Rate of connecting passengers
        misconnect_rate: Rate of misconnected bags

    Returns:
        List of bag dictionaries
    """
    if scheduled_time is None:
        scheduled_time = datetime.now(timezone.utc)

    capacity = _get_aircraft_capacity(aircraft_type)
    passenger_count = int(capacity * load_factor)
    bag_count = int(passenger_count * bags_per_passenger)

    # Use flight number as seed for reproducibility within same minute
    seed = int(hashlib.md5(
        f"{flight_number}-{scheduled_time.strftime('%Y%m%d%H%M')}".encode()
    ).hexdigest()[:8], 16)
    rng = random.Random(seed)

    bags = []
    current_time = datetime.now(timezone.utc)

    for i in range(bag_count):
        bag_id = _generate_bag_id(flight_number, i)

        # Determine if connecting
        is_connecting = rng.random() < connecting_rate

        # Determine if misconnect (only for connecting bags)
        is_misconnect = is_connecting and rng.random() < misconnect_rate

        # Check-in time (60-180 min before departure for departures)
        if not is_arrival:
            check_in_offset = timedelta(minutes=rng.randint(60, 180))
            check_in_time = scheduled_time - check_in_offset
        else:
            # For arrivals, check-in was at origin
            check_in_time = scheduled_time - timedelta(hours=rng.randint(3, 8))

        # Determine status
        if is_misconnect:
            status = "misconnect"
        else:
            status = _determine_bag_status(check_in_time, scheduled_time, is_arrival, current_time)

        # Connecting flight if applicable
        connecting_flight = None
        if is_connecting:
            conn_airlines = ["UA", "AA", "DL", "WN"]
            connecting_flight = f"{rng.choice(conn_airlines)}{rng.randint(100, 2999)}"

        # Carousel for arrivals
        carousel = None
        if is_arrival and status in ["on_carousel", "claimed"]:
            carousel = rng.randint(1, 8)

        bag = {
            "bag_id": bag_id,
            "flight_number": flight_number,
            "passenger_name": _generate_passenger_name(),
            "status": status,
            "is_connecting": is_connecting,
            "connecting_flight": connecting_flight,
            "origin": origin,
            "destination": destination,
            "check_in_time": check_in_time.isoformat(),
            "carousel": carousel,
        }
        bags.append(bag)

    return bags


def get_flight_baggage_stats(
    flight_number: str,
    aircraft_type: str = "A320",
    origin: str = "SFO",
    destination: str = "LAX",
    scheduled_time: Optional[datetime] = None,
    is_arrival: bool = True,
    flight_phase: Optional[str] = None,
) -> dict:
    """
    Get baggage statistics for a flight.

    Returns summary statistics without generating all individual bags.
    """
    if scheduled_time is None:
        scheduled_time = datetime.now(timezone.utc)

    # Non-baggage phases: aircraft not at gate, bags can't be processed
    # (B1 fix: baggage delivery only possible after aircraft arrives and unloads)
    _NON_BAGGAGE_PHASES = {
        "cruising", "descending", "climbing", "approaching", "enroute",
        "landing", "taxi_to_gate", "takeoff", "departing", "pushback",
        "taxi_to_runway",
    }
    if flight_phase and flight_phase.lower() in _NON_BAGGAGE_PHASES:
        capacity = _get_aircraft_capacity(aircraft_type)
        passenger_count = int(capacity * 0.82)
        bag_count = int(passenger_count * 1.2)
        connecting_count = int(bag_count * 0.15)
        return {
            "flight_number": flight_number,
            "total_bags": bag_count,
            "checked_in": 0,
            "loaded": bag_count,
            "unloaded": 0,
            "on_carousel": 0,
            "claimed": 0,
            "delivered": 0,
            "loading_progress_pct": 0,
            "connecting_bags": connecting_count,
            "misconnects": 0,
            "carousel": None,
        }

    bags = generate_bags_for_flight(
        flight_number=flight_number,
        aircraft_type=aircraft_type,
        origin=origin,
        destination=destination,
        scheduled_time=scheduled_time,
        is_arrival=is_arrival,
    )

    total = len(bags)
    status_counts = {}
    connecting_count = 0
    misconnects = 0

    for bag in bags:
        status = bag["status"]
        status_counts[status] = status_counts.get(status, 0) + 1
        if bag["is_connecting"]:
            connecting_count += 1
        if status == "misconnect":
            misconnects += 1

    # Calculate loading/unloading progress
    if is_arrival:
        # For arrivals: progress = bags that have been unloaded/on_carousel/claimed
        processed = (status_counts.get("unloaded", 0)
                     + status_counts.get("on_carousel", 0)
                     + status_counts.get("claimed", 0))
        loading_progress = int((processed / total) * 100) if total > 0 else 0
    else:
        loaded = status_counts.get("loaded", 0) + status_counts.get("in_transit", 0)
        loading_progress = int((loaded / total) * 100) if total > 0 else 0

    carousel = None
    if is_arrival:
        for bag in bags:
            if bag["carousel"]:
                carousel = bag["carousel"]
                break

    unloaded = status_counts.get("unloaded", 0)
    on_carousel = status_counts.get("on_carousel", 0)
    claimed = status_counts.get("claimed", 0)

    return {
        "flight_number": flight_number,
        "total_bags": total,
        "checked_in": status_counts.get("checked_in", 0),
        "loaded": status_counts.get("loaded", 0) + status_counts.get("in_transit", 0),
        "unloaded": unloaded,
        "on_carousel": on_carousel,
        "claimed": claimed,
        "delivered": unloaded + on_carousel + claimed,
        "loading_progress_pct": loading_progress,
        "connecting_bags": connecting_count,
        "misconnects": misconnects,
        "carousel": carousel,
    }


def generate_baggage_alerts(flight_numbers: list[str]) -> list[dict]:
    """
    Generate baggage alerts for flights with issues.

    Args:
        flight_numbers: List of flight numbers to check

    Returns:
        List of alert dictionaries
    """
    alerts = []
    alert_id = 1

    for flight_number in flight_numbers:
        # 5% chance of generating an alert per flight
        if random.random() < 0.05:
            alert_type = random.choice(["misconnect", "delayed_loading", "carousel_change"])

            if alert_type == "misconnect":
                message = f"Bag may miss connection - tight transfer time"
                bag_id = _generate_bag_id(flight_number, random.randint(1, 100))
                connecting = f"UA{random.randint(100, 999)}"
            elif alert_type == "delayed_loading":
                message = f"Baggage loading delayed - ground crew shortage"
                bag_id = _generate_bag_id(flight_number, 0)
                connecting = None
            else:
                message = f"Carousel changed from {random.randint(1, 4)} to {random.randint(5, 8)}"
                bag_id = _generate_bag_id(flight_number, 0)
                connecting = None

            alerts.append({
                "alert_id": f"ALERT-{alert_id:04d}",
                "alert_type": alert_type,
                "bag_id": bag_id,
                "flight_number": flight_number,
                "connecting_flight": connecting,
                "message": message,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "resolved": False,
            })
            alert_id += 1

    return alerts


def get_overall_baggage_stats() -> dict:
    """
    Get overall baggage handling statistics for the airport.

    Returns simulated daily statistics.
    """
    current_hour = datetime.now(timezone.utc).hour

    # Simulate daily bag count based on time
    base_daily = 15000
    if 6 <= current_hour < 12:
        progress = (current_hour - 6) / 6
    elif 12 <= current_hour < 18:
        progress = 0.5 + (current_hour - 12) / 12
    elif current_hour >= 18:
        progress = 0.8 + (current_hour - 18) / 30
    else:
        progress = current_hour / 30

    total_today = int(base_daily * progress)
    bags_in_system = random.randint(2500, 4000)
    connecting = random.randint(400, 800)
    misconnects = int(connecting * 0.02)

    return {
        "total_bags_today": total_today,
        "bags_in_system": bags_in_system,
        "loaded_departures": int(total_today * 0.45),
        "delivered_arrivals": int(total_today * 0.45),
        "connecting_bags": connecting,
        "misconnects": misconnects,
        "misconnect_rate_pct": round(misconnects / max(connecting, 1) * 100, 2),
        "avg_processing_time_min": random.randint(22, 28),
    }
