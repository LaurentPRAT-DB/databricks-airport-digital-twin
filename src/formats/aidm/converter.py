"""
AIDM to Internal Format Converter

Converts parsed AIDM documents to the internal flight models
used by the Airport Digital Twin.
"""

from datetime import datetime
from typing import Any, Optional

from src.formats.base import CoordinateConverter, GeoPosition
from src.formats.aidm.models import (
    AIDMDocument,
    AIDMFlight,
    AIDMFlightLeg,
    AIDMEventType,
    FlightType,
)


class AIDMConverter:
    """
    Converts AIDM models to internal flight format.

    Maps AIDM flights to FlightPosition and ScheduledFlight models
    used by the backend API and frontend visualization.
    """

    # Map AIDM status to internal flight status
    STATUS_MAP = {
        AIDMEventType.SCHEDULED: "scheduled",
        AIDMEventType.ESTIMATED: "en_route",
        AIDMEventType.ACTUAL: "en_route",
        AIDMEventType.BOARDING: "boarding",
        AIDMEventType.FINAL_CALL: "final_call",
        AIDMEventType.GATE_CLOSED: "gate_closed",
        AIDMEventType.DEPARTED: "departed",
        AIDMEventType.LANDED: "landed",
        AIDMEventType.ON_BLOCK: "at_gate",
        AIDMEventType.OFF_BLOCK: "taxiing",
        AIDMEventType.CANCELLED: "cancelled",
        AIDMEventType.DIVERTED: "diverted",
        AIDMEventType.DELAYED: "delayed",
    }

    def __init__(self, coord_converter: CoordinateConverter):
        """Initialize converter with coordinate transformer."""
        self.coord_converter = coord_converter

    def to_config(self, doc: AIDMDocument) -> dict[str, Any]:
        """
        Convert AIDM document to internal configuration.

        Args:
            doc: Parsed AIDM document

        Returns:
            Configuration with flights, scheduled_flights, and resources
        """
        config: dict[str, Any] = {
            "source": "AIDM",
            "version": doc.version,
            "airport": doc.airport.code if doc.airport else None,
            "timestamp": doc.timestamp.isoformat() if doc.timestamp else None,
            "flights": [],
            "scheduled_flights": [],
            "resources": [],
            "events": [],
        }

        for flight in doc.flights:
            # Convert to flight position (for live tracking)
            flight_pos = self._convert_to_flight_position(flight)
            if flight_pos:
                config["flights"].append(flight_pos)

            # Convert to scheduled flight (for FIDS display)
            scheduled = self._convert_to_scheduled_flight(flight)
            if scheduled:
                config["scheduled_flights"].append(scheduled)

        # Convert resources
        for resource in doc.resources:
            config["resources"].append({
                "type": resource.resource_type.value,
                "id": resource.resource_id,
                "terminal": resource.terminal,
                "start_time": resource.start_time.isoformat() if resource.start_time else None,
                "end_time": resource.end_time.isoformat() if resource.end_time else None,
            })

        # Convert events
        for event in doc.events:
            config["events"].append({
                "id": event.event_id,
                "type": event.event_type.value,
                "timestamp": event.timestamp.isoformat(),
                "description": event.description,
                "source": event.source,
            })

        # Convert gates
        for gate in doc.gates:
            config["resources"].append({
                "type": "GATE",
                "id": gate.gate_id,
                "terminal": gate.terminal,
                "gate_type": gate.gate_type,
                "position": gate.position,
            })

        return config

    def _convert_to_flight_position(self, flight: AIDMFlight) -> Optional[dict[str, Any]]:
        """Convert AIDM flight to FlightPosition format."""
        if not flight.legs:
            return None

        # Use last leg for arrivals, first leg for departures
        leg = flight.legs[-1] if flight.is_arrival else flight.legs[0]

        # Determine if arrival or departure
        is_arrival = flight.is_arrival

        # Get position estimate based on status
        position = self._estimate_position(flight, leg)
        if not position:
            return None

        return {
            "icao24": self._generate_icao24(flight),
            "callsign": flight.callsign,
            "latitude": position["latitude"],
            "longitude": position["longitude"],
            "altitude": position.get("altitude", 0),
            "velocity": position.get("velocity", 0),
            "heading": position.get("heading", 0),
            "vertical_rate": position.get("vertical_rate", 0),
            "on_ground": position.get("on_ground", False),
            "timestamp": int(datetime.utcnow().timestamp()),
            "origin": leg.departure_airport.code,
            "destination": leg.arrival_airport.code,
            "aircraft_type": flight.aircraft.aircraft_type if flight.aircraft else "A320",
            "registration": flight.aircraft.registration if flight.aircraft else None,
            "flight_phase": self._determine_phase(flight.status),
            "gate": flight.gate.gate_id if flight.gate else None,
            "status": self.STATUS_MAP.get(flight.status, "unknown"),
        }

    def _convert_to_scheduled_flight(self, flight: AIDMFlight) -> Optional[dict[str, Any]]:
        """Convert AIDM flight to ScheduledFlight format."""
        if not flight.legs:
            return None

        leg = flight.legs[0]

        return {
            "flight_number": flight.callsign,
            "airline": flight.flight_id.airline.code,
            "airline_name": flight.flight_id.airline.name,
            "origin": leg.departure_airport.code,
            "destination": leg.arrival_airport.code,
            "scheduled_time": (
                leg.scheduled_departure.isoformat()
                if leg.scheduled_departure else
                leg.scheduled_arrival.isoformat()
                if leg.scheduled_arrival else None
            ),
            "estimated_time": (
                leg.estimated_departure.isoformat()
                if leg.estimated_departure else
                leg.estimated_arrival.isoformat()
                if leg.estimated_arrival else None
            ),
            "actual_time": (
                leg.actual_departure.isoformat()
                if leg.actual_departure else
                leg.actual_arrival.isoformat()
                if leg.actual_arrival else None
            ),
            "status": self.STATUS_MAP.get(flight.status, "scheduled"),
            "terminal": leg.departure_airport.terminal or leg.arrival_airport.terminal,
            "gate": flight.gate.gate_id if flight.gate else None,
            "aircraft_type": flight.aircraft.aircraft_type if flight.aircraft else None,
            "is_arrival": flight.is_arrival,
            "remarks": flight.remarks,
        }

    def _estimate_position(
        self,
        flight: AIDMFlight,
        leg: AIDMFlightLeg,
    ) -> Optional[dict[str, Any]]:
        """
        Estimate current position based on flight status and times.

        For real tracking, this would use ADS-B data. For AIDM imports,
        we estimate position based on scheduled times and status.
        """
        # Default to airport location
        airport_lat = self.coord_converter.reference_lat
        airport_lon = self.coord_converter.reference_lon

        status = flight.status

        if status in [AIDMEventType.ON_BLOCK, AIDMEventType.BOARDING,
                      AIDMEventType.FINAL_CALL, AIDMEventType.GATE_CLOSED]:
            # At gate
            return {
                "latitude": airport_lat,
                "longitude": airport_lon,
                "altitude": 0,
                "velocity": 0,
                "heading": 0,
                "on_ground": True,
            }

        elif status == AIDMEventType.OFF_BLOCK:
            # Taxiing
            return {
                "latitude": airport_lat + 0.002,
                "longitude": airport_lon + 0.002,
                "altitude": 0,
                "velocity": 15,  # ~30 knots taxi speed
                "heading": 280,  # Toward runway
                "on_ground": True,
            }

        elif status == AIDMEventType.DEPARTED:
            # Climbing out
            return {
                "latitude": airport_lat + 0.05,
                "longitude": airport_lon + 0.05,
                "altitude": 3000,
                "velocity": 250,
                "heading": 280,
                "vertical_rate": 2000,
                "on_ground": False,
            }

        elif status == AIDMEventType.LANDED:
            # On runway
            return {
                "latitude": airport_lat - 0.01,
                "longitude": airport_lon - 0.02,
                "altitude": 0,
                "velocity": 80,
                "heading": 280,
                "on_ground": True,
            }

        elif status in [AIDMEventType.ESTIMATED, AIDMEventType.ACTUAL]:
            # En route - estimate based on time
            return {
                "latitude": airport_lat + 0.3,
                "longitude": airport_lon + 0.3,
                "altitude": 35000,
                "velocity": 450,
                "heading": 250,
                "on_ground": False,
            }

        # Default: scheduled, not yet departed
        return None

    def _determine_phase(self, status: AIDMEventType) -> str:
        """Map AIDM status to flight phase."""
        phase_map = {
            AIDMEventType.SCHEDULED: "scheduled",
            AIDMEventType.BOARDING: "boarding",
            AIDMEventType.FINAL_CALL: "boarding",
            AIDMEventType.GATE_CLOSED: "pushback",
            AIDMEventType.OFF_BLOCK: "taxi_out",
            AIDMEventType.DEPARTED: "climb",
            AIDMEventType.ESTIMATED: "cruise",
            AIDMEventType.ACTUAL: "cruise",
            AIDMEventType.LANDED: "taxi_in",
            AIDMEventType.ON_BLOCK: "at_gate",
        }
        return phase_map.get(status, "unknown")

    def _generate_icao24(self, flight: AIDMFlight) -> str:
        """Generate a pseudo ICAO24 address from flight data."""
        # Create deterministic hash from flight ID
        flight_str = f"{flight.callsign}{flight.flight_id.operational_date}"
        hash_val = hash(flight_str) & 0xFFFFFF
        return f"{hash_val:06x}"


