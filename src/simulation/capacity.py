"""Airport capacity manager — enforces throughput limits based on weather, runway config, and disruptions.

All airport geometry (runways, gates) is derived from OSM data or computed
from runway count. Nothing is hardcoded per airport IATA code.
"""

import logging
import re
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def parse_runway_heading(runway_name: str) -> int | None:
    """Parse heading from runway name. E.g. '28L' → 280, '09R' → 90, '34' → 340."""
    m = re.match(r"(\d{1,2})", runway_name)
    if m:
        return int(m.group(1)) * 10
    return None


def compute_reversal_pair(runway_name: str) -> str:
    """Compute reciprocal runway name. E.g. '28L' → '10R', '09R' → '27L', '34' → '16'."""
    m = re.match(r"(\d{1,2})([LRC]?)", runway_name)
    if not m:
        return runway_name
    num = int(m.group(1))
    suffix = m.group(2)
    recip_num = (num + 18) % 36
    if recip_num == 0:
        recip_num = 36
    # Opposite side: L↔R, C stays C
    recip_suffix = {"L": "R", "R": "L", "C": "C"}.get(suffix, "")
    return f"{recip_num:02d}{recip_suffix}"


def compute_base_rates(runway_count: int) -> tuple[int, int]:
    """Compute base AAR/ADR from runway count.

    Approximation based on FAA ASPM data:
    - 1 runway: ~30 arr/hr, ~25 dep/hr
    - 2 runways: ~60 arr/hr, ~55 dep/hr (parallel ops)
    - 3 runways: ~80 arr/hr, ~70 dep/hr
    - 4+ runways: ~90 arr/hr, ~80 dep/hr (diminishing returns)
    """
    if runway_count <= 0:
        return 30, 25
    if runway_count == 1:
        return 30, 25
    if runway_count == 2:
        return 60, 55
    if runway_count == 3:
        return 80, 70
    return 90, 80  # 4+


