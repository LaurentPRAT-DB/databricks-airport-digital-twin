"""
AIXM XML Parser

Parses AIXM 5.1.1 XML documents using defusedxml for security.
Extracts runways, taxiways, aprons, and navaids for airport visualization.

AIXM XML structure uses GML (Geography Markup Language) for geometry
and follows a time-sliced model for temporal data management.

Example AIXM structure:
<aixm:RunwayElement gml:id="RWY_01">
  <aixm:timeSlice>
    <aixm:RunwayElementTimeSlice>
      <aixm:designator>10L/28R</aixm:designator>
      <aixm:length uom="M">3048</aixm:length>
      ...
    </aixm:RunwayElementTimeSlice>
  </aixm:timeSlice>
</aixm:RunwayElement>
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Union
import re

import xml.etree.ElementTree as ElementTree

try:
    import defusedxml.ElementTree as ET
except ImportError:
    # Fall back to standard library with warning
    ET = ElementTree
    print("Warning: defusedxml not installed, using standard XML parser")

from src.formats.base import AirportFormatParser, CoordinateConverter, ParseError, ValidationError
from src.formats.aixm.models import (
    AIXMDocument,
    AIXMRunway,
    AIXMRunwayDirection,
    AIXMTaxiway,
    AIXMApron,
    AIXMNavaid,
    AIXMAirportHeliport,
    GMLPoint,
    GMLLineString,
    GMLPolygon,
    RunwaySurfaceType,
    NavaidType,
)


# AIXM XML namespaces
NAMESPACES = {
    "aixm": "http://www.aixm.aero/schema/5.1.1",
    "gml": "http://www.opengis.net/gml/3.2",
    "xlink": "http://www.w3.org/1999/xlink",
    "message": "http://www.aixm.aero/schema/5.1.1/message",
}


class AIXMParser(AirportFormatParser[AIXMDocument]):
    """
    Parser for AIXM 5.1.1 XML documents.

    Extracts aeronautical features from AIXM XML files and converts
    them to Pydantic models for further processing.
    """

    def parse(self, source: Union[str, Path, bytes]) -> AIXMDocument:
        """
        Parse AIXM XML from file path or raw bytes.

        Args:
            source: File path or XML content as bytes

        Returns:
            Parsed AIXMDocument

        Raises:
            ParseError: If XML parsing fails
        """
        try:
            if isinstance(source, bytes):
                root = ET.fromstring(source)
            elif isinstance(source, (str, Path)):
                tree = ET.parse(str(source))
                root = tree.getroot()
            else:
                raise ParseError(f"Unsupported source type: {type(source)}")

            return self._parse_document(root)

        except ET.ParseError as e:
            raise ParseError(f"XML parsing error: {e}") from e
        except Exception as e:
            raise ParseError(f"Failed to parse AIXM: {e}") from e

    def validate(self, model: AIXMDocument) -> list[str]:
        """
        Validate parsed AIXM document.

        Args:
            model: Parsed AIXMDocument

        Returns:
            List of validation warnings

        Raises:
            ValidationError: If critical validation errors found
        """
        warnings = []

        # Check for required elements
        if not model.runways and not model.taxiways and not model.aprons:
            warnings.append("No runways, taxiways, or aprons found in document")

        # Validate runway data
        for runway in model.runways:
            if runway.length <= 0:
                warnings.append(f"Runway {runway.designator}: Invalid length {runway.length}")
            if runway.width <= 0:
                warnings.append(f"Runway {runway.designator}: Invalid width {runway.width}")
            if not runway.centre_line:
                warnings.append(f"Runway {runway.designator}: Missing center line geometry")

        # Validate taxiway data
        for taxiway in model.taxiways:
            if not taxiway.centre_line and not taxiway.extent:
                warnings.append(f"Taxiway {taxiway.designator}: Missing geometry")

        return warnings

    def to_config(self, model: AIXMDocument) -> dict[str, Any]:
        """
        Convert AIXM document to internal airport configuration.

        Uses AIXMConverter for the actual conversion.
        """
        from src.formats.aixm.converter import AIXMConverter
        converter = AIXMConverter(self.converter)
        return converter.to_config(model)

    def _parse_document(self, root: ElementTree.Element) -> AIXMDocument:
        """Parse root element into AIXMDocument."""
        doc = AIXMDocument()

        # Parse airport/heliport
        for ah in root.findall(".//aixm:AirportHeliport", NAMESPACES):
            doc.airport = self._parse_airport(ah)
            break  # Take first one

        # Parse runways
        for rwy in root.findall(".//aixm:Runway", NAMESPACES):
            parsed = self._parse_runway(rwy)
            if parsed:
                doc.runways.append(parsed)

        # Parse taxiways
        for twy in root.findall(".//aixm:Taxiway", NAMESPACES):
            parsed = self._parse_taxiway(twy)
            if parsed:
                doc.taxiways.append(parsed)

        # Parse aprons
        for apron in root.findall(".//aixm:Apron", NAMESPACES):
            parsed = self._parse_apron(apron)
            if parsed:
                doc.aprons.append(parsed)

        # Parse navaids
        for navaid in root.findall(".//aixm:Navaid", NAMESPACES):
            parsed = self._parse_navaid(navaid)
            if parsed:
                doc.navaids.append(parsed)

        return doc

    def _parse_airport(self, elem: ElementTree.Element) -> Optional[AIXMAirportHeliport]:
        """Parse AirportHeliport element."""
        gml_id = elem.get(f"{{{NAMESPACES['gml']}}}id", "")

        # Get time slice data
        ts = elem.find(".//aixm:AirportHeliportTimeSlice", NAMESPACES)
        if ts is None:
            return None

        # Extract fields
        identifier = self._get_text(ts, "aixm:identifier") or gml_id
        icao = self._get_text(ts, "aixm:locationIndicatorICAO")
        iata = self._get_text(ts, "aixm:designatorIATA")
        name = self._get_text(ts, "aixm:name") or "Unknown Airport"

        # Parse ARP (Aerodrome Reference Point)
        arp = None
        arp_elem = ts.find(".//aixm:ARP//gml:pos", NAMESPACES)
        if arp_elem is not None and arp_elem.text:
            arp = GMLPoint(pos=arp_elem.text)

        elevation = self._get_float(ts, "aixm:fieldElevation")
        mag_var = self._get_float(ts, "aixm:magneticVariation")

        return AIXMAirportHeliport(
            gmlId=gml_id,
            identifier=identifier,
            icaoCode=icao,
            iataCode=iata,
            name=name,
            arp=arp,
            elevation=elevation,
            magneticVariation=mag_var,
        )

    def _parse_runway(self, elem: ElementTree.Element) -> Optional[AIXMRunway]:
        """Parse Runway element."""
        gml_id = elem.get(f"{{{NAMESPACES['gml']}}}id", "")

        ts = elem.find(".//aixm:RunwayTimeSlice", NAMESPACES)
        if ts is None:
            return None

        identifier = self._get_text(ts, "aixm:identifier") or gml_id
        designator = self._get_text(ts, "aixm:designator") or identifier
        length = self._get_float(ts, "aixm:nominalLength") or 0
        width = self._get_float(ts, "aixm:nominalWidth") or 45  # Default 45m

        # Parse surface type
        surface_type = None
        surface_text = self._get_text(ts, "aixm:surfaceComposition")
        if surface_text:
            try:
                surface_type = RunwaySurfaceType(surface_text)
            except ValueError:
                pass

        # Parse center line geometry
        centre_line = self._parse_linestring(ts, ".//aixm:centreLine//gml:posList")

        # Parse runway directions
        directions = []
        for rwy_dir in elem.findall(".//aixm:RunwayDirection", NAMESPACES):
            direction = self._parse_runway_direction(rwy_dir)
            if direction:
                directions.append(direction)

        return AIXMRunway(
            gmlId=gml_id,
            identifier=identifier,
            designator=designator,
            length=length,
            width=width,
            surfaceType=surface_type,
            centreLine=centre_line,
            directions=directions,
        )

    def _parse_runway_direction(self, elem: ElementTree.Element) -> Optional[AIXMRunwayDirection]:
        """Parse RunwayDirection element."""
        gml_id = elem.get(f"{{{NAMESPACES['gml']}}}id", "")

        ts = elem.find(".//aixm:RunwayDirectionTimeSlice", NAMESPACES)
        if ts is None:
            return None

        designator = self._get_text(ts, "aixm:designator") or ""
        true_bearing = self._get_float(ts, "aixm:trueBearing")
        mag_bearing = self._get_float(ts, "aixm:magneticBearing")

        # Parse threshold location
        threshold = None
        threshold_elem = ts.find(".//aixm:aiming//gml:pos", NAMESPACES)
        if threshold_elem is not None and threshold_elem.text:
            threshold = GMLPoint(pos=threshold_elem.text)

        elevation = self._get_float(ts, "aixm:elevation")

        return AIXMRunwayDirection(
            gmlId=gml_id,
            designator=designator,
            trueBearing=true_bearing,
            magneticBearing=mag_bearing,
            thresholdLocation=threshold,
            elevation=elevation,
        )

    def _parse_taxiway(self, elem: ElementTree.Element) -> Optional[AIXMTaxiway]:
        """Parse Taxiway element."""
        gml_id = elem.get(f"{{{NAMESPACES['gml']}}}id", "")

        ts = elem.find(".//aixm:TaxiwayTimeSlice", NAMESPACES)
        if ts is None:
            return None

        identifier = self._get_text(ts, "aixm:identifier") or gml_id
        designator = self._get_text(ts, "aixm:designator") or identifier
        width = self._get_float(ts, "aixm:width")

        # Parse geometry
        centre_line = self._parse_linestring(ts, ".//aixm:centreLine//gml:posList")
        extent = self._parse_polygon(ts, ".//aixm:extent//gml:posList")

        return AIXMTaxiway(
            gmlId=gml_id,
            identifier=identifier,
            designator=designator,
            width=width,
            centreLine=centre_line,
            extent=extent,
        )

    def _parse_apron(self, elem: ElementTree.Element) -> Optional[AIXMApron]:
        """Parse Apron element."""
        gml_id = elem.get(f"{{{NAMESPACES['gml']}}}id", "")

        ts = elem.find(".//aixm:ApronTimeSlice", NAMESPACES)
        if ts is None:
            return None

        identifier = self._get_text(ts, "aixm:identifier") or gml_id
        name = self._get_text(ts, "aixm:name")

        # Parse geometry
        extent = self._parse_polygon(ts, ".//aixm:extent//gml:posList")

        return AIXMApron(
            gmlId=gml_id,
            identifier=identifier,
            name=name,
            extent=extent,
        )

    def _parse_navaid(self, elem: ElementTree.Element) -> Optional[AIXMNavaid]:
        """Parse Navaid element."""
        gml_id = elem.get(f"{{{NAMESPACES['gml']}}}id", "")

        ts = elem.find(".//aixm:NavaidTimeSlice", NAMESPACES)
        if ts is None:
            return None

        identifier = self._get_text(ts, "aixm:identifier") or gml_id
        designator = self._get_text(ts, "aixm:designator") or identifier
        name = self._get_text(ts, "aixm:name")

        # Parse type
        type_text = self._get_text(ts, "aixm:type") or "VOR"
        try:
            navaid_type = NavaidType(type_text)
        except ValueError:
            navaid_type = NavaidType.VOR

        # Parse location
        location = None
        loc_elem = ts.find(".//aixm:location//gml:pos", NAMESPACES)
        if loc_elem is not None and loc_elem.text:
            location = GMLPoint(pos=loc_elem.text)

        frequency = self._get_float(ts, "aixm:frequency")

        return AIXMNavaid(
            gmlId=gml_id,
            identifier=identifier,
            designator=designator,
            name=name,
            type=navaid_type,
            location=location,
            frequency=frequency,
        )

    def _get_text(self, elem: ElementTree.Element, path: str) -> Optional[str]:
        """Get text content of child element."""
        child = elem.find(path, NAMESPACES)
        return child.text.strip() if child is not None and child.text else None

    def _get_float(self, elem: ElementTree.Element, path: str) -> Optional[float]:
        """Get float value from child element."""
        text = self._get_text(elem, path)
        if text:
            try:
                return float(text)
            except ValueError:
                return None
        return None

    def _parse_linestring(self, elem: ElementTree.Element, path: str) -> Optional[GMLLineString]:
        """Parse GML LineString from element."""
        pos_list_elem = elem.find(path, NAMESPACES)
        if pos_list_elem is not None and pos_list_elem.text:
            return GMLLineString(posList=pos_list_elem.text.strip())
        return None

    def _parse_polygon(self, elem: ElementTree.Element, path: str) -> Optional[GMLPolygon]:
        """Parse GML Polygon from element."""
        linestring = self._parse_linestring(elem, path)
        if linestring:
            return GMLPolygon(exterior=linestring)
        return None
