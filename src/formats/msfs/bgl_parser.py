"""
BGL Binary Parser for Microsoft Flight Simulator compiled scenery.

Decodes compiled .bgl files from MSFS 2020 scenery packages to extract
airport data (parking spots, runways). The BGL format is a binary container
with section headers, sub-records, and custom coordinate encoding.

BGL coordinate formulas (from albar965/atools):
    lon = raw_int32 * (360.0 / (3 * 0x10000000)) - 180.0
    lat = 90.0 - raw_int32 * (180.0 / (2 * 0x10000000))

Reference: https://github.com/albar965/atools (GPLv3)
"""

import logging
import re
import struct
from dataclasses import dataclass
from typing import Optional

from src.formats.msfs.models import (
    MSFSDocument,
    MSFSParkingSpot,
    MSFSRunway,
    MSFSRunwayEnd,
    ParkingType,
)

logger = logging.getLogger(__name__)

BGL_MAGIC = 0x19920201

# BGL section types
SECTION_AIRPORT = 0x03

# BGL airport sub-record types (MSFS 2020)
REC_NAME = 0x0019
REC_RUNWAY_MSFS = 0x00CE
REC_TAXI_PARKING_MSFS = 0x00E7

# Airport record header size (type(2) + size(4) + counts(6) + coords(12) + tower(12) + magvar(4) + ident(4) + extra(36))
AIRPORT_HEADER_SIZE = 0x50

# BGL parking name indices → display prefix
BGL_PARKING_NAMES = {
    0: "", 1: "P", 2: "NP", 3: "NEP", 4: "EP", 5: "SEP", 6: "SP",
    7: "SWP", 8: "WP", 9: "NWP", 10: "GATE", 11: "DOCK",
    12: "GA", 13: "GB", 14: "GC", 15: "GD", 16: "GE", 17: "GF",
    18: "GG", 19: "GH", 20: "GI", 21: "GJ", 22: "GK", 23: "GL",
    24: "GM", 25: "GN", 26: "GO", 27: "GP", 28: "GQ", 29: "GR",
    30: "GS", 31: "GT", 32: "GU", 33: "GV", 34: "GW", 35: "GX",
    36: "GY", 37: "GZ",
}

# BGL parking type indices → (ParkingType, is_gate)
BGL_PARKING_TYPES = {
    0: (ParkingType.RAMP, False),    # UNKNOWN
    1: (ParkingType.RAMP, False),    # RAMP_GA
    2: (ParkingType.RAMP, False),    # RAMP_GA_SMALL
    3: (ParkingType.RAMP, False),    # RAMP_GA_MEDIUM
    4: (ParkingType.RAMP, False),    # RAMP_GA_LARGE
    5: (ParkingType.RAMP, False),    # RAMP_CARGO
    6: (ParkingType.RAMP, False),    # RAMP_MIL_CARGO
    7: (ParkingType.RAMP, False),    # RAMP_MIL_COMBAT
    8: (ParkingType.GATE, True),     # GATE_SMALL
    9: (ParkingType.GATE, True),     # GATE_MEDIUM
    10: (ParkingType.GATE, True),    # GATE_HEAVY
    11: (ParkingType.DOCK, False),   # DOCK_GA
    12: (ParkingType.RAMP, False),   # FUEL
    13: (ParkingType.RAMP, False),   # VEHICLES
    14: (ParkingType.RAMP, False),   # RAMP_GA_EXTRA
    15: (ParkingType.GATE, True),    # GATE_EXTRA
}


def bgl_lon(raw: int) -> float:
    """Convert BGL raw int32 to longitude in degrees."""
    return raw * (360.0 / (3 * 0x10000000)) - 180.0


def bgl_lat(raw: int) -> float:
    """Convert BGL raw int32 to latitude in degrees."""
    return 90.0 - raw * (180.0 / (2 * 0x10000000))


@dataclass
class BGLSection:
    """A BGL file section header."""
    type: int
    subsection_count: int
    first_subsection_offset: int
    total_size: int


@dataclass
class BGLSubRecord:
    """A sub-record within an airport record."""
    type: int
    size: int
    offset: int


def is_bgl(data: bytes) -> bool:
    """Check if data starts with BGL magic number."""
    if len(data) < 4:
        return False
    magic = struct.unpack_from("<I", data, 0)[0]
    return magic == BGL_MAGIC


