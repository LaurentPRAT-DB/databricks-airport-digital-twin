"""Lightweight aggregate passenger flow model.

Passengers are modeled as cohorts per flight, flowing through a pipeline
of stages with stochastic timing. No spatial/2D pathfinding — just
queuing theory producing checkpoint throughput and terminal dwell metrics.

Pipeline stages (departure):
  1. Landside arrival — passengers arrive 60–180 min before departure
  2. Check-in — 30% use counter, rest online
  3. Security checkpoint — queue → screening (throughput-limited per lane)
  4. Airside dwell — time in terminal (shopping, lounge, gate area)
  5. Gate arrival — must arrive before boarding cutoff

Pipeline stages (arrival):
  1. Deplane — deboarding time from GSE model
  2. Terminal walk — to baggage claim or connection
  3. Baggage claim wait — aligned with baggage generator timing
  4. Landside exit — or transfer to connection
"""

import math
import random
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from src.ingestion.baggage_generator import AIRCRAFT_CAPACITY


# ---------------------------------------------------------------------------
# Parameters — all derived from aircraft capacity / gate count, not hardcoded
# per airport.
# ---------------------------------------------------------------------------

# Security checkpoint model
LANE_THROUGHPUT_PPH = 180          # passengers per lane per hour (TSA average)
ONLINE_CHECKIN_RATE = 0.70         # 70% skip counter check-in

# Dwell time — lognormal(mu, sigma) in minutes
DWELL_MU = math.log(45)           # median 45 min airside
DWELL_SIGMA = 0.4

# Arrival pipeline
TERMINAL_WALK_MIN = (3.0, 10.0)   # uniform range in minutes
BAGGAGE_CLAIM_WAIT_MIN = (10.0, 30.0)  # uniform range

# Departure arrival curve — lognormal for minutes-before-departure
ARRIVAL_MU = math.log(100)        # median ~100 min before departure
ARRIVAL_SIGMA = 0.35


