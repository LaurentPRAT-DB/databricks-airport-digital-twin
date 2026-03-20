"""
Microsoft Flight Simulator Scenery Parser

Parses MSFS airport scenery packages from XML files, compiled BGL files,
ZIP archives, or directories containing scenery files.

Supports two formats:
- XML source files: <FSData> with <Airport> elements
- Compiled BGL binaries: MSFS 2020 compiled scenery (magic 0x19920201)
"""

import logging
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Union

from src.formats.base import CoordinateConverter, ParseError, AirportFormatParser
from src.formats.msfs.bgl_parser import is_bgl, parse_bgl
from src.formats.msfs.models import (
    MSFSDocument,
    MSFSParkingSpot,
    MSFSTaxiPoint,
    MSFSTaxiPath,
    MSFSRunway,
    MSFSRunwayEnd,
    MSFSApron,
    MSFSApronVertex,
    ParkingType,
    TaxiPointType,
    TaxiPathType,
)

logger = logging.getLogger(__name__)


class MSFSParser(AirportFormatParser[MSFSDocument]):
    """
    Parser for Microsoft Flight Simulator airport scenery.

    Handles XML source files, compiled BGL binaries, ZIP archives,
    and directories. Auto-detects format by checking file content.
    """

    def parse(self, source: Union[str, Path, bytes], source_path: str = "") -> MSFSDocument:
        """
        Parse MSFS scenery data from file, ZIP, directory, or raw bytes.

        Auto-detects BGL vs XML vs ZIP format for binary data and files.

        Args:
            source: File path (XML, BGL, or ZIP), directory path, or raw bytes
            source_path: Optional original filename/path hint for ICAO extraction
                         (useful when source is raw bytes from an HTTP upload)

        Returns:
            Parsed MSFSDocument

        Raises:
            ParseError: If parsing fails
        """
        try:
            if isinstance(source, bytes):
                if is_bgl(source):
                    return self._parse_bgl_bytes(source, source_path=source_path)
                if self._is_zip_bytes(source):
                    return self._parse_zip_bytes(source, source_path=source_path)
                return self._parse_xml_bytes(source)

            path = Path(source) if isinstance(source, str) else source

            if path.is_dir():
                return self._parse_directory(path)
            elif path.suffix.lower() == ".zip":
                return self._parse_zip(path)
            elif path.suffix.lower() == ".bgl":
                return self._parse_bgl_file(path)
            elif path.suffix.lower() == ".xml":
                return self._parse_xml_file(path)
            else:
                # Try auto-detecting by reading first bytes
                if path.exists() and path.is_file():
                    with open(path, "rb") as f:
                        header = f.read(4)
                    if is_bgl(header):
                        return self._parse_bgl_file(path)
                return self._parse_xml_file(path)

        except ParseError:
            raise
        except ET.ParseError as e:
            raise ParseError(f"Invalid XML: {e}")
        except ValueError as e:
            raise ParseError(f"Invalid BGL: {e}")
        except Exception as e:
            raise ParseError(f"Failed to parse MSFS scenery: {e}")

    def _parse_bgl_bytes(self, data: bytes, source_path: str = "") -> MSFSDocument:
        """Parse raw BGL binary bytes."""
        return parse_bgl(data, source_path=source_path)

    @staticmethod
    def _is_zip_bytes(data: bytes) -> bool:
        """Check if data starts with ZIP magic (PK\\x03\\x04)."""
        return len(data) >= 4 and data[:4] == b"PK\x03\x04"

    def _parse_zip_bytes(self, data: bytes, source_path: str = "") -> MSFSDocument:
        """Parse a ZIP archive from raw bytes (in-memory)."""
        import io
        docs = []
        with zipfile.ZipFile(io.BytesIO(data), "r") as zf:
            # Try BGL files first (compiled scenery — most common)
            for name in zf.namelist():
                if name.lower().endswith(".bgl"):
                    try:
                        bgl_data = zf.read(name)
                        if is_bgl(bgl_data):
                            doc = parse_bgl(bgl_data, source_path=source_path)
                            if doc.parking_spots or doc.runways:
                                docs.append(doc)
                                logger.info(f"Parsed BGL from ZIP bytes: {name}")
                    except (ValueError, Exception) as e:
                        logger.debug(f"Skipping BGL in ZIP: {name}: {e}")

            # Then try XML files
            if not docs:
                for name in zf.namelist():
                    if name.lower().endswith(".xml"):
                        try:
                            xml_data = zf.read(name)
                            root = ET.fromstring(xml_data)
                            if root.tag == "FSData" and root.findall("Airport"):
                                docs.append(self._parse_fsdata(root))
                        except ET.ParseError:
                            logger.debug(f"Skipping non-XML in ZIP: {name}")

        if not docs:
            raise ParseError("No valid MSFS airport scenery found in ZIP archive")

        if len(docs) > 1:
            logger.info(f"ZIP contains {len(docs)} airports, using first")
        return docs[0]

    def _parse_bgl_file(self, path: Path) -> MSFSDocument:
        """Parse a compiled BGL file."""
        if not path.exists():
            raise ParseError(f"File not found: {path}")
        data = path.read_bytes()
        return parse_bgl(data, source_path=str(path))

    def _parse_xml_bytes(self, data: bytes) -> MSFSDocument:
        """Parse raw XML bytes."""
        root = ET.fromstring(data)
        return self._parse_fsdata(root)

    def _parse_xml_file(self, path: Path) -> MSFSDocument:
        """Parse a single XML file."""
        if not path.exists():
            raise ParseError(f"File not found: {path}")
        tree = ET.parse(path)
        return self._parse_fsdata(tree.getroot())

    def _parse_zip(self, path: Path) -> MSFSDocument:
        """Parse a ZIP archive containing scenery XML or BGL files."""
        if not path.exists():
            raise ParseError(f"File not found: {path}")

        docs = []
        with zipfile.ZipFile(path, "r") as zf:
            # First try BGL files (compiled scenery — most common in downloads)
            for name in zf.namelist():
                if name.lower().endswith(".bgl"):
                    try:
                        data = zf.read(name)
                        if is_bgl(data):
                            doc = parse_bgl(data, source_path=str(path))
                            if doc.parking_spots or doc.runways:
                                docs.append(doc)
                                logger.info(f"Parsed BGL from ZIP: {name}")
                    except (ValueError, Exception) as e:
                        logger.debug(f"Skipping BGL in ZIP: {name}: {e}")

            # Then try XML files
            if not docs:
                for name in zf.namelist():
                    if name.lower().endswith(".xml"):
                        try:
                            data = zf.read(name)
                            root = ET.fromstring(data)
                            if root.tag == "FSData" and root.findall("Airport"):
                                docs.append(self._parse_fsdata(root))
                        except ET.ParseError:
                            logger.debug(f"Skipping non-XML or invalid XML in ZIP: {name}")

        if not docs:
            raise ParseError("No valid MSFS airport scenery found in ZIP archive")

        # Return first document (most scenery packages have one airport)
        if len(docs) > 1:
            logger.info(f"ZIP contains {len(docs)} airports, using first")
        return docs[0]

    def _parse_directory(self, path: Path) -> MSFSDocument:
        """Parse scenery files (BGL or XML) in a directory."""
        docs = []

        # Try BGL files first
        for bgl_file in sorted(path.rglob("*.bgl")):
            try:
                data = bgl_file.read_bytes()
                if is_bgl(data):
                    doc = parse_bgl(data, source_path=str(bgl_file))
                    if doc.parking_spots or doc.runways:
                        docs.append(doc)
                        logger.info(f"Parsed BGL: {bgl_file}")
            except (ValueError, Exception) as e:
                logger.debug(f"Skipping BGL: {bgl_file}: {e}")

        # Fall back to XML
        if not docs:
            for xml_file in sorted(path.rglob("*.xml")):
                try:
                    tree = ET.parse(xml_file)
                    root = tree.getroot()
                    if root.tag == "FSData" and root.findall("Airport"):
                        docs.append(self._parse_fsdata(root))
                except ET.ParseError:
                    logger.debug(f"Skipping invalid XML: {xml_file}")

        if not docs:
            raise ParseError(f"No valid MSFS airport scenery found in {path}")

        if len(docs) > 1:
            logger.info(f"Directory contains {len(docs)} airports, using first")
        return docs[0]

    def _parse_fsdata(self, root: ET.Element) -> MSFSDocument:
        """Parse FSData root element containing Airport definitions."""
        if root.tag != "FSData":
            raise ParseError(f"Expected FSData root element, got {root.tag}")

        airports = root.findall("Airport")
        if not airports:
            raise ParseError("No Airport elements found in FSData")

        # Use first airport
        airport = airports[0]
        return self._parse_airport(airport)

    def _parse_airport(self, airport: ET.Element) -> MSFSDocument:
        """Parse an Airport element into MSFSDocument."""
        doc = MSFSDocument(
            airport_name=airport.get("name", ""),
            icao_code=airport.get("ident", ""),
            lat=float(airport.get("lat", 0)),
            lon=float(airport.get("lon", 0)),
            alt=float(airport.get("alt", 0)),
        )

        # Parse TaxiwayParking elements
        for elem in airport.findall("TaxiwayParking"):
            spot = self._parse_parking(elem)
            if spot:
                doc.parking_spots.append(spot)

        # Parse TaxiwayPoint elements
        for elem in airport.findall("TaxiwayPoint"):
            point = self._parse_taxi_point(elem)
            if point:
                doc.taxi_points.append(point)

        # Parse TaxiwayPath elements
        for elem in airport.findall("TaxiwayPath"):
            path = self._parse_taxi_path(elem)
            if path:
                doc.taxi_paths.append(path)

        # Parse Runway elements
        for elem in airport.findall("Runway"):
            runway = self._parse_runway(elem)
            if runway:
                doc.runways.append(runway)

        # Parse Apron elements
        for elem in airport.findall("Apron"):
            apron = self._parse_apron(elem)
            if apron:
                doc.aprons.append(apron)

        logger.info(
            f"Parsed MSFS airport {doc.icao_code}: "
            f"{len(doc.parking_spots)} parking, "
            f"{len(doc.taxi_points)} taxi points, "
            f"{len(doc.taxi_paths)} taxi paths, "
            f"{len(doc.runways)} runways, "
            f"{len(doc.aprons)} aprons"
        )

        return doc

    def _parse_parking(self, elem: ET.Element) -> MSFSParkingSpot | None:
        """Parse a TaxiwayParking element."""
        try:
            index = int(elem.get("index", 0))
            lat = float(elem.get("lat", 0))
            lon = float(elem.get("lon", 0))

            if lat == 0 and lon == 0:
                return None

            heading = float(elem.get("heading", 0))
            radius = float(elem.get("radius", 25))

            # Parse type
            type_str = elem.get("type", "RAMP").upper()
            try:
                parking_type = ParkingType(type_str)
            except ValueError:
                parking_type = ParkingType.RAMP

            name = elem.get("name", "")
            number = int(elem.get("number", 0))

            # Parse airline codes (comma-separated)
            airline_str = elem.get("airlineCodes", "")
            airline_codes = [c.strip() for c in airline_str.split(",") if c.strip()] if airline_str else []

            return MSFSParkingSpot(
                index=index,
                lat=lat,
                lon=lon,
                heading=heading,
                radius=radius,
                type=parking_type,
                name=name,
                number=number,
                airline_codes=airline_codes,
            )
        except (ValueError, TypeError) as e:
            logger.debug(f"Skipping invalid parking element: {e}")
            return None

    def _parse_taxi_point(self, elem: ET.Element) -> MSFSTaxiPoint | None:
        """Parse a TaxiwayPoint element."""
        try:
            index = int(elem.get("index", 0))
            lat = float(elem.get("lat", 0))
            lon = float(elem.get("lon", 0))

            if lat == 0 and lon == 0:
                return None

            type_str = elem.get("type", "NORMAL").upper()
            try:
                point_type = TaxiPointType(type_str)
            except ValueError:
                point_type = TaxiPointType.NORMAL

            return MSFSTaxiPoint(
                index=index,
                lat=lat,
                lon=lon,
                type=point_type,
            )
        except (ValueError, TypeError) as e:
            logger.debug(f"Skipping invalid taxi point: {e}")
            return None

    def _parse_taxi_path(self, elem: ET.Element) -> MSFSTaxiPath | None:
        """Parse a TaxiwayPath element."""
        try:
            start = int(elem.get("start", 0))
            end = int(elem.get("end", 0))
            width = float(elem.get("width", 20))
            name = elem.get("name", "")
            weight_limit = float(elem.get("weightLimit", 0))
            surface = elem.get("surface", "ASPHALT")

            type_str = elem.get("type", "TAXI").upper()
            try:
                path_type = TaxiPathType(type_str)
            except ValueError:
                path_type = TaxiPathType.TAXI

            return MSFSTaxiPath(
                start=start,
                end=end,
                width=width,
                name=name,
                type=path_type,
                weight_limit=weight_limit,
                surface=surface,
            )
        except (ValueError, TypeError) as e:
            logger.debug(f"Skipping invalid taxi path: {e}")
            return None

    def _parse_runway(self, elem: ET.Element) -> MSFSRunway | None:
        """Parse a Runway element."""
        try:
            lat = float(elem.get("lat", 0))
            lon = float(elem.get("lon", 0))

            if lat == 0 and lon == 0:
                return None

            heading = float(elem.get("heading", 0))
            length = float(elem.get("length", 0))
            width = float(elem.get("width", 45))
            surface = elem.get("surface", "ASPHALT")
            designator = elem.get("designator", "")

            # Parse runway ends
            primary_end = None
            secondary_end = None
            for end_elem in elem.findall("RunwayEnd"):
                end = MSFSRunwayEnd(
                    designator=end_elem.get("designator", ""),
                    lat=float(end_elem.get("lat", lat)),
                    lon=float(end_elem.get("lon", lon)),
                )
                if primary_end is None:
                    primary_end = end
                else:
                    secondary_end = end

            return MSFSRunway(
                lat=lat,
                lon=lon,
                heading=heading,
                length=length,
                width=width,
                surface=surface,
                designator=designator,
                primary_end=primary_end,
                secondary_end=secondary_end,
            )
        except (ValueError, TypeError) as e:
            logger.debug(f"Skipping invalid runway: {e}")
            return None

    def _parse_apron(self, elem: ET.Element) -> MSFSApron | None:
        """Parse an Apron element."""
        try:
            surface = elem.get("surface", "ASPHALT")
            vertices = []

            for vertex in elem.findall("Vertex"):
                lat = float(vertex.get("lat", 0))
                lon = float(vertex.get("lon", 0))
                if lat != 0 or lon != 0:
                    vertices.append(MSFSApronVertex(lat=lat, lon=lon))

            if not vertices:
                return None

            return MSFSApron(surface=surface, vertices=vertices)
        except (ValueError, TypeError) as e:
            logger.debug(f"Skipping invalid apron: {e}")
            return None

    def validate(self, model: MSFSDocument) -> list[str]:
        """
        Validate parsed MSFS data.

        Args:
            model: Parsed MSFSDocument

        Returns:
            List of validation warnings
        """
        warnings = []

        if not model.parking_spots and not model.runways:
            warnings.append("No parking spots or runways found")

        if not model.gates:
            warnings.append("No gate-type parking spots found (only ramps/docks)")

        # Check for unreferenced taxi points
        if model.taxi_points and model.taxi_paths:
            referenced = set()
            for path in model.taxi_paths:
                referenced.add(path.start)
                referenced.add(path.end)
            point_indices = {p.index for p in model.taxi_points}
            unreferenced = point_indices - referenced
            if unreferenced:
                warnings.append(f"{len(unreferenced)} taxi points not referenced by any path")

        # Check for paths referencing non-existent points
        if model.taxi_paths and model.taxi_points:
            point_indices = {p.index for p in model.taxi_points}
            bad_refs = 0
            for path in model.taxi_paths:
                if path.start not in point_indices or path.end not in point_indices:
                    bad_refs += 1
            if bad_refs:
                warnings.append(f"{bad_refs} taxi paths reference non-existent points")

        return warnings

    def to_config(self, model: MSFSDocument) -> dict:
        """
        Convert MSFSDocument to internal configuration.

        Args:
            model: Parsed MSFSDocument

        Returns:
            Configuration dictionary for airport config
        """
        from src.formats.msfs.converter import MSFSConverter

        converter = MSFSConverter(self.converter)
        return converter.to_config(model)