def merge_aidm_flights(
    existing_flights: list[dict[str, Any]],
    aidm_flights: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Merge AIDM flights with existing flight data.

    AIDM data provides authoritative schedule and status information,
    while existing data may have more accurate positions from ADS-B.

    Args:
        existing_flights: Current flights from ADS-B or other sources
        aidm_flights: Flights from AIDM import

    Returns:
        Merged flight list
    """
    # Index existing by callsign
    existing_by_callsign = {f["callsign"]: f for f in existing_flights}

    result = []

    for aidm_flight in aidm_flights:
        callsign = aidm_flight.get("callsign")
        existing = existing_by_callsign.get(callsign)

        if existing:
            # Merge: keep position from existing, update metadata from AIDM
            merged = existing.copy()
            merged["status"] = aidm_flight.get("status", existing.get("status"))
            merged["gate"] = aidm_flight.get("gate", existing.get("gate"))
            merged["origin"] = aidm_flight.get("origin", existing.get("origin"))
            merged["destination"] = aidm_flight.get("destination", existing.get("destination"))
            result.append(merged)
            del existing_by_callsign[callsign]
        else:
            # New flight from AIDM
            result.append(aidm_flight)

    # Add remaining existing flights not in AIDM
    result.extend(existing_by_callsign.values())

    return result