def extract_icao_from_path(path: str) -> str:
    """
    Try to extract ICAO code from a file/directory path.

    Most MSFS scenery packages include the ICAO code in the filename,
    e.g. 'plasmastorm-lsgg-geneva-airport_9OP2u.zip' → 'LSGG'.
    """
    # Common false positives to exclude
    EXCLUDE = {
        "MSFS", "PACK", "MEGA", "LITE", "FREE", "FULL", "DEMO", "BETA",
        "BEST", "PLUS", "EDIT", "FILE", "DATA", "DOCS", "TEST", "TEMP",
        "HOME", "USER", "APPS", "MAIN", "HIGH", "BASE", "CORE",
    }

    # Known ICAO first-letter region prefixes
    ICAO_FIRST = set("BCDEFGHKLMNOPRSTUVWYZ")

    matches = re.findall(r'(?:^|(?<=[-_/\\]))([A-Za-z]{4})(?=[-_/\\.]|$)', path)
    for m in matches:
        candidate = m.upper()
        if candidate in EXCLUDE:
            continue
        if candidate[0] in ICAO_FIRST:
            return candidate
    return ""


def parse_bgl(data: bytes, source_path: str = "") -> MSFSDocument:
    """
    Parse a compiled BGL file into an MSFSDocument.

    Args:
        data: Raw BGL file bytes
        source_path: Optional source file/zip path to extract ICAO from filename

    Returns:
        Parsed MSFSDocument with parking spots and runways

    Raises:
        ValueError: If BGL format is invalid
    """
    if len(data) < 24:
        raise ValueError("BGL file too small")

    magic = struct.unpack_from("<I", data, 0)[0]
    if magic != BGL_MAGIC:
        raise ValueError(f"Invalid BGL magic: 0x{magic:08x}")

    header_size = struct.unpack_from("<I", data, 4)[0]
    num_sections = struct.unpack_from("<I", data, 0x14)[0]

    # Parse section table (starts after header)
    sections = []
    for i in range(num_sections):
        off = header_size + i * 20
        if off + 20 > len(data):
            break
        sec_type, sec_unk, sec_count, sec_offset, sec_size = struct.unpack_from(
            "<IIIII", data, off
        )
        sections.append(BGLSection(sec_type, sec_count, sec_offset, sec_size))

    # Find AIRPORT section
    airport_sections = [s for s in sections if s.type == SECTION_AIRPORT]
    if not airport_sections:
        raise ValueError("No AIRPORT section found in BGL")

    airport_sec = airport_sections[0]

    # Read subsection index entries to find the airport record
    for i in range(airport_sec.subsection_count):
        entry_off = airport_sec.first_subsection_offset + i * 16
        if entry_off + 16 > len(data):
            continue

        _qmid, _num_recs, rec_offset, rec_size = struct.unpack_from(
            "<IIII", data, entry_off
        )

        if rec_offset + rec_size > len(data):
            logger.warning(f"Airport record extends past file end, skipping")
            continue

        doc = _parse_airport_record(data, rec_offset, rec_size, source_path)
        if doc:
            return doc

    raise ValueError("No valid airport record found in BGL")


