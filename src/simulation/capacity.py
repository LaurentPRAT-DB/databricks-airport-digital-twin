"""Airport capacity manager — enforces throughput limits based on weather, runway config, and disruptions."""

import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class CapacityManager:
    """Enforces airport throughput limits based on weather, runway config, and disruptions."""

    def __init__(self, airport: str = "SFO", runways: list[str] | None = None) -> None:
        self.airport = airport
        self.base_aar = 60  # arrivals/hour VMC (2 parallel runways)
        self.base_adr = 55  # departures/hour VMC
        self.all_runways = set(runways or ["28L", "28R"])
        self.active_runways = set(self.all_runways)
        self.current_category = "VFR"  # VFR/MVFR/IFR/LIFR
        self.weather_multiplier = 1.0
        self.failed_gates: dict[str, datetime] = {}  # gate -> expires_at
        self.closed_runways: dict[str, datetime] = {}  # runway -> expires_at
        self.turnaround_multiplier = 1.0
        self.ground_stop = False
        self._recent_arrivals: list[datetime] = []
        self._recent_departures: list[datetime] = []

    def get_arrival_rate(self, sim_time: datetime) -> int:
        """Current max arrivals/hour based on weather + runway config."""
        base = self.base_aar
        runway_fraction = len(self.active_runways) / max(len(self.all_runways), 1)
        rate = base * runway_fraction * self.weather_multiplier
        return max(1, int(rate))

    def get_departure_rate(self, sim_time: datetime) -> int:
        """Current max departures/hour."""
        if self.ground_stop:
            return 0
        base = self.base_adr
        runway_fraction = len(self.active_runways) / max(len(self.all_runways), 1)
        rate = base * runway_fraction * self.weather_multiplier
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

    def apply_weather(
        self,
        visibility_nm: float | None,
        ceiling_ft: int | None,
        wind_gusts_kt: int | None = None,
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

        # Wind gusts further reduce capacity
        if wind_gusts_kt and wind_gusts_kt > 35:
            self.weather_multiplier *= 0.80
        elif wind_gusts_kt and wind_gusts_kt > 25:
            self.weather_multiplier *= 0.90

        logger.info(
            "Weather update: category=%s, multiplier=%.2f (vis=%.1fnm, ceil=%dft%s)",
            self.current_category,
            self.weather_multiplier,
            vis,
            ceil,
            f", gusts={wind_gusts_kt}kt" if wind_gusts_kt else "",
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
        return " | ".join(parts)
