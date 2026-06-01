"""ICAO ↔ IATA callsign reconciliation.

OpenSky uses ICAO format: UAL123, BAW456, DLH789
FLIFO uses IATA format:  UA123,  BA456,  LH789

This module provides bidirectional normalization so schedule_service
can deduplicate flights regardless of which format they arrive in.
"""

import re
from typing import Optional

# ICAO (3-letter) → IATA (2-letter) mapping
# Covers ~95% of commercial traffic
_ICAO_TO_IATA = {
    "AAL": "AA",  # American Airlines
    "ACA": "AC",  # Air Canada
    "AFR": "AF",  # Air France
    "AIC": "AI",  # Air India
    "AMX": "AM",  # Aeromexico
    "ANA": "NH",  # All Nippon Airways
    "ASA": "AS",  # Alaska Airlines
    "AVA": "AV",  # Avianca
    "AZA": "AZ",  # ITA Airways (ex-Alitalia)
    "BAW": "BA",  # British Airways
    "CCA": "CA",  # Air China
    "CES": "MU",  # China Eastern
    "CPA": "CX",  # Cathay Pacific
    "CSN": "CZ",  # China Southern
    "DAL": "DL",  # Delta Air Lines
    "DLH": "LH",  # Lufthansa
    "EDV": "9E",  # Endeavor Air
    "ELY": "LY",  # El Al
    "ENY": "MQ",  # Envoy Air
    "ETD": "EY",  # Etihad Airways
    "ETH": "ET",  # Ethiopian Airlines
    "EVA": "BR",  # EVA Air
    "EWG": "EW",  # Eurowings
    "EZY": "U2",  # easyJet
    "FDB": "FZ",  # flydubai
    "FFT": "F9",  # Frontier Airlines
    "FIN": "AY",  # Finnair
    "GAI": "G3",  # Gol Airlines
    "GLO": "G3",  # Gol Linhas Aereas
    "HAL": "HA",  # Hawaiian Airlines
    "ICE": "FI",  # Icelandair
    "JAL": "JL",  # Japan Airlines
    "JBU": "B6",  # JetBlue Airways
    "JST": "JQ",  # Jetstar Airways
    "KAL": "KE",  # Korean Air
    "KLM": "KL",  # KLM Royal Dutch
    "LAN": "LA",  # LATAM Chile
    "MAS": "MH",  # Malaysia Airlines
    "NKS": "NK",  # Spirit Airlines
    "QFA": "QF",  # Qantas
    "QTR": "QR",  # Qatar Airways
    "RPA": "YX",  # Republic Airways
    "RYR": "FR",  # Ryanair
    "SAS": "SK",  # SAS
    "SAA": "SA",  # South African Airways
    "SIA": "SQ",  # Singapore Airlines
    "SKW": "OO",  # SkyWest Airlines
    "SVA": "SV",  # Saudia
    "SWA": "WN",  # Southwest Airlines
    "TAM": "JJ",  # LATAM Brasil
    "TAP": "TP",  # TAP Portugal
    "THA": "TG",  # Thai Airways
    "THY": "TK",  # Turkish Airlines
    "UAE": "EK",  # Emirates
    "UAL": "UA",  # United Airlines
    "VIR": "VS",  # Virgin Atlantic
    "VOZ": "VA",  # Virgin Australia
    "WJA": "WS",  # WestJet
    # Regional European
    "AEE": "A3",  # Aegean Airlines
    "BEE": "BE",  # Flybe
    "CTN": "OA",  # Croatia Airlines / Olympic (Greece)
    "IBE": "IB",  # Iberia
    "SWR": "LX",  # Swiss
    "TAR": "RO",  # TAROM
    "VLG": "VY",  # Vueling
    # Middle East
    "GFA": "GF",  # Gulf Air
    "MEA": "ME",  # Middle East Airlines
    "OMA": "WY",  # Oman Air
    "RJA": "RJ",  # Royal Jordanian
    # Americas
    "AAY": "G4",  # Allegiant Air
    "AZU": "AD",  # Azul Brazilian
    "JNA": "JA",  # JetSMART
    "SCX": "SY",  # Sun Country
    "WUP": "UP",  # Bahamas Air / Wheels Up
    # Asia Pacific
    "AAR": "OZ",  # Asiana Airlines
    "APJ": "MM",  # Peach Aviation
    "JJP": "GK",  # Jetstar Japan
    "SKY": "BC",  # Skymark Airlines
    "SFJ": "7G",  # StarFlyer
    "TWB": "TW",  # T'way Air
}

# Reverse mapping: IATA → ICAO
_IATA_TO_ICAO = {v: k for k, v in _ICAO_TO_IATA.items()}

# Regex: split callsign into alpha prefix + numeric suffix
_CALLSIGN_RE = re.compile(r"^([A-Z]{2,3})(\d+)$")


def to_iata(callsign: str) -> Optional[str]:
    """Convert ICAO callsign (UAL123) to IATA flight number (UA123).

    Returns None if prefix not recognized (passes through unchanged).
    """
    callsign = callsign.strip().upper()
    m = _CALLSIGN_RE.match(callsign)
    if not m:
        return None

    prefix, number = m.group(1), m.group(2)

    if len(prefix) == 3:
        iata = _ICAO_TO_IATA.get(prefix)
        if iata:
            return f"{iata}{number}"
    elif len(prefix) == 2:
        return callsign  # Already IATA format

    return None


def to_icao(flight_number: str) -> Optional[str]:
    """Convert IATA flight number (UA123) to ICAO callsign (UAL123).

    Returns None if prefix not recognized.
    """
    flight_number = flight_number.strip().upper()
    m = _CALLSIGN_RE.match(flight_number)
    if not m:
        return None

    prefix, number = m.group(1), m.group(2)

    if len(prefix) == 2:
        icao = _IATA_TO_ICAO.get(prefix)
        if icao:
            return f"{icao}{number}"
    elif len(prefix) == 3:
        return flight_number  # Already ICAO format

    return None


def normalize(callsign: str) -> str:
    """Normalize any callsign to IATA format for dedup comparison.

    If conversion fails, returns the original callsign stripped/uppercased.
    This ensures consistent matching regardless of source format.
    """
    callsign = callsign.strip().upper()
    iata = to_iata(callsign)
    return iata if iata else callsign


def are_same_flight(a: str, b: str) -> bool:
    """Check if two callsigns refer to the same flight.

    Handles ICAO vs IATA format differences:
      are_same_flight("UAL123", "UA123") → True
      are_same_flight("BA456", "BAW456") → True
    """
    return normalize(a) == normalize(b)
