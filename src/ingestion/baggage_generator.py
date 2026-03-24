"""Synthetic baggage data generator for baggage handling system.

Generates realistic baggage data with:
- 1.2 bags per passenger average
- 82% aircraft load factor
- 15% connecting bags
- Misconnect rate derived from connection time vs MCT
- Lognormal timing distributions for realistic P50/P95 spread
"""

import math
import random
import hashlib
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

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

# Bag status progression — lognormal parameters (mu, sigma) in minutes.
# Each draw gives a realistic P50/P95 spread rather than fixed offsets.
# mu = ln(median), sigma controls tail weight.
BAG_TIMING_DISTRIBUTIONS = {
    # Departure: minutes from check-in to each status
    "security_screening": (math.log(5.0), 0.35),    # median 5 min, P95 ~8 min
    "sorted":            (math.log(15.0), 0.30),     # median 15 min, P95 ~23 min
    "loaded":            (math.log(35.0), 0.25),     # median 35 min, P95 ~50 min
    # Arrival: minutes after landing
    "unloaded":          (math.log(10.0), 0.30),     # median 10 min, P95 ~15 min
    "on_carousel":       (math.log(25.0), 0.25),     # median 25 min, P95 ~36 min
    "claimed":           (math.log(40.0), 0.20),     # median 40 min, P95 ~53 min
}

# Minimum Connection Time (MCT) in minutes by terminal pair type.
# Misconnect probability = sigmoid function of (MCT - actual_connection_time).
MCT_DOMESTIC = 45   # Same terminal
MCT_INTERNATIONAL = 90  # Cross terminal / customs

# BHS belt capacity
BHS_INJECTION_RATE = 30        # bags/min per injection belt
BHS_INJECTION_POINTS = 4       # parallel injection belts (scaled by gate count)
BHS_CAROUSEL_RATE = 25         # bags/min per carousel
BHS_CAROUSEL_COUNT = 8         # carousels (scaled by gate count)
BHS_SORT_TIME_MIN = 8          # median sort routing time (minutes)


def _sample_bag_timing(status: str, rng: random.Random) -> float:
    """Sample a bag processing time from lognormal distribution."""
    params = BAG_TIMING_DISTRIBUTIONS.get(status)
    if params is None:
        return 0.0
    mu, sigma = params
    return rng.lognormvariate(mu, sigma)


def _misconnect_probability(connection_time_min: float, mct_min: float) -> float:
    """Compute misconnect probability as sigmoid of (MCT - connection_time).

    P(miss) is ~50% when connection time is 35 min below MCT (very tight),
    drops to ~5% at MCT, and near-zero when connection time >> MCT.
    Overall population rate lands around 3-6% for realistic schedules.
    """
    margin = connection_time_min - mct_min  # positive = safe, negative = tight
    # Sigmoid centered at margin=-35: only very tight connections misconnect
    k = 0.15
    return 1.0 / (1.0 + math.exp(k * (margin + 35)))


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
    rng: Optional[random.Random] = None,
) -> str:
    """Determine bag status based on stochastic timing.

    Departure: uses minutes-to-departure with per-bag jitter on thresholds.
    Arrival: uses minutes-since-landing with per-bag jitter on thresholds.
    Each bag hits each stage at a slightly different time, producing
    realistic P50/P95 distributions while preserving ordering.
    """
    if current_time is None:
        current_time = datetime.now(timezone.utc)
    if rng is None:
        rng = random.Random()

    if is_arrival:
        # Arrival bag status — minutes since landing with per-bag jitter
        minutes_since_arrival = (current_time - flight_time).total_seconds() / 60
        if minutes_since_arrival < 0:
            return "in_transit"
        # Jitter: ±15% around nominal thresholds (preserves ordering)
        jitter = rng.uniform(0.85, 1.15)
        if minutes_since_arrival < 10 * jitter:
            return "unloaded"
        elif minutes_since_arrival < 25 * jitter:
            return "on_carousel"
        else:
            return "claimed"
    else:
        # Departure bag status — minutes to departure with per-bag jitter
        minutes_to_departure = (flight_time - current_time).total_seconds() / 60
        if minutes_to_departure < 0:
            return "in_transit"
        # Jitter: ±15% around nominal thresholds (preserves ordering)
        jitter = rng.uniform(0.85, 1.15)
        if minutes_to_departure < 15 * jitter:
            return "loaded"
        elif minutes_to_departure < 30 * jitter:
            return "sorted"
        elif minutes_to_departure < 60 * jitter:
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

        # Check-in time (60-180 min before departure for departures)
        if not is_arrival:
            check_in_offset = timedelta(minutes=rng.randint(60, 180))
            check_in_time = scheduled_time - check_in_offset
        else:
            # For arrivals, check-in was at origin
            check_in_time = scheduled_time - timedelta(hours=rng.randint(3, 8))

        # Connecting flight info
        connecting_flight = None
        connection_time_min = 0.0
        if is_connecting:
            conn_airlines = ["UA", "AA", "DL", "WN"]
            connecting_flight = f"{rng.choice(conn_airlines)}{rng.randint(100, 2999)}"
            # Connection time: 30-150 min window to next flight
            connection_time_min = rng.uniform(30, 150)

        # Determine if misconnect — MCT-based probability for connecting bags
        is_misconnect = False
        if is_connecting:
            mct = MCT_INTERNATIONAL if rng.random() < 0.25 else MCT_DOMESTIC
            p_miss = _misconnect_probability(connection_time_min, mct)
            is_misconnect = rng.random() < p_miss

        # Determine status
        if is_misconnect:
            status = "misconnect"
        else:
            status = _determine_bag_status(
                check_in_time, scheduled_time, is_arrival, current_time, rng
            )

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