def _parse_airport_record(
    data: bytes, rec_offset: int, rec_size: int, source_path: str = ""
) -> Optional[MSFSDocument]:
    """Parse an airport record from BGL data."""
    if rec_size < AIRPORT_HEADER_SIZE:
        return None

    # Read airport record header
    o = rec_offset
    rec_id = struct.unpack_from("<H", data, o)[0]
    o += 2
    size = struct.unpack_from("<I", data, o)[0]
    o += 4

    if rec_id != 0x0056:
        logger.warning(f"Unexpected airport record type: 0x{rec_id:04x}")

    # Counts
    num_runways = data[o]
    o += 6  # skip numRunways(1)+numComs(1)+numStarts(1)+numApproaches(1)+numAprons(1)+numHelipads(1)

    # Coordinates
    lon_raw = struct.unpack_from("<i", data, o)[0]
    o += 4
    lat_raw = struct.unpack_from("<i", data, o)[0]
    o += 4

    airport_lon = bgl_lon(lon_raw)
    airport_lat = bgl_lat(lat_raw)

    # Skip remaining header fields to reach sub-records
    # Alt(4) + towerLon(4) + towerLat(4) + towerAlt(4) + magVar(4) + ident(4) + extra(36) = 60 bytes
    # Total header is 0x50 = 80 bytes from record start

    # Scan sub-records starting at rec_offset + AIRPORT_HEADER_SIZE
    sub_records = _scan_sub_records(data, rec_offset + AIRPORT_HEADER_SIZE, rec_offset + rec_size)

    # Parse airport name
    airport_name = ""
    for rec in sub_records:
        if rec.type == REC_NAME:
            # NAME record: type(2)+size(4)+name_bytes
            name_data = data[rec.offset + 6 : rec.offset + rec.size]
            airport_name = name_data.decode("utf-8", errors="replace").rstrip("\x00")
            break

    icao_code = extract_icao_from_path(source_path) if source_path else ""

    doc = MSFSDocument(
        airport_name=airport_name,
        icao_code=icao_code,
        lat=airport_lat,
        lon=airport_lon,
    )

    # Parse parking
    for rec in sub_records:
        if rec.type == REC_TAXI_PARKING_MSFS:
            parkings = _parse_parking_record(data, rec.offset, rec.size)
            doc.parking_spots.extend(parkings)

    # Parse runways
    for rec in sub_records:
        if rec.type == REC_RUNWAY_MSFS:
            runway = _parse_runway_record(data, rec.offset, rec.size, airport_lat, airport_lon)
            if runway:
                doc.runways.append(runway)

    logger.info(
        f"Parsed BGL airport at ({airport_lat:.3f}, {airport_lon:.3f}): "
        f"{len(doc.parking_spots)} parking spots, {len(doc.runways)} runways, "
        f"name='{airport_name}'"
    )

    return doc


def _scan_sub_records(data: bytes, start: int, end: int) -> list[BGLSubRecord]:
    """Scan type(2)+size(4) sub-records within an airport record."""
    records = []
    offset = start
    while offset < end - 6:
        rec_type = struct.unpack_from("<H", data, offset)[0]
        rec_size = struct.unpack_from("<I", data, offset + 2)[0]
        if rec_size < 6 or rec_size > (end - offset):
            break
        records.append(BGLSubRecord(rec_type, rec_size, offset))
        offset += rec_size
    return records


def _parse_parking_record(
    data: bytes, rec_offset: int, rec_size: int
) -> list[MSFSParkingSpot]:
    """
    Parse a TAXI_PARKING_MSFS record containing multiple parking spots.

    Binary layout per parking (56 bytes base + numAirlines * 4):
        flags(4) + radius(4 float) + heading(4 float) + teeOffset(16) +
        lon(4 int32) + lat(4 int32) + suffix_area(20)

    Flags bitfield:
        bits 0-5:   name index (GATE_A=12, GATE_B=13, etc.)
        bits 6-7:   pushback type
        bits 8-11:  parking type (GATE_SMALL=8, GATE_MEDIUM=9, etc.)
        bits 12-23: number
        bits 24-31: number of airline codes
    """
    parkings = []
    num_parkings = struct.unpack_from("<H", data, rec_offset + 6)[0]
    off = rec_offset + 8  # after type(2)+size(4)+count(2)
    end = rec_offset + rec_size

    for i in range(num_parkings):
        if off + 56 > end:
            logger.warning(f"Parking record truncated at spot {i}/{num_parkings}")
            break

        flags = struct.unpack_from("<I", data, off)[0]
        name_idx = flags & 0x3F
        type_idx = (flags >> 8) & 0xF
        number = (flags >> 12) & 0xFFF
        num_airlines = (flags >> 24) & 0xFF

        radius = struct.unpack_from("<f", data, off + 4)[0]
        heading = struct.unpack_from("<f", data, off + 8)[0]
        # teeOffset at off+12: 16 bytes skipped
        lon_raw = struct.unpack_from("<i", data, off + 28)[0]
        lat_raw = struct.unpack_from("<i", data, off + 32)[0]

        lon = bgl_lon(lon_raw)
        lat = bgl_lat(lat_raw)

        # Read airline codes (4 bytes each, Latin-1)
        # Filter to valid ICAO codes (2-4 uppercase letters/digits)
        airline_codes = []
        for j in range(num_airlines):
            al_off = off + 36 + j * 4
            if al_off + 4 > end:
                break
            code = data[al_off : al_off + 4].decode("latin1").rstrip("\x00").strip()
            if code and len(code) >= 2 and code.isalnum() and code.isascii():
                airline_codes.append(code)

        # Map BGL type to our ParkingType
        parking_type, is_gate = BGL_PARKING_TYPES.get(
            type_idx, (ParkingType.RAMP, False)
        )

        # Build display name from BGL name index
        name_prefix = BGL_PARKING_NAMES.get(name_idx, "")
        # Map to MSFS XML-style name for compatibility with existing converter
        if is_gate or name_idx >= 10:
            msfs_name = f"GATE_{name_prefix}" if name_prefix else "GATE_"
        elif parking_type == ParkingType.DOCK:
            msfs_name = f"DOCK_{name_prefix}" if name_prefix else "DOCK_"
        else:
            msfs_name = f"RAMP_{name_prefix}" if name_prefix else "RAMP_"

        parkings.append(
            MSFSParkingSpot(
                index=i,
                lat=lat,
                lon=lon,
                heading=heading % 360,
                radius=radius,
                type=parking_type,
                name=msfs_name,
                number=number,
                airline_codes=airline_codes,
            )
        )

        # Advance: 56 bytes base + variable airline codes
        off += 56 + num_airlines * 4

    return parkings


