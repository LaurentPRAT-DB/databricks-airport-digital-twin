"""Gate recommendation model for optimal gate assignment.

Uses OSM gate data for real airport configurations including:
- Actual gate positions and terminal assignments
- Airline operator assignments
- Multi-level terminal support
- Aircraft size compatibility (wide-body vs narrow-body gates)

When an AirportProfile is provided, airline market share data is used
to improve operator matching for airports where gate-airline affinity
is known from real data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, TYPE_CHECKING
import logging

if TYPE_CHECKING:
    from src.calibration.profile import AirportProfile

logger = logging.getLogger(__name__)


class GateStatus(Enum):
    """Status of an airport gate."""
    AVAILABLE = "available"
    OCCUPIED = "occupied"
    DELAYED = "delayed"
    MAINTENANCE = "maintenance"


class GateSize(Enum):
    """Gate size category for aircraft compatibility."""
    SMALL = "small"      # Regional jets (CRJ, E175)
    MEDIUM = "medium"    # Narrow-body (A320, B737)
    LARGE = "large"      # Wide-body (B777, A330, A350)
    SUPER = "super"      # Super heavy (A380, B747)


# Aircraft type to size mapping
AIRCRAFT_SIZE = {
    # Super heavy
    "A380": GateSize.SUPER,
    "B747": GateSize.SUPER,
    # Wide-body / Large
    "B777": GateSize.LARGE,
    "B787": GateSize.LARGE,
    "A330": GateSize.LARGE,
    "A340": GateSize.LARGE,
    "A350": GateSize.LARGE,
    "A345": GateSize.LARGE,
    # Narrow-body / Medium
    "A320": GateSize.MEDIUM,
    "A321": GateSize.MEDIUM,
    "A319": GateSize.MEDIUM,
    "A318": GateSize.MEDIUM,
    "B737": GateSize.MEDIUM,
    "B738": GateSize.MEDIUM,
    "B739": GateSize.MEDIUM,
    # Regional / Small
    "CRJ9": GateSize.SMALL,
    "E175": GateSize.SMALL,
    "E190": GateSize.SMALL,
}


@dataclass
class Gate:
    """Represents an airport gate with OSM-derived properties."""
    gate_id: str           # Reference from OSM (e.g., "A1", "G92")
    terminal: str          # Terminal name from OSM
    status: GateStatus = GateStatus.AVAILABLE
    current_flight: Optional[str] = None  # icao24 of current flight
    available_at: Optional[datetime] = None

    # OSM-derived properties
    name: Optional[str] = None           # Full gate name
    operator: Optional[str] = None       # Airline operator (e.g., "United Airlines")
    level: Optional[str] = None          # Floor level for multi-story terminals
    latitude: Optional[float] = None     # Geographic position
    longitude: Optional[float] = None
    osm_id: Optional[int] = None         # Original OSM node ID

    # Gate capability
    gate_size: GateSize = GateSize.MEDIUM  # Aircraft size this gate can handle
    is_international: bool = False         # International terminal gate

    @classmethod
    def from_osm_gate(cls, osm_gate: Dict[str, Any]) -> "Gate":
        """
        Create Gate from OSM gate configuration.

        Args:
            osm_gate: Gate dict from airport config (converted from OSM)

        Returns:
            Gate instance with OSM properties
        """
        gate_id = osm_gate.get("ref") or osm_gate.get("id", "")
        terminal = osm_gate.get("terminal") or ""

        geo = osm_gate.get("geo", {})

        # Determine gate size from terminal name heuristics
        # International terminals typically have larger gates
        terminal_lower = terminal.lower() if terminal else ""
        is_intl = "international" in terminal_lower or terminal_lower.startswith("g")

        # Gates in international terminals are typically larger
        gate_size = GateSize.LARGE if is_intl else GateSize.MEDIUM

        # Cast coordinates to float — Lakebase may return strings
        raw_lat = geo.get("latitude")
        raw_lon = geo.get("longitude")
        latitude = float(raw_lat) if raw_lat is not None else None
        longitude = float(raw_lon) if raw_lon is not None else None

        return cls(
            gate_id=str(gate_id),
            terminal=terminal,
            name=osm_gate.get("name"),
            operator=osm_gate.get("operator"),
            level=osm_gate.get("level"),
            latitude=latitude,
            longitude=longitude,
            osm_id=osm_gate.get("osmId"),
            gate_size=gate_size,
            is_international=is_intl,
        )


@dataclass
class GateRecommendation:
    """Recommendation for a gate assignment."""
    gate_id: str
    score: float  # 0-1, higher is better
    reasons: List[str] = field(default_factory=list)
    estimated_taxi_time: int = 0  # minutes


class GateRecommender:
    """Recommends optimal gate assignments for incoming flights.

    Uses OSM-derived gate data when available for accurate recommendations
    based on real airport layout, terminal assignments, and airline operators.
    """

    def __init__(
        self,
        airport_code: str = "KSFO",
        gates: Optional[List[Gate]] = None,
        airport_profile: Optional[AirportProfile] = None,
    ):
        """
        Initialize the gate recommender.

        Args:
            airport_code: ICAO airport code for this recommender instance.
            gates: List of available gates. If None, attempts to load from
                   airport config service (OSM data), falling back to defaults.
            airport_profile: Optional calibrated profile for airline-gate affinity
        """
        self.airport_code = airport_code
        self._profile = airport_profile
        self._runway_coords = self._load_runway_coords()
        if gates is not None:
            self.gates = {g.gate_id: g for g in gates}
            self._using_defaults = False
        else:
            osm_gates = self._load_osm_gates()
            if osm_gates:
                self.gates = osm_gates
                self._using_defaults = False
            else:
                self.gates = self._create_default_gates()
                self._using_defaults = True
            logger.info(f"GateRecommender initialized with {len(self.gates)} gates for {airport_code} (defaults={self._using_defaults})")

    def _load_runway_coords(self) -> tuple:
        """Load primary runway coordinates from OSM config.

        Returns:
            (lat, lon) tuple of the first runway centroid, or a default.
        """
        try:
            from app.backend.services.airport_config_service import (
                get_airport_config_service,
            )
            service = get_airport_config_service()
            config = service.get_config()
            osm_runways = config.get("osmRunways", [])
            if osm_runways:
                rw = osm_runways[0]
                geo_points = rw.get("geoPoints", [])
                if geo_points:
                    avg_lat = sum(p["latitude"] for p in geo_points) / len(geo_points)
                    avg_lon = sum(p["longitude"] for p in geo_points) / len(geo_points)
                    return (avg_lat, avg_lon)
        except Exception:
            pass
        # Fallback: SFO runway 28L
        return (37.6117, -122.3583)

    def _load_osm_gates(self) -> Optional[Dict[str, Gate]]:
        """
        Load gates from OSM data via airport config service.

        Returns:
            Dictionary of gate_id to Gate, or None if not available
        """
        try:
            from app.backend.services.airport_config_service import (
                get_airport_config_service,
            )

            service = get_airport_config_service()
            config = service.get_config()
            osm_gates = config.get("gates", [])

            if not osm_gates:
                logger.debug("No OSM gates found in airport config")
                return None

            gates = {}
            for osm_gate in osm_gates:
                gate = Gate.from_osm_gate(osm_gate)
                if gate.gate_id:
                    gates[gate.gate_id] = gate

            if gates:
                logger.info(f"Loaded {len(gates)} gates from OSM data")
                # Log terminal distribution
                terminals = {}
                for g in gates.values():
                    t = g.terminal or "Unknown"
                    terminals[t] = terminals.get(t, 0) + 1
                logger.debug(f"Gate distribution by terminal: {terminals}")

            return gates if gates else None

        except ImportError:
            logger.debug("Airport config service not available")
            return None
        except Exception as e:
            logger.warning(f"Failed to load OSM gates: {e}")
            return None

    def _create_default_gates(self) -> Dict[str, Gate]:
        """Create default airport gates (fallback when no OSM data)."""
        logger.info("Using default gate configuration (no OSM data)")
        gates = {}

        # Terminal A: A1-A5 (domestic, medium size)
        for i in range(1, 6):
            gate_id = f"A{i}"
            gates[gate_id] = Gate(
                gate_id=gate_id,
                terminal="Domestic Terminal A",
                gate_size=GateSize.MEDIUM,
                is_international=False,
            )

        # Terminal B: B1-B5 (international, large size)
        for i in range(1, 6):
            gate_id = f"B{i}"
            gates[gate_id] = Gate(
                gate_id=gate_id,
                terminal="International Terminal B",
                gate_size=GateSize.LARGE,
                is_international=True,
            )

        return gates

    def reload_gates(self) -> int:
        """
        Reload gates from OSM data.

        Call this after importing new OSM data to refresh gate information.

        Returns:
            Number of gates loaded
        """
        new_gates = self._load_osm_gates()
        if new_gates:
            self.gates = new_gates
            self._using_defaults = False
        return len(self.gates)

    def _score_gate(self, gate: Gate, flight: dict) -> float:
        """
        Score a gate for a given flight using OSM-derived properties.

        Scoring factors:
        1. Availability (40%): Gate must be available
        2. Operator match (20%): Prefer gates assigned to the airline
        3. Terminal type (15%): Match international/domestic
        4. Aircraft size (15%): Gate must handle aircraft size
        5. Proximity bonus (10%): Lower gate numbers preferred

        Args:
            gate: The gate to score (with OSM properties).
            flight: Flight data dict with icao24, callsign, aircraft_type, etc.

        Returns:
            Score from 0-1, higher is better.
        """
        score = 0.0

        # 1. Availability check (40% weight) - most important
        if gate.status == GateStatus.AVAILABLE:
            score += 0.40
        elif gate.status == GateStatus.DELAYED:
            score += 0.15
        else:
            # Occupied or maintenance gates are not usable
            return 0.0

        callsign = flight.get("callsign", "")
        aircraft_type = flight.get("aircraft_type", "")
        airline_code = callsign[:3].upper() if len(callsign) >= 3 else ""

        # 2. Operator matching (20% weight) - OSM gates have operator info
        if gate.operator:
            operator_lower = gate.operator.lower()
            # Check if airline matches gate operator
            if self._airline_matches_operator(airline_code, operator_lower):
                score += 0.20
            else:
                score += 0.05  # Small penalty for non-matching operator

        elif self._profile and airline_code:
            # No OSM operator, but profile has airline shares — use affinity
            # Dominant airlines get a slight bonus (they'd occupy more gates)
            share = self._profile.airline_shares.get(airline_code, 0.0)
            # Scale: 0% share → 0.08, 50% share → 0.16
            score += 0.08 + min(share, 0.5) * 0.16
        else:
            # No operator assigned - neutral score
            score += 0.10

        # 3. Terminal type matching (15% weight)
        # If profile has domestic routes, check against known domestic destinations
        is_international = self._is_international_flight(callsign)
        if self._profile and not is_international:
            # Double-check: if airline is not in domestic shares at all,
            # it might be international
            intl_airlines = set(self._profile.international_route_shares.keys()) if self._profile.international_route_shares else set()
            if airline_code and airline_code not in self._profile.airline_shares and intl_airlines:
                is_international = True

        if is_international and gate.is_international:
            score += 0.15
        elif not is_international and not gate.is_international:
            score += 0.15
        else:
            # Mismatch but still usable (customs/immigration may apply)
            score += 0.05

        # 4. Aircraft size compatibility (15% weight)
        aircraft_size = self._get_aircraft_size(aircraft_type)
        size_score = self._score_size_compatibility(gate.gate_size, aircraft_size)
        score += size_score * 0.15

        # 5. Proximity bonus (10% weight)
        # Extract numeric portion for proximity estimate
        try:
            # Handle various gate ID formats (A1, G92, 1A, etc.)
            numeric_part = "".join(c for c in gate.gate_id if c.isdigit())
            if numeric_part:
                gate_number = int(numeric_part)
                # Normalize: lower numbers get higher scores
                proximity_score = max(0, 1.0 - (gate_number / 100))
                score += proximity_score * 0.10
        except (ValueError, IndexError):
            score += 0.05  # Default if can't parse

        # Penalty for delayed flights
        delay_minutes = flight.get("delay_minutes", 0)
        if delay_minutes > 30:
            score -= 0.05
        elif delay_minutes > 0:
            score -= 0.02

        return min(1.0, max(0.0, score))

    def _airline_matches_operator(self, airline_code: str, operator: str) -> bool:
        """Check if airline code matches gate operator name."""
        # Mapping of common airline codes to operator names
        airline_names = {
            "UAL": ["united", "ual"],
            "DAL": ["delta", "dal"],
            "AAL": ["american", "aal"],
            "SWA": ["southwest", "swa"],
            "JBU": ["jetblue", "jbu"],
            "ASA": ["alaska", "asa"],
            "UAE": ["emirates", "uae"],
            "AFR": ["air france", "afr"],
            "CPA": ["cathay", "cpa"],
            "ANA": ["ana", "all nippon"],
            "JAL": ["japan airlines", "jal"],
            "KAL": ["korean", "kal"],
            "SIA": ["singapore", "sia"],
            "QFA": ["qantas", "qfa"],
            "BAW": ["british", "baw"],
            "DLH": ["lufthansa", "dlh"],
        }

        if airline_code in airline_names:
            for name in airline_names[airline_code]:
                if name in operator:
                    return True
        return False

    def _get_aircraft_size(self, aircraft_type: str) -> GateSize:
        """Get aircraft size category from type code."""
        # Try exact match
        if aircraft_type in AIRCRAFT_SIZE:
            return AIRCRAFT_SIZE[aircraft_type]

        # Try partial match (e.g., "B737-800" -> "B737")
        for code, size in AIRCRAFT_SIZE.items():
            if aircraft_type.startswith(code):
                return size

        # Default to medium if unknown
        return GateSize.MEDIUM

    def _score_size_compatibility(
        self, gate_size: GateSize, aircraft_size: GateSize
    ) -> float:
        """
        Score gate/aircraft size compatibility.

        Returns 1.0 for perfect match, lower for over/undersized gates.
        """
        size_order = [GateSize.SMALL, GateSize.MEDIUM, GateSize.LARGE, GateSize.SUPER]
        gate_idx = size_order.index(gate_size)
        aircraft_idx = size_order.index(aircraft_size)

        # Gate too small - cannot use
        if gate_idx < aircraft_idx:
            return 0.0

        # Perfect match
        if gate_idx == aircraft_idx:
            return 1.0

        # Gate larger than needed (wasteful but works)
        # Penalty increases with size difference
        diff = gate_idx - aircraft_idx
        return max(0.3, 1.0 - (diff * 0.3))

    def _is_international_flight(self, callsign: str) -> bool:
        """
        Determine if a flight is international based on callsign and airport.

        For US airports (ICAO starting with K): non-US airline prefixes are international.
        For non-US airports: all non-local carriers are treated as international.
        """
        if not callsign:
            return False

        prefix = callsign[:3].upper()

        # US airport: domestic = US airline prefixes
        if self.airport_code.startswith("K"):
            domestic_prefixes = {
                "AAL", "UAL", "DAL", "SWA", "JBU", "NKS", "ASA", "FFT", "SKW"
            }
            return prefix not in domestic_prefixes

        # Country-specific domestic airline mappings by ICAO prefix
        country_domestic = {
            "O": {"UAE", "ETD", "FDB", "ABY", "AXB"},  # UAE (OMAA, OMDB, etc.)
            "EG": {"BAW", "EZY", "VIR", "TOM", "BEE"},  # UK
            "LF": {"AFR", "HOP", "TVF", "EJU"},  # France
            "ED": {"DLH", "EWG", "GWI"},  # Germany
            "RJ": {"RJA", "RJD"},  # Jordan
            "VH": {"AIC", "IGO", "SEJ"},  # India
        }

        # Find matching country prefix (try 2-char first, then 1-char)
        icao_2 = self.airport_code[:2]
        icao_1 = self.airport_code[:1]
        domestic = country_domestic.get(icao_2) or country_domestic.get(icao_1, set())

        # If we have a mapping, check it; otherwise treat all flights as international
        if domestic:
            return prefix not in domestic
        return True

    def _generate_reasons(self, gate: Gate, flight: dict, score: float) -> List[str]:
        """Generate human-readable reasons for the recommendation."""
        reasons = []

        # Availability
        if gate.status == GateStatus.AVAILABLE:
            reasons.append("Gate is currently available")
        elif gate.status == GateStatus.DELAYED:
            reasons.append("Gate will be available soon")

        callsign = flight.get("callsign", "")
        aircraft_type = flight.get("aircraft_type", "")
        airline_code = callsign[:3].upper() if len(callsign) >= 3 else ""
        is_international = self._is_international_flight(callsign)

        # Operator match (OSM data)
        if gate.operator:
            if self._airline_matches_operator(airline_code, gate.operator.lower()):
                reasons.append(f"Gate assigned to {gate.operator}")
            else:
                reasons.append(f"Gate operated by {gate.operator}")

        # Terminal match
        if gate.terminal:
            if is_international and gate.is_international:
                reasons.append(f"International gate in {gate.terminal}")
            elif not is_international and not gate.is_international:
                reasons.append(f"Domestic gate in {gate.terminal}")
            else:
                reasons.append(f"Located in {gate.terminal}")

        # Aircraft size compatibility
        if aircraft_type:
            aircraft_size = self._get_aircraft_size(aircraft_type)
            if gate.gate_size == aircraft_size:
                reasons.append(f"Optimal size for {aircraft_type}")
            elif gate.gate_size.value > aircraft_size.value:
                reasons.append(f"Can accommodate {aircraft_type}")

        # Level info (multi-story terminals)
        if gate.level:
            reasons.append(f"Level {gate.level}")

        # Quality assessment
        if score >= 0.85:
            reasons.append("Optimal gate assignment")
        elif score >= 0.70:
            reasons.append("Good gate assignment")
        elif score >= 0.50:
            reasons.append("Acceptable gate assignment")

        return reasons

    def _estimate_taxi_time(self, gate: Gate) -> int:
        """
        Estimate taxi time to gate in minutes.

        Uses geographic coordinates when available (OSM data) for more
        accurate estimates based on distance from runway.
        """
        base_time = 5  # Base taxi time

        # If we have coordinates, estimate based on distance from runway
        if gate.latitude and gate.longitude:
            runway_lat, runway_lon = self._runway_coords

            # Simple distance calculation (degrees to approximate minutes)
            lat_diff = abs(gate.latitude - runway_lat)
            lon_diff = abs(gate.longitude - runway_lon)
            distance = (lat_diff**2 + lon_diff**2) ** 0.5

            # Convert distance to taxi time (rough estimate)
            # ~0.01 degrees = ~1km = ~2 minutes taxi
            additional_time = int(distance * 200)
            return min(base_time + additional_time, 15)  # Cap at 15 minutes

        # Fallback: estimate from gate number
        try:
            numeric_part = "".join(c for c in gate.gate_id if c.isdigit())
            if numeric_part:
                gate_number = int(numeric_part)
                # Rough estimate: higher numbers = further from runway
                additional_time = min(gate_number // 10, 8)
                return base_time + additional_time
        except (ValueError, IndexError):
            pass

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
        # Lazy reload: if still using defaults, try OSM gates once more
        if self._using_defaults:
            osm_gates = self._load_osm_gates()
            if osm_gates:
                self.gates = osm_gates
                self._using_defaults = False
                self._runway_coords = self._load_runway_coords()
                logger.info(f"Lazy-loaded {len(osm_gates)} OSM gates for {self.airport_code}")

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


def get_gate_recommender() -> GateRecommender:
    """
    Get the gate recommender singleton.

    Automatically loads OSM gates if available.

    Returns:
        GateRecommender instance
    """
    global _default_recommender

    if _default_recommender is None:
        _default_recommender = GateRecommender()

    return _default_recommender


def reload_gate_recommender() -> int:
    """
    Reload the gate recommender with fresh OSM data.

    Call this after importing new OSM airport data to refresh
    the gate configuration used for recommendations.

    Returns:
        Number of gates loaded
    """
    global _default_recommender

    if _default_recommender is None:
        _default_recommender = GateRecommender()
    else:
        _default_recommender.reload_gates()

    return len(_default_recommender.gates)


def recommend_gate(flight: dict) -> GateRecommendation:
    """
    Convenience function returning top recommendation.

    Args:
        flight: Flight data dict with icao24, callsign, aircraft_type, etc.

    Returns:
        Top GateRecommendation for the flight.
    """
    recommender = get_gate_recommender()
    recommendations = recommender.recommend(flight, top_k=1)

    if recommendations:
        return recommendations[0]

    # Return a default recommendation if no gates available
    return GateRecommendation(
        gate_id="A1",
        score=0.0,
        reasons=["No gates currently available, assigned to overflow"],
        estimated_taxi_time=10
    )