# ---------------------------------------------------------------------------
# BHS Throughput Model (B02)
# ---------------------------------------------------------------------------

@dataclass
class BHSThroughputResult:
    """Results from BHS conveyor throughput simulation."""
    peak_throughput_bpm: float = 0.0      # bags per minute at peak
    total_injection_capacity_bpm: float = 0.0  # max injection rate
    jam_count: int = 0                     # times queue > 2x capacity
    max_queue_depth: int = 0               # peak queue at injection
    p95_processing_time_min: float = 0.0   # P95 sort-to-carousel time
    window_metrics: list[dict[str, Any]] = field(default_factory=list)


def _bhs_injection_points_from_gates(gate_count: int) -> int:
    """Scale BHS injection points by gate count (1 per ~10 gates, min 4)."""
    return max(BHS_INJECTION_POINTS, gate_count // 10)


def _bhs_carousels_from_gates(gate_count: int) -> int:
    """Scale BHS carousels by gate count (1 per ~5 gates, min 4)."""
    return max(4, min(BHS_CAROUSEL_COUNT, gate_count // 5))


def simulate_bhs_throughput(
    flights: list[dict[str, Any]],
    gate_count: int = 40,
    seed: int | None = None,
) -> BHSThroughputResult:
    """Simulate BHS throughput with conveyor capacity limits.

    Takes a list of flights with bag counts and scheduled times. Bins bags
    into 5-minute windows by injection time and computes throughput, queue
    depth, and jam events.

    Args:
        flights: list of dicts with keys:
            - flight_number, aircraft_type, scheduled_time (ISO str or datetime),
              flight_type ("arrival" or "departure")
        gate_count: airport gate count (for scaling injection points)
        seed: random seed for reproducibility

    Returns:
        BHSThroughputResult with throughput metrics
    """
    rng = random.Random(seed)
    injection_points = _bhs_injection_points_from_gates(gate_count)
    carousels = _bhs_carousels_from_gates(gate_count)

    injection_capacity_bpm = injection_points * BHS_INJECTION_RATE  # bags/min
    result = BHSThroughputResult(total_injection_capacity_bpm=injection_capacity_bpm)

    # Bin bags into 5-minute windows
    bag_bins: defaultdict[int, int] = defaultdict(int)  # bin_key → bag count

    for flight in flights:
        aircraft_type = flight.get("aircraft_type", "A320")
        capacity = _get_aircraft_capacity(aircraft_type)
        pax = int(capacity * 0.82)
        bag_count = int(pax * 1.2)

        sched = flight.get("scheduled_time")
        if isinstance(sched, str):
            sched = datetime.fromisoformat(sched)
        if sched is None:
            continue

        is_arrival = flight.get("flight_type") == "arrival"

        if is_arrival:
            # Arrival bags: unloaded 10–25 min after parking, then injected into BHS
            for _ in range(bag_count):
                offset = rng.lognormvariate(math.log(15), 0.3)
                inject_time = sched + timedelta(minutes=offset)
                bin_key = int(inject_time.timestamp() // 300)
                bag_bins[bin_key] += 1
        else:
            # Departure bags: checked in 60–180 min before, injected at check-in
            for _ in range(bag_count):
                offset = rng.uniform(60, 180)
                inject_time = sched - timedelta(minutes=offset)
                bin_key = int(inject_time.timestamp() // 300)
                bag_bins[bin_key] += 1

    if not bag_bins:
        return result

    # Process bins in order, applying capacity limits
    sorted_bins = sorted(bag_bins.keys())
    carry_over = 0
    processing_times: list[float] = []
    jam_capacity_threshold = injection_capacity_bpm * 5 * 2  # 2x 5-min capacity

    for bk in sorted_bins:
        arrivals = bag_bins[bk] + carry_over
        capacity_5min = int(injection_capacity_bpm * 5)  # 5-min capacity
        processed = min(arrivals, capacity_5min)
        carry_over = arrivals - processed

        throughput_bpm = processed / 5.0
        is_jam = carry_over > jam_capacity_threshold

        if is_jam:
            result.jam_count += 1

        result.max_queue_depth = max(result.max_queue_depth, carry_over)
        result.peak_throughput_bpm = max(result.peak_throughput_bpm, throughput_bpm)

        # Processing time = sort time + queue wait
        sort_time = rng.lognormvariate(math.log(BHS_SORT_TIME_MIN), 0.25)
        queue_wait = carry_over / max(1, injection_capacity_bpm)
        processing_times.append(sort_time + queue_wait)

        result.window_metrics.append({
            "bin_key": bk,
            "bags_arrived": bag_bins[bk],
            "bags_processed": processed,
            "queue_depth": carry_over,
            "throughput_bpm": round(throughput_bpm, 1),
            "jam": is_jam,
        })

    # P95 processing time
    if processing_times:
        sorted_times = sorted(processing_times)
        idx = min(int(len(sorted_times) * 0.95), len(sorted_times) - 1)
        result.p95_processing_time_min = sorted_times[idx]

    return result