def _security_lanes_from_gates(gate_count: int) -> int:
    """Derive number of security lanes from gate count (1 per ~8 gates, min 4)."""
    return max(4, gate_count // 8)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class PassengerEvent:
    """A single passenger flow event."""
    time: datetime
    flight_number: str
    flight_type: str        # "arrival" or "departure"
    stage: str              # checkpoint, dwell, deplane, etc.
    pax_count: int
    queue_length: int = 0
    wait_time_min: float = 0.0
    throughput_pph: float = 0.0
    dwell_time_min: float = 0.0


@dataclass
class PassengerFlowResult:
    """Aggregated results from the passenger flow model."""
    events: list[dict] = field(default_factory=list)

    # Checkpoint metrics
    checkpoint_throughput_pph: list[float] = field(default_factory=list)
    checkpoint_wait_p50_min: float = 0.0
    checkpoint_wait_p95_min: float = 0.0

    # Dwell metrics
    dwell_times_min: list[float] = field(default_factory=list)
    mean_dwell_min: float = 0.0
    dwell_stdev_min: float = 0.0


# ---------------------------------------------------------------------------
# Core model
# ---------------------------------------------------------------------------

class PassengerFlowModel:
    """Aggregate passenger flow simulation.

    Call ``process_departure()`` when a departure flight enters the schedule
    window (spawn_time - 180 min).  Call ``process_arrival()`` when a flight
    reaches PARKED.
    """

    def __init__(self, gate_count: int = 40, seed: int | None = None) -> None:
        self.gate_count = gate_count
        self.security_lanes = _security_lanes_from_gates(gate_count)
        self.max_throughput_pph = self.security_lanes * LANE_THROUGHPUT_PPH
        self.rng = random.Random(seed)

        # Running state — checkpoint queue (pax waiting per 5-min bin)
        self._queue: defaultdict[int, int] = defaultdict(int)  # bin_key → pax
        self._wait_times: list[float] = []
        self._throughputs: list[float] = []
        self._dwell_times: list[float] = []
        self._events: list[dict[str, Any]] = []

    # ---- helpers ----

    def _bin_key(self, t: datetime) -> int:
        """5-minute bin key (epoch minutes // 5)."""
        return int(t.timestamp() // 300)

    def _pax_count(self, aircraft_type: str, load_factor: float = 0.82) -> int:
        capacity = AIRCRAFT_CAPACITY.get(aircraft_type, 180)
        return int(capacity * load_factor)

    # ---- departure flow ----

    def process_departure(
        self,
        flight_number: str,
        aircraft_type: str,
        scheduled_departure: datetime,
    ) -> None:
        """Model departure passenger flow through checkpoint."""
        pax = self._pax_count(aircraft_type)

        # Passengers arrive following a lognormal curve before departure
        for _ in range(pax):
            mins_before = self.rng.lognormvariate(ARRIVAL_MU, ARRIVAL_SIGMA)
            arrival_time = scheduled_departure - timedelta(minutes=mins_before)

            # Counter check-in adds 5–15 min for 30% of passengers
            if self.rng.random() > ONLINE_CHECKIN_RATE:
                arrival_time += timedelta(minutes=self.rng.uniform(5, 15))

            # Enter security queue
            bin_k = self._bin_key(arrival_time)
            self._queue[bin_k] += 1

        # Process the queue bins touched by this flight's passengers
        # Compute throughput and wait for each 5-min window
        bins_touched = sorted(set(
            self._bin_key(scheduled_departure - timedelta(minutes=m))
            for m in range(0, 181, 5)
        ))

        carry_over = 0
        for bk in bins_touched:
            arrivals_in_bin = self._queue.pop(bk, 0) + carry_over
            capacity_in_bin = int(self.max_throughput_pph * 5 / 60)  # 5-min capacity
            processed = min(arrivals_in_bin, capacity_in_bin)
            carry_over = arrivals_in_bin - processed

            if processed > 0:
                throughput = processed * 12  # scale 5-min to hourly
                self._throughputs.append(throughput)

                # Wait time ~ queue_depth / throughput (Little's law approximation)
                queue_depth = carry_over
                wait_min = queue_depth / max(1, self.max_throughput_pph / 60)
                self._wait_times.append(wait_min)

                # Record event
                bin_time = datetime.fromtimestamp(bk * 300)
                self._events.append({
                    "time": bin_time.isoformat(),
                    "flight_number": flight_number,
                    "flight_type": "departure",
                    "stage": "checkpoint",
                    "pax_count": processed,
                    "queue_length": queue_depth,
                    "wait_time_min": round(wait_min, 1),
                    "throughput_pph": round(throughput, 0),
                })

        # Dwell time for this flight's passengers
        for _ in range(pax):
            dwell = self.rng.lognormvariate(DWELL_MU, DWELL_SIGMA)
            self._dwell_times.append(dwell)

        self._events.append({
            "time": scheduled_departure.isoformat(),
            "flight_number": flight_number,
            "flight_type": "departure",
            "stage": "dwell",
            "pax_count": pax,
            "dwell_time_min": round(
                sum(self._dwell_times[-pax:]) / pax, 1
            ) if pax > 0 else 0.0,
        })

    # ---- arrival flow ----

    def process_arrival(
        self,
        flight_number: str,
        aircraft_type: str,
        parked_time: datetime,
    ) -> None:
        """Model arrival passenger flow (deplane → walk → claim)."""
        pax = self._pax_count(aircraft_type)

        # Deboarding: 8–20 min depending on aircraft size
        capacity = AIRCRAFT_CAPACITY.get(aircraft_type, 180)
        if capacity > 250:
            deboard_min = self.rng.uniform(15, 20)
        else:
            deboard_min = self.rng.uniform(8, 14)

        self._events.append({
            "time": parked_time.isoformat(),
            "flight_number": flight_number,
            "flight_type": "arrival",
            "stage": "deplane",
            "pax_count": pax,
            "dwell_time_min": round(deboard_min, 1),
        })

        # Terminal walk
        walk_min = self.rng.uniform(*TERMINAL_WALK_MIN)

        # Baggage claim wait
        claim_min = self.rng.uniform(*BAGGAGE_CLAIM_WAIT_MIN)

        total_dwell = deboard_min + walk_min + claim_min
        self._dwell_times.append(total_dwell)

        self._events.append({
            "time": (parked_time + timedelta(minutes=deboard_min)).isoformat(),
            "flight_number": flight_number,
            "flight_type": "arrival",
            "stage": "dwell",
            "pax_count": pax,
            "dwell_time_min": round(total_dwell, 1),
        })

    # ---- results ----

    def get_results(self) -> PassengerFlowResult:
        """Compute aggregated results."""
        result = PassengerFlowResult(events=list(self._events))

        # Checkpoint metrics
        result.checkpoint_throughput_pph = list(self._throughputs)
        if self._wait_times:
            sorted_waits = sorted(self._wait_times)
            n = len(sorted_waits)
            result.checkpoint_wait_p50_min = sorted_waits[n // 2]
            result.checkpoint_wait_p95_min = sorted_waits[min(int(n * 0.95), n - 1)]

        # Dwell metrics
        result.dwell_times_min = list(self._dwell_times)
        if self._dwell_times:
            result.mean_dwell_min = sum(self._dwell_times) / len(self._dwell_times)
            if len(self._dwell_times) >= 2:
                mean = result.mean_dwell_min
                variance = sum((d - mean) ** 2 for d in self._dwell_times) / (len(self._dwell_times) - 1)
                result.dwell_stdev_min = variance ** 0.5

        return result
