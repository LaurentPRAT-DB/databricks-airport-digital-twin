"""Centralized demo mode configuration.

All demo defaults are read from environment variables at import time.
Override via app.yaml env section or shell environment.

Environment variables:
    DEMO_MODE: "true" to start in demo mode with synthetic data (default: "true")
    DEMO_DEFAULT_AIRPORT: ICAO code for the default airport (default: "KSFO")
    DEMO_FLIGHT_COUNT: Number of synthetic flights to generate (default: 100)
"""

import os

DEMO_MODE: bool = os.getenv("DEMO_MODE", "true").lower() in ("true", "1", "yes")
DEFAULT_AIRPORT_ICAO: str = os.getenv("DEMO_DEFAULT_AIRPORT", "KSFO")
try:
    DEFAULT_FLIGHT_COUNT: int = int(os.getenv("DEMO_FLIGHT_COUNT", "100"))
except (ValueError, TypeError):
    DEFAULT_FLIGHT_COUNT: int = 100

# Derive IATA from ICAO for convenience
_ICAO_TO_IATA = {
    # US airports
    "KSFO": "SFO", "KJFK": "JFK", "KLAX": "LAX", "KORD": "ORD",
    "KATL": "ATL", "KDEN": "DEN", "KDFW": "DFW", "KMIA": "MIA",
    "KBOS": "BOS", "KSEA": "SEA", "KIAH": "IAH", "KLAS": "LAS",
    "KMSP": "MSP", "KPHX": "PHX", "KEWR": "EWR", "KDTW": "DTW",
    "KMCO": "MCO", "KCLT": "CLT", "KPHL": "PHL", "KSAN": "SAN",
    "KPDX": "PDX",
    # Europe
    "EGLL": "LHR", "LFPG": "CDG", "EDDF": "FRA", "EHAM": "AMS",
    "LSGG": "GVA", "LGAV": "ATH", "LEMD": "MAD", "LIRF": "FCO",
    # Middle East
    "OMDB": "DXB", "OMAA": "AUH",
    # Asia-Pacific
    "RJTT": "HND", "RJAA": "NRT", "VHHH": "HKG", "WSSS": "SIN",
    "YSSY": "SYD", "RKSI": "ICN", "ZBAA": "PEK", "VTBS": "BKK",
    # Americas / Africa
    "SBGR": "GRU", "FAOR": "JNB", "FACT": "CPT",
    "GMMN": "CMN", "MMMX": "MEX",
}


def icao_to_iata(icao_code: str) -> str:
    """Convert ICAO code to IATA. Falls back to stripping leading 'K'."""
    if icao_code in _ICAO_TO_IATA:
        return _ICAO_TO_IATA[icao_code]
    if icao_code.startswith("K") and len(icao_code) == 4:
        return icao_code[1:]
    return icao_code


DEFAULT_AIRPORT_IATA: str = icao_to_iata(DEFAULT_AIRPORT_ICAO)
