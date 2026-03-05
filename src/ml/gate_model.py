"""Gate recommendation model for optimal gate assignment."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional


class GateStatus(Enum):
    """Status of an airport gate."""
    AVAILABLE = "available"
    OCCUPIED = "occupied"
    DELAYED = "delayed"
    MAINTENANCE = "maintenance"


@dataclass
class Gate:
    """Represents an airport gate."""
    gate_id: str  # e.g., "A1", "B3"
    terminal: str  # e.g., "A", "B"
    status: GateStatus = GateStatus.AVAILABLE
    current_flight: Optional[str] = None  # icao24 of current flight
    available_at: Optional[datetime] = None


@dataclass
class GateRecommendation:
    """Recommendation for a gate assignment."""
    gate_id: str
    score: float  # 0-1, higher is better
    reasons: List[str] = field(default_factory=list)
    estimated_taxi_time: int = 0  # minutes


class GateRecommender:
    """Recommends optimal gate assignments for incoming flights."""

    def __init__(self, gates: Optional[List[Gate]] = None):
        """
        Initialize the gate recommender.

        Args:
            gates: List of available gates. If None, creates default airport gates.
        """
        if gates is not None:
            self.gates = {g.gate_id: g for g in gates}
        else:
            self.gates = self._create_default_gates()

    def _create_default_gates(self) -> dict:
        """Create default airport gates."""
        gates = {}

        # Terminal A: A1-A5 (domestic)
        for i in range(1, 6):
            gate_id = f"A{i}"
            gates[gate_id] = Gate(
                gate_id=gate_id,
                terminal="A",
                status=GateStatus.AVAILABLE
            )

        # Terminal B: B1-B5 (international)
        for i in range(1, 6):
            gate_id = f"B{i}"
            gates[gate_id] = Gate(
                gate_id=gate_id,
                terminal="B",
                status=GateStatus.AVAILABLE
            )

        return gates

    def _score_gate(self, gate: Gate, flight: dict) -> float:
        """
        Score a gate for a given flight.

        Args:
            gate: The gate to score.
            flight: Flight data dict with icao24, callsign, etc.

        Returns:
            Score from 0-1, higher is better.
        """
        score = 0.0

        # Base score for availability (most important)
        if gate.status == GateStatus.AVAILABLE:
            score += 0.5
        elif gate.status == GateStatus.DELAYED:
            score += 0.2
        else:
            # Occupied or maintenance gates get very low score
            return 0.0

        # Terminal matching based on flight type
        callsign = flight.get("callsign", "")
        is_international = self._is_international_flight(callsign)

        if is_international and gate.terminal == "B":
            score += 0.25
        elif not is_international and gate.terminal == "A":
            score += 0.25
        else:
            score += 0.1  # Still usable, just not optimal

        # Prefer gates closer to runway (lower number = closer)
        try:
            gate_number = int(gate.gate_id[1:])
            proximity_score = (6 - gate_number) / 5 * 0.15
            score += max(0, proximity_score)
        except (ValueError, IndexError):
            score += 0.05  # Default if can't parse gate number

        # Factor in delay prediction (if available)
        delay_minutes = flight.get("delay_minutes", 0)
        if delay_minutes > 30:
            score -= 0.1
        elif delay_minutes > 0:
            score -= 0.05

        return min(1.0, max(0.0, score))

    def _is_international_flight(self, callsign: str) -> bool:
        """
        Determine if a flight is international based on callsign.

        Simple heuristic: non-US airline prefixes are international.
        """
        if not callsign:
            return False

        # Common US domestic airline prefixes
        domestic_prefixes = {
            "AAL", "UAL", "DAL", "SWA", "JBU", "NKS", "ASA", "FFT", "SKW"
        }

        prefix = callsign[:3].upper()
        return prefix not in domestic_prefixes

    def _generate_reasons(self, gate: Gate, flight: dict, score: float) -> List[str]:
        """Generate human-readable reasons for the recommendation."""
        reasons = []

        if gate.status == GateStatus.AVAILABLE:
            reasons.append("Gate is currently available")
        elif gate.status == GateStatus.DELAYED:
            reasons.append("Gate will be available soon")

        callsign = flight.get("callsign", "")
        is_international = self._is_international_flight(callsign)

        if is_international and gate.terminal == "B":
            reasons.append("International terminal matches flight type")
        elif not is_international and gate.terminal == "A":
            reasons.append("Domestic terminal matches flight type")

        try:
            gate_number = int(gate.gate_id[1:])
            if gate_number <= 2:
                reasons.append("Close to runway for quick turnaround")
        except (ValueError, IndexError):
            pass

        if score >= 0.8:
            reasons.append("Optimal gate assignment")
        elif score >= 0.6:
            reasons.append("Good gate assignment")

        return reasons

    def _estimate_taxi_time(self, gate: Gate) -> int:
        """Estimate taxi time to gate in minutes."""
        base_time = 5  # Base taxi time

        try:
            gate_number = int(gate.gate_id[1:])
            # Gates further from runway take longer
            additional_time = gate_number - 1
            return base_time + additional_time
        except (ValueError, IndexError):
            return base_time

    def recommend(self, flight: dict, top_k: int = 3) -> List[GateRecommendation]:
        """
        Recommend gates for a flight.

        Args:
            flight: Flight data dict with icao24, callsign, etc.
            top_k: Number of recommendations to return.

        Returns:
            List of GateRecommendation sorted by score (descending).
        """
        recommendations = []

        for gate in self.gates.values():
            score = self._score_gate(gate, flight)
            if score > 0:
                reasons = self._generate_reasons(gate, flight, score)
                taxi_time = self._estimate_taxi_time(gate)

                recommendations.append(GateRecommendation(
                    gate_id=gate.gate_id,
                    score=score,
                    reasons=reasons,
                    estimated_taxi_time=taxi_time
                ))

        # Sort by score descending
        recommendations.sort(key=lambda r: r.score, reverse=True)

        return recommendations[:top_k]

    def update_gate_status(
        self,
        gate_id: str,
        status: GateStatus,
        flight: Optional[str] = None
    ) -> None:
        """
        Update gate availability.

        Args:
            gate_id: ID of the gate to update.
            status: New status for the gate.
            flight: Optional icao24 of the flight at the gate.
        """
        if gate_id in self.gates:
            self.gates[gate_id].status = status
            self.gates[gate_id].current_flight = flight

            # Clear available_at if gate is now available
            if status == GateStatus.AVAILABLE:
                self.gates[gate_id].available_at = None

    def get_gate(self, gate_id: str) -> Optional[Gate]:
        """Get gate by ID."""
        return self.gates.get(gate_id)


# Default recommender instance
_default_recommender: Optional[GateRecommender] = None


def recommend_gate(flight: dict) -> GateRecommendation:
    """
    Convenience function returning top recommendation.

    Args:
        flight: Flight data dict with icao24, callsign, etc.

    Returns:
        Top GateRecommendation for the flight.
    """
    global _default_recommender

    if _default_recommender is None:
        _default_recommender = GateRecommender()

    recommendations = _default_recommender.recommend(flight, top_k=1)

    if recommendations:
        return recommendations[0]

    # Return a default recommendation if no gates available
    return GateRecommendation(
        gate_id="A1",
        score=0.0,
        reasons=["No gates currently available, assigned to overflow"],
        estimated_taxi_time=10
    )