def _parse_runway_record(
    data: bytes,
    rec_offset: int,
    rec_size: int,
    airport_lat: float,
    airport_lon: float,
) -> Optional[MSFSRunway]:
    """
    Parse a RUNWAY_MSFS sub-record.

    Binary layout (from data start = rec_offset + 6):
        surface(2) + flags(2) + numEnds(2) + unknown(8) +
        lon(4 int32) + lat(4 int32) + alt(4) +
        length(4 float) + width(4 float) + heading(4 float)
    """
    if rec_size < 44:
        return None

    # Data starts after type(2)+size(4) header
    doff = rec_offset + 6

    # Surface info and flags
    surface_idx = struct.unpack_from("<H", data, doff)[0]

    # Position at +14 from data start (after surface(2)+flags(2)+numEnds(2)+unk(8))
    pos_off = doff + 14
    lon_raw = struct.unpack_from("<i", data, pos_off)[0]
    lat_raw = struct.unpack_from("<i", data, pos_off + 4)[0]
    _alt = struct.unpack_from("<I", data, pos_off + 8)[0]

    rwy_lon = bgl_lon(lon_raw)
    rwy_lat = bgl_lat(lat_raw)

    # Length, width, heading as floats at +26, +30, +34 from data start
    length = struct.unpack_from("<f", data, doff + 26)[0]
    width = struct.unpack_from("<f", data, doff + 30)[0]
    heading = struct.unpack_from("<f", data, doff + 34)[0]

    # Validate coordinates
    if abs(rwy_lat - airport_lat) > 0.5 or abs(rwy_lon - airport_lon) > 0.5:
        logger.warning(
            f"Runway coordinates ({rwy_lat:.3f}, {rwy_lon:.3f}) "
            f"too far from airport ({airport_lat:.3f}, {airport_lon:.3f})"
        )
        return None

    if length <= 0 or width <= 0:
        return None

    # Compute designator from heading
    rwy_num = round(heading / 10) % 36
    if rwy_num == 0:
        rwy_num = 36
    recip_num = (rwy_num + 18) % 36
    if recip_num == 0:
        recip_num = 36
    designator = f"{rwy_num:02d}/{recip_num:02d}"

    surface_map = {0: "CONCRETE", 1: "ASPHALT", 2: "GRASS", 4: "DIRT", 7: "GRAVEL"}
    surface = surface_map.get(surface_idx & 0xFF, "ASPHALT")

    import math

    half_len_m = length / 2
    # Approximate runway end positions
    hdg_rad = math.radians(heading)
    dlat = (half_len_m / 111320) * math.cos(hdg_rad)
    dlon = (half_len_m / (111320 * math.cos(math.radians(rwy_lat)))) * math.sin(hdg_rad)

    primary_end = MSFSRunwayEnd(
        designator=f"{rwy_num:02d}",
        lat=rwy_lat - dlat,
        lon=rwy_lon - dlon,
    )
    secondary_end = MSFSRunwayEnd(
        designator=f"{recip_num:02d}",
        lat=rwy_lat + dlat,
        lon=rwy_lon + dlon,
    )

    return MSFSRunway(
        lat=rwy_lat,
        lon=rwy_lon,
        heading=heading,
        length=length,
        width=width,
        surface=surface,
        designator=designator,
        primary_end=primary_end,
        secondary_end=secondary_end,
    )