class CapacityManager:
    """Enforces airport throughput limits based on weather, runway config, and disruptions.

    All geometry is derived from the runways list passed at init time (which
    comes from OSM data). Base AAR/ADR are computed from runway count, not
    looked up per airport code.
    """

    def __init__(self, airport: str = "SFO", runways: list[str] | None = None) -> None:
        self.airport = airport
        rwy_list = runways or ["28L", "28R"]  # fallback for standalone sim
        self.all_runways = set(rwy_list)
        self.active_runways = set(self.all_runways)
        # Compute base rates from runway count
        self.base_aar, self.base_adr = compute_base_rates(len(self.all_runways))
        self.current_category = "VFR"  # VFR/MVFR/IFR/LIFR
        self.weather_multiplier = 1.0
        self.failed_gates: dict[str, datetime] = {}  # gate -> expires_at
        self.closed_runways: dict[str, datetime] = {}  # runway -> expires_at
        self.turnaround_multiplier = 1.0
        self.ground_stop = False
        self._recent_arrivals: list[datetime] = []
        self._recent_departures: list[datetime] = []
        # Temperature de-rating
        self._temperature_c: float | None = None
        self._temp_derate_factor: float = 1.0
        # Multi-stage: departure queue and taxiway congestion
        self._departure_queue: list[str] = []  # callsigns waiting
        self._departure_queue_delay_min: float = 0.0  # avg queue delay
        self._taxiway_congestion: float = 1.0  # 1.0 = normal, >1.0 = congested
        self._cascading_delay_pool: float = 0.0  # accumulated delay minutes to propagate
        # Curfew: list of (start_hour, start_min, end_hour, end_min, max_arr_per_hour)
        self._curfews: list[tuple[int, int, int, int, int]] = []
        # Wind-based runway config: runway heading → runway name pairs
        # e.g. {"28L": 280, "28R": 280, "10L": 100, "10R": 100} for SFO
        self._runway_headings: dict[str, int] = {}
        self._wind_direction: int | None = None
        self._runway_reversal_pairs: dict[str, str] = {}  # "28L" -> "10R", etc.

    def get_arrival_rate(self, sim_time: datetime) -> int:
        """Current max arrivals/hour based on weather + runway config + curfew."""
        curfew_max = self.curfew_max_arrivals(sim_time)
        if curfew_max is not None:
            return curfew_max
        base = self.base_aar
        runway_fraction = len(self.active_runways) / max(len(self.all_runways), 1)
        rate = base * runway_fraction * self.weather_multiplier
        return max(1, int(rate))

    def get_departure_rate(self, sim_time: datetime) -> int:
        """Current max departures/hour (includes temp de-rating + taxiway congestion)."""
        if self.ground_stop:
            return 0
        if self.is_curfew_active(sim_time):
            return 0  # No departures during curfew
        base = self.base_adr
        runway_fraction = len(self.active_runways) / max(len(self.all_runways), 1)
        rate = base * runway_fraction * self.weather_multiplier
        # Temperature de-rating (hot days reduce departure throughput)
        rate *= self._temp_derate_factor
        # Taxiway congestion penalty (gridlock slows departures)
        rate /= self._taxiway_congestion
        return max(1, int(rate))

    def _count_recent(self, timestamps: list[datetime], sim_time: datetime) -> int:
        """Count operations in the last 60 minutes."""
        cutoff = sim_time - timedelta(hours=1)
        return sum(1 for t in timestamps if t >= cutoff)

    def can_accept_arrival(self, sim_time: datetime) -> bool:
        """Has arrival rate capacity for one more in the last hour?"""
        recent = self._count_recent(self._recent_arrivals, sim_time)
        return recent < self.get_arrival_rate(sim_time)

    def can_release_departure(self, sim_time: datetime) -> bool:
        """Has departure rate capacity?"""
        if self.ground_stop:
            return False
        if self.is_curfew_active(sim_time):
            return False
        recent = self._count_recent(self._recent_departures, sim_time)
        return recent < self.get_departure_rate(sim_time)

    def should_hold(self, sim_time: datetime) -> bool:
        """Approaching flights should enter holding pattern when at capacity."""
        return not self.can_accept_arrival(sim_time)

    def is_gate_available(self, gate: str, sim_time: datetime) -> bool:
        """Gate not failed/closed."""
        if gate in self.failed_gates:
            if sim_time >= self.failed_gates[gate]:
                del self.failed_gates[gate]
                return True
            return False
        return True

    def get_available_runways(self, sim_time: datetime) -> set[str]:
        """Get currently active (non-closed) runways."""
        return set(self.active_runways)

    # Weather types that impose extra capacity penalties beyond visibility/ceiling
    # (equipment damage risk, crew health, surface contamination, etc.)
    WEATHER_TYPE_PENALTY: dict[str, float] = {
        "sandstorm": 0.70,       # Engine ingestion risk, runway contamination
        "dust": 0.85,            # Reduced vis recovery, engine FOD risk
        "smoke": 0.80,           # Crew health, poor vis recovery
        "haze": 0.95,            # Mild — mostly a vis issue already captured
        "freezing_rain": 0.60,   # Deicing delays, surface contamination
        "ice_pellets": 0.70,     # Runway braking action, deicing
        "snow": 0.75,            # Plowing, deicing, braking
    }

    def apply_weather(
        self,
        visibility_nm: float | None,
        ceiling_ft: int | None,
        wind_gusts_kt: int | None = None,
        weather_type: str | None = None,
    ) -> None:
        """Recalculate flight category and weather multiplier from conditions."""
        vis = visibility_nm if visibility_nm is not None else 10.0
        ceil = ceiling_ft if ceiling_ft is not None else 10000

        if vis < 1.0 or ceil < 500:
            self.current_category = "LIFR"
            self.weather_multiplier = 0.30  # ~18 arr/hr
        elif vis < 3.0 or ceil < 1000:
            self.current_category = "IFR"
            self.weather_multiplier = 0.50  # ~30 arr/hr
        elif vis < 5.0 or ceil < 3000:
            self.current_category = "MVFR"
            self.weather_multiplier = 0.70  # ~42 arr/hr
        else:
            self.current_category = "VFR"
            self.weather_multiplier = 1.0

        # Store gusts for go-around probability
        self._wind_gusts_kt = wind_gusts_kt
        self._weather_type = weather_type

        # Wind gusts further reduce capacity
        if wind_gusts_kt and wind_gusts_kt > 35:
            self.weather_multiplier *= 0.80
        elif wind_gusts_kt and wind_gusts_kt > 25:
            self.weather_multiplier *= 0.90

        # Weather-type-specific penalty (sandstorm, smoke, etc.)
        if weather_type and weather_type in self.WEATHER_TYPE_PENALTY:
            self.weather_multiplier *= self.WEATHER_TYPE_PENALTY[weather_type]

        logger.info(
            "Weather update: category=%s, multiplier=%.2f (vis=%.1fnm, ceil=%dft%s%s)",
            self.current_category,
            self.weather_multiplier,
            vis,
            ceil,
            f", gusts={wind_gusts_kt}kt" if wind_gusts_kt else "",
            f", type={weather_type}" if weather_type else "",
        )

    def go_around_probability(self) -> float:
        """Weather-dependent go-around probability per approach attempt."""
        base = {"VFR": 0.005, "MVFR": 0.015, "IFR": 0.03, "LIFR": 0.05}
        prob = base.get(self.current_category, 0.005)
        gusts = getattr(self, '_wind_gusts_kt', None)
        if gusts:
            if gusts > 50:
                prob += 0.05
            elif gusts > 35:
                prob += 0.03
        if not self.active_runways:
            prob = 1.0
        return min(prob, 1.0)

    def configure_runway_reversal(self) -> None:
        """Derive runway headings and reversal pairs from runway names.

        Parses heading from the runway name (e.g. '28L' → 280°) and computes
        reciprocal runway names (e.g. '28L' → '10R'). Works for any airport
        worldwide — no hardcoded per-airport data needed.
        """
        for rwy in self.all_runways:
            heading = parse_runway_heading(rwy)
            if heading is not None:
                self._runway_headings[rwy] = heading
                self._runway_reversal_pairs[rwy] = compute_reversal_pair(rwy)

    def check_wind_reversal(self, wind_direction: int) -> None:
        """If wind has shifted >90° from runway heading, swap to reciprocal config."""
        if not self._runway_headings:
            return
        self._wind_direction = wind_direction

        # Get the primary runway heading (all runways in a config share the same heading)
        primary_heading = next(iter(self._runway_headings.values()), None)
        if primary_heading is None:
            return

        # Calculate angle difference
        diff = abs((wind_direction - primary_heading + 180) % 360 - 180)

        # Tailwind component > 10kt threshold: real-world is ~90° crosswind becomes issue
        # If wind is >90° off the runway heading, aircraft have a tailwind component
        if diff > 90:
            # Check if we're already on the reversed config
            current_names = set(self.active_runways)
            reversed_names = set(self._runway_reversal_pairs.values())
            if current_names & reversed_names:
                return  # Already reversed

            # Swap to reciprocal runways
            new_runways = set()
            new_headings = {}
            for rwy, reciprocal in self._runway_reversal_pairs.items():
                new_runways.add(reciprocal)
                new_headings[reciprocal] = (self._runway_headings[rwy] + 180) % 360
            # Update — preserve any closures on the new runway names
            old_active = set(self.active_runways)
            self.all_runways = new_runways
            self.active_runways = new_runways - set(self.closed_runways.keys())
            self._runway_headings = new_headings
            # Swap reversal pairs
            self._runway_reversal_pairs = {v: k for k, v in self._runway_reversal_pairs.items()}
            logger.info(
                "Wind reversal: %d° → runway config changed from %s to %s",
                wind_direction, old_active, self.active_runways,
            )

    def add_curfew(self, start: str, end: str, max_arrivals_per_hour: int = 2) -> None:
        """Add a curfew period (e.g. '23:00' to '06:00')."""
        sh, sm = map(int, start.split(":"))
        eh, em = map(int, end.split(":"))
        self._curfews.append((sh, sm, eh, em, max_arrivals_per_hour))
        logger.info("Curfew added: %s-%s (max %d arr/hr)", start, end, max_arrivals_per_hour)

    def is_curfew_active(self, sim_time: datetime) -> bool:
        """Check if any curfew is active at the given time."""
        h, m = sim_time.hour, sim_time.minute
        t = h * 60 + m
        for sh, sm, eh, em, _ in self._curfews:
            start = sh * 60 + sm
            end = eh * 60 + em
            if start > end:
                # Overnight curfew (e.g. 23:00 - 06:00)
                if t >= start or t < end:
                    return True
            else:
                if start <= t < end:
                    return True
        return False

    def curfew_max_arrivals(self, sim_time: datetime) -> int | None:
        """Return max arrivals/hr during curfew, or None if no curfew active."""
        h, m = sim_time.hour, sim_time.minute
        t = h * 60 + m
        for sh, sm, eh, em, max_arr in self._curfews:
            start = sh * 60 + sm
            end = eh * 60 + em
            if start > end:
                if t >= start or t < end:
                    return max_arr
            else:
                if start <= t < end:
                    return max_arr
        return None

    # --- Temperature de-rating ---

    def set_temperature(self, temp_c: float) -> None:
        """Set ambient temperature and compute de-rating factor.

        High temperatures reduce air density → longer takeoff rolls → reduced
        departure capacity. Real-world: Denver in summer loses ~10-15% capacity.
        """
        self._temperature_c = temp_c
        if temp_c > 45:
            self._temp_derate_factor = 0.75
        elif temp_c > 40:
            self._temp_derate_factor = 0.85
        elif temp_c > 35:
            self._temp_derate_factor = 0.90
        else:
            self._temp_derate_factor = 1.0
        if self._temp_derate_factor < 1.0:
            logger.info("Temperature %.1f°C → departure de-rate %.0f%%", temp_c, self._temp_derate_factor * 100)

    @property
    def temperature_c(self) -> float | None:
        return self._temperature_c

    # --- Multi-stage capacity: departure queue + taxiway congestion ---

    def update_departure_queue(self, queue_size: int) -> None:
        """Track departure queue size → compute average queue delay."""
        self._departure_queue_delay_min = max(0.0, (queue_size - 3) * 2.5)
        # Taxiway congestion scales with queue (>8 creates gridlock)
        if queue_size > 8:
            self._taxiway_congestion = 1.4
        elif queue_size > 5:
            self._taxiway_congestion = 1.2
        else:
            self._taxiway_congestion = 1.0

    @property
    def departure_queue_delay_min(self) -> float:
        return self._departure_queue_delay_min

    @property
    def taxiway_congestion(self) -> float:
        return self._taxiway_congestion

    def add_cascading_delay(self, delay_minutes: float) -> None:
        """Add delay to propagation pool (e.g. late inbound → delayed turnaround → delayed departure)."""
        self._cascading_delay_pool += delay_minutes

    def consume_cascading_delay(self) -> float:
        """Consume and return accumulated cascading delay for the next departure."""
        if self._cascading_delay_pool <= 0:
            return 0.0
        # Each flight absorbs a portion of the pool
        absorbed = min(self._cascading_delay_pool, 15.0)  # cap at 15 min per flight
        self._cascading_delay_pool = max(0, self._cascading_delay_pool - absorbed * 0.5)
        return absorbed

    def close_runway(self, runway: str, until: datetime) -> None:
        """Close a runway until the specified time."""
        self.closed_runways[runway] = until
        self.active_runways.discard(runway)
        logger.info("Runway %s closed until %s", runway, until.strftime("%H:%M"))

    def reopen_runway(self, runway: str) -> None:
        """Reopen a runway."""
        self.closed_runways.pop(runway, None)
        if runway in self.all_runways:
            self.active_runways.add(runway)
        logger.info("Runway %s reopened", runway)

    def fail_gate(self, gate: str, until: datetime) -> None:
        """Mark gate as failed until specified time."""
        self.failed_gates[gate] = until
        logger.info("Gate %s failed until %s", gate, until.strftime("%H:%M"))

    def set_ground_stop(self, active: bool) -> None:
        """Set or clear ground stop."""
        self.ground_stop = active
        logger.info("Ground stop: %s", "ACTIVE" if active else "cleared")

    def set_turnaround_multiplier(self, mult: float) -> None:
        """Set turnaround time multiplier (1.0 = normal)."""
        self.turnaround_multiplier = mult
        logger.info("Turnaround multiplier: %.1fx", mult)

    def record_arrival(self, sim_time: datetime) -> None:
        """Record an arrival for rate tracking."""
        self._recent_arrivals.append(sim_time)

    def record_departure(self, sim_time: datetime) -> None:
        """Record a departure for rate tracking."""
        self._recent_departures.append(sim_time)

    def update(self, sim_time: datetime) -> None:
        """Expire events whose duration has elapsed, clean up old tracking data."""
        # Expire runway closures
        for runway, until in list(self.closed_runways.items()):
            if sim_time >= until:
                self.reopen_runway(runway)

        # Expire gate failures
        for gate, until in list(self.failed_gates.items()):
            if sim_time >= until:
                del self.failed_gates[gate]
                logger.info("Gate %s failure expired", gate)

        # Prune old tracking data (keep last 2 hours)
        cutoff = sim_time - timedelta(hours=2)
        self._recent_arrivals = [t for t in self._recent_arrivals if t >= cutoff]
        self._recent_departures = [t for t in self._recent_departures if t >= cutoff]

    def status_summary(self, sim_time: datetime) -> str:
        """Return a short status string for progress display."""
        arr_rate = self.get_arrival_rate(sim_time)
        dep_rate = self.get_departure_rate(sim_time)
        parts = [f"{self.current_category}", f"AAR:{arr_rate}", f"ADR:{dep_rate}"]
        if self.ground_stop:
            parts.append("GND_STOP")
        if self.closed_runways:
            parts.append(f"RWY_CLOSED:{','.join(self.closed_runways.keys())}")
        if self.failed_gates:
            parts.append(f"GATES_FAILED:{len(self.failed_gates)}")
        if self.is_curfew_active(sim_time):
            parts.append("CURFEW")
        if self._temp_derate_factor < 1.0:
            parts.append(f"TEMP:{self._temperature_c:.0f}C")
        if self._departure_queue_delay_min > 0:
            parts.append(f"Q_DELAY:{self._departure_queue_delay_min:.0f}m")
        return " | ".join(parts)
