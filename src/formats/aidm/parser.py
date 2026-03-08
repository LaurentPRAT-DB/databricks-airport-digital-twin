"""
AIDM Parser

Parses IATA AIDM (Airport Industry Data Model) messages in JSON or XML format.
Extracts flight information, resource allocations, and operational events.

AIDM messages typically come from:
- A-CDM (Airport Collaborative Decision Making) systems
- AODB (Airport Operational Database)
- DCS (Departure Control System)
- BRS (Baggage Reconciliation System)
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Union
import logging

import xml.etree.ElementTree as ElementTree

try:
    import defusedxml.ElementTree as ET
except ImportError:
    ET = ElementTree

from src.formats.base import AirportFormatParser, CoordinateConverter, ParseError, ValidationError
from src.formats.aidm.models import (
    AIDMDocument,
    AIDMFlight,
    AIDMFlightId,
    AIDMFlightLeg,
    AIDMResource,
    AIDMResourceType,
    AIDMEvent,
    AIDMEventType,
    AIDMGate,
    AIDMBaggageClaim,
    AIDMCheckIn,
    AIDMAirport,
    AIDMAirline,
    AIDMAircraft,
    FlightType,
    FlightServiceType,
)

logger = logging.getLogger(__name__)


# XML namespaces for AIDM
AIDM_NAMESPACES = {
    "aidm": "http://www.iata.org/AIDM/12.0",
    "aidx": "http://www.iata.org/IATA/PADIS/2003/05/AIDX",
}


class AIDMParser(AirportFormatParser[AIDMDocument]):
    """
    Parser for AIDM messages.

    Supports both JSON and XML formats commonly used for AIDM data exchange.
    """

    def __init__(
        self,
        converter: CoordinateConverter | None = None,
        local_airport: str = "SFO",
    ):
        """
        Initialize AIDM parser.

        Args:
            converter: Coordinate converter for geo transforms
            local_airport: Local airport IATA code for context
        """
        super().__init__(converter)
        self.local_airport = local_airport

    def parse(self, source: Union[str, Path, bytes]) -> AIDMDocument:
        """
        Parse AIDM data from file or content.

        Auto-detects JSON vs XML format.

        Args:
            source: File path, JSON string, XML string, or raw bytes

        Returns:
            Parsed AIDMDocument

        Raises:
            ParseError: If parsing fails
        """
        try:
            # Handle different source types
            if isinstance(source, bytes):
                content = source.decode("utf-8")
            elif isinstance(source, Path):
                content = source.read_text()
            elif isinstance(source, str):
                # Check if it looks like a file path (short, no JSON/XML markers)
                # and actually exists on disk
                is_file = (
                    len(source) < 1000 and
                    not source.strip().startswith("{") and
                    not source.strip().startswith("[") and
                    not source.strip().startswith("<") and
                    Path(source).exists()
                )
                if is_file:
                    content = Path(source).read_text()
                else:
                    content = source
            else:
                raise ParseError(f"Unsupported source type: {type(source)}")

            # Detect format
            content = content.strip()
            if content.startswith("{") or content.startswith("["):
                return self._parse_json(content)
            elif content.startswith("<"):
                return self._parse_xml(content)
            else:
                raise ParseError("Unable to detect format (expected JSON or XML)")

        except json.JSONDecodeError as e:
            raise ParseError(f"JSON parsing error: {e}") from e
        except ET.ParseError as e:
            raise ParseError(f"XML parsing error: {e}") from e
        except Exception as e:
            raise ParseError(f"Failed to parse AIDM: {e}") from e

    def validate(self, model: AIDMDocument) -> list[str]:
        """
        Validate parsed AIDM document.

        Args:
            model: Parsed AIDMDocument

        Returns:
            List of validation warnings
        """
        warnings = []

        if not model.flights and not model.events:
            warnings.append("No flights or events found in AIDM data")

        for flight in model.flights:
            if not flight.legs:
                warnings.append(f"Flight {flight.callsign}: No legs defined")
            if not flight.aircraft:
                warnings.append(f"Flight {flight.callsign}: No aircraft information")

        return warnings

    def to_config(self, model: AIDMDocument) -> dict[str, Any]:
        """Convert AIDM document to internal configuration."""
        from src.formats.aidm.converter import AIDMConverter
        converter = AIDMConverter(self.converter)
        return converter.to_config(model)

    def _parse_json(self, content: str) -> AIDMDocument:
        """Parse JSON AIDM format."""
        data = json.loads(content)

        # Handle array or single document
        if isinstance(data, list):
            # Multiple flights
            doc = AIDMDocument(
                airport=AIDMAirport(code=self.local_airport),
                timestamp=datetime.utcnow(),
            )
            for item in data:
                if "flightId" in item or "FlightId" in item:
                    flight = self._parse_json_flight(item)
                    if flight:
                        doc.flights.append(flight)
                elif "eventId" in item or "EventId" in item:
                    event = self._parse_json_event(item)
                    if event:
                        doc.events.append(event)
            return doc
        else:
            # Check if it's a single flight object
            if "flightId" in data or "FlightId" in data:
                doc = AIDMDocument(
                    airport=AIDMAirport(code=self.local_airport),
                    timestamp=datetime.utcnow(),
                )
                flight = self._parse_json_flight(data)
                if flight:
                    doc.flights.append(flight)
                return doc
            # Otherwise it's a document
            return self._parse_json_document(data)

    def _parse_json_document(self, data: dict) -> AIDMDocument:
        """Parse a JSON AIDM document."""
        doc = AIDMDocument(
            version=data.get("version", "12.0"),
            timestamp=self._parse_datetime(data.get("timestamp")),
        )

        # Parse airport context
        if "airport" in data:
            doc.airport = AIDMAirport(
                code=data["airport"].get("code", self.local_airport),
            )

        # Parse flights
        flights_data = data.get("flights", data.get("Flights", []))
        for flight_data in flights_data:
            flight = self._parse_json_flight(flight_data)
            if flight:
                doc.flights.append(flight)

        # Parse resources
        resources_data = data.get("resources", data.get("Resources", []))
        for res_data in resources_data:
            resource = self._parse_json_resource(res_data)
            if resource:
                doc.resources.append(resource)

        # Parse events
        events_data = data.get("events", data.get("Events", []))
        for event_data in events_data:
            event = self._parse_json_event(event_data)
            if event:
                doc.events.append(event)

        # Parse gates
        gates_data = data.get("gates", data.get("Gates", []))
        for gate_data in gates_data:
            gate = self._parse_json_gate(gate_data)
            if gate:
                doc.gates.append(gate)

        return doc

    def _parse_json_flight(self, data: dict) -> Optional[AIDMFlight]:
        """Parse a single flight from JSON."""
        try:
            # Parse flight ID
            fid_data = data.get("flightId", data.get("FlightId", {}))
            airline_data = fid_data.get("airline", fid_data.get("Airline", {}))

            flight_id = AIDMFlightId(
                airline=AIDMAirline(
                    code=airline_data.get("code", airline_data.get("Code", "XX")),
                    name=airline_data.get("name"),
                ),
                flightNumber=fid_data.get("flightNumber", fid_data.get("FlightNumber", "0000")),
                suffix=fid_data.get("suffix"),
                operationalDate=self._parse_datetime(
                    fid_data.get("operationalDate", fid_data.get("OperationalDate"))
                ) or datetime.utcnow(),
            )

            flight = AIDMFlight(flightId=flight_id)

            # Parse flight type
            ft = data.get("flightType", data.get("FlightType"))
            if ft:
                try:
                    flight.flight_type = FlightType(ft)
                except ValueError:
                    pass

            # Parse aircraft
            aircraft_data = data.get("aircraft", data.get("Aircraft"))
            if aircraft_data:
                flight.aircraft = AIDMAircraft(
                    registration=aircraft_data.get("registration"),
                    aircraftType=aircraft_data.get("aircraftType", aircraft_data.get("AircraftType", "A320")),
                    icaoType=aircraft_data.get("icaoType"),
                )

            # Parse legs
            legs_data = data.get("legs", data.get("Legs", []))
            for i, leg_data in enumerate(legs_data):
                leg = self._parse_json_leg(leg_data, i + 1)
                if leg:
                    flight.legs.append(leg)

            # If no legs, create default leg from top-level data
            if not flight.legs:
                leg = self._create_leg_from_flight_data(data)
                if leg:
                    flight.legs.append(leg)

            # Parse gate
            gate_data = data.get("gate", data.get("Gate"))
            if gate_data:
                flight.gate = self._parse_json_gate(gate_data)

            # Parse status
            status = data.get("status", data.get("Status"))
            if status:
                try:
                    flight.status = AIDMEventType(status)
                except ValueError:
                    pass

            return flight

        except Exception as e:
            logger.warning(f"Failed to parse flight: {e}")
            return None

    def _parse_json_leg(self, data: dict, sequence: int) -> Optional[AIDMFlightLeg]:
        """Parse a flight leg from JSON."""
        try:
            dep_data = data.get("departureAirport", data.get("DepartureAirport", {}))
            arr_data = data.get("arrivalAirport", data.get("ArrivalAirport", {}))

            return AIDMFlightLeg(
                legId=data.get("legId", f"leg-{sequence}"),
                sequence=sequence,
                departureAirport=AIDMAirport(
                    code=dep_data.get("code", dep_data.get("Code", "XXX")),
                    terminal=dep_data.get("terminal"),
                ),
                arrivalAirport=AIDMAirport(
                    code=arr_data.get("code", arr_data.get("Code", "XXX")),
                    terminal=arr_data.get("terminal"),
                ),
                scheduledDeparture=self._parse_datetime(
                    data.get("scheduledDeparture", data.get("ScheduledDeparture"))
                ),
                estimatedDeparture=self._parse_datetime(
                    data.get("estimatedDeparture", data.get("EstimatedDeparture"))
                ),
                actualDeparture=self._parse_datetime(
                    data.get("actualDeparture", data.get("ActualDeparture"))
                ),
                scheduledArrival=self._parse_datetime(
                    data.get("scheduledArrival", data.get("ScheduledArrival"))
                ),
                estimatedArrival=self._parse_datetime(
                    data.get("estimatedArrival", data.get("EstimatedArrival"))
                ),
                actualArrival=self._parse_datetime(
                    data.get("actualArrival", data.get("ActualArrival"))
                ),
                runway=data.get("runway"),
                stand=data.get("stand"),
                cancelled=data.get("cancelled", False),
                diverted=data.get("diverted", False),
            )
        except Exception as e:
            logger.warning(f"Failed to parse leg: {e}")
            return None

    def _create_leg_from_flight_data(self, data: dict) -> Optional[AIDMFlightLeg]:
        """Create a leg from top-level flight data."""
        origin = data.get("origin", data.get("Origin"))
        destination = data.get("destination", data.get("Destination"))

        if not origin and not destination:
            return None

        return AIDMFlightLeg(
            legId="leg-1",
            sequence=1,
            departureAirport=AIDMAirport(code=origin or "XXX"),
            arrivalAirport=AIDMAirport(code=destination or "XXX"),
            scheduledDeparture=self._parse_datetime(
                data.get("scheduledDeparture", data.get("std"))
            ),
            scheduledArrival=self._parse_datetime(
                data.get("scheduledArrival", data.get("sta"))
            ),
        )

    def _parse_json_gate(self, data: dict) -> Optional[AIDMGate]:
        """Parse a gate from JSON."""
        gate_id = data.get("gateId", data.get("GateId", data.get("gate")))
        if not gate_id:
            return None

        return AIDMGate(
            gateId=str(gate_id),
            terminal=data.get("terminal", data.get("Terminal")),
            gateType=data.get("gateType", data.get("GateType")),
            position=data.get("position"),
        )

    def _parse_json_resource(self, data: dict) -> Optional[AIDMResource]:
        """Parse a resource from JSON."""
        try:
            res_type = data.get("resourceType", data.get("ResourceType", "GATE"))
            return AIDMResource(
                resourceType=AIDMResourceType(res_type),
                resourceId=data.get("resourceId", data.get("ResourceId", "")),
                terminal=data.get("terminal"),
                startTime=self._parse_datetime(data.get("startTime")),
                endTime=self._parse_datetime(data.get("endTime")),
            )
        except Exception as e:
            logger.warning(f"Failed to parse resource: {e}")
            return None

    def _parse_json_event(self, data: dict) -> Optional[AIDMEvent]:
        """Parse an event from JSON."""
        try:
            event_type = data.get("eventType", data.get("EventType", "SCHEDULED"))
            return AIDMEvent(
                eventId=data.get("eventId", data.get("EventId", "")),
                eventType=AIDMEventType(event_type),
                timestamp=self._parse_datetime(data.get("timestamp")) or datetime.utcnow(),
                description=data.get("description"),
                source=data.get("source"),
            )
        except Exception as e:
            logger.warning(f"Failed to parse event: {e}")
            return None

    def _parse_xml(self, content: str) -> AIDMDocument:
        """Parse XML AIDM format (AIDX/IATA standard)."""
        root = ET.fromstring(content)

        doc = AIDMDocument(
            airport=AIDMAirport(code=self.local_airport),
            timestamp=datetime.utcnow(),
        )

        # Parse flights (AIDX format)
        for flight_elem in root.findall(".//aidx:FlightLeg", AIDM_NAMESPACES):
            flight = self._parse_xml_flight(flight_elem)
            if flight:
                doc.flights.append(flight)

        # Fallback: try without namespace
        if not doc.flights:
            for flight_elem in root.findall(".//FlightLeg"):
                flight = self._parse_xml_flight(flight_elem)
                if flight:
                    doc.flights.append(flight)

        return doc

    def _parse_xml_flight(self, elem: ElementTree.Element) -> Optional[AIDMFlight]:
        """Parse flight from XML element."""
        try:
            # Get airline and flight number
            airline_elem = elem.find(".//Airline", AIDM_NAMESPACES) or elem.find(".//Airline")
            flight_num_elem = elem.find(".//FlightNumber", AIDM_NAMESPACES) or elem.find(".//FlightNumber")

            airline_code = "XX"
            if airline_elem is not None and airline_elem.text:
                airline_code = airline_elem.text.strip()

            flight_number = "0000"
            if flight_num_elem is not None and flight_num_elem.text:
                flight_number = flight_num_elem.text.strip()

            flight_id = AIDMFlightId(
                airline=AIDMAirline(code=airline_code),
                flightNumber=flight_number,
                operationalDate=datetime.utcnow(),
            )

            flight = AIDMFlight(flightId=flight_id)

            # Parse origin/destination
            origin_elem = elem.find(".//DepartureAirport") or elem.find(".//Origin")
            dest_elem = elem.find(".//ArrivalAirport") or elem.find(".//Destination")

            if origin_elem is not None or dest_elem is not None:
                leg = AIDMFlightLeg(
                    legId="leg-1",
                    sequence=1,
                    departureAirport=AIDMAirport(
                        code=origin_elem.text.strip() if origin_elem is not None and origin_elem.text else "XXX"
                    ),
                    arrivalAirport=AIDMAirport(
                        code=dest_elem.text.strip() if dest_elem is not None and dest_elem.text else "XXX"
                    ),
                )
                flight.legs.append(leg)

            return flight

        except Exception as e:
            logger.warning(f"Failed to parse XML flight: {e}")
            return None

    def _parse_datetime(self, value: Any) -> Optional[datetime]:
        """Parse datetime from various formats."""
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            # Try ISO format
            for fmt in [
                "%Y-%m-%dT%H:%M:%S.%fZ",
                "%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d",
            ]:
                try:
                    return datetime.strptime(value, fmt)
                except ValueError:
                    continue
        return None
