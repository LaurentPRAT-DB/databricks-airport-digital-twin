"""Immutable constants for the synthetic flight system.

Pure data — never reassigned at runtime. Extracted from fallback.py to
separate static configuration from mutable simulation state.
"""

from typing import Dict, Tuple

# ============================================================================
# AIRLINE TURNAROUND SPEED FACTORS
# ============================================================================
# 1.0 = standard, <1.0 = faster turnaround, >1.0 = slower turnaround.
# Based on industry data: LCCs target 25-30 min turns, full-service 45-90 min,
# Gulf/Asian premium carriers add 5-15% for extra catering/cleaning.

AIRLINE_TURNAROUND_FACTOR: Dict[str, float] = {
    # US low-cost carriers — fast turns
    "SWA": 0.72,   # Southwest: 25-min target, industry fastest
    "FFT": 0.78,   # Frontier: ULCC, minimal service
    "NKS": 0.78,   # Spirit: ULCC
    "JBU": 0.88,   # JetBlue: midway LCC/legacy
    # US legacy carriers — standard
    "UAL": 1.0, "DAL": 1.0, "AAL": 1.0,
    # US regional — slightly faster
    "ASA": 0.92, "SKW": 0.90, "RPA": 0.90, "ENY": 0.90,
    # European LCCs — very fast
    "RYR": 0.70,   # Ryanair: 25-min target
    "EZY": 0.75,   # easyJet: 30-min target
    # European legacy
    "BAW": 1.05, "DLH": 1.05, "AFR": 1.05, "KLM": 1.0,
    # Gulf carriers — premium service, longer turns
    "UAE": 1.15, "QTR": 1.12, "ETD": 1.10,
    # Asian carriers — premium service
    "SIA": 1.10, "CPA": 1.08, "ANA": 1.05, "JAL": 1.05, "KAL": 1.05,
    "CZ": 1.0,     # China Southern
    # Latin American
    "AMX": 1.0, "MXA": 1.0,
    # Hawaiian
    "HAL": 0.95,
}
_DEFAULT_AIRLINE_FACTOR = 1.0

# ============================================================================
# AIRLINE NAMES — Callsign prefix → airline name
# ============================================================================

_AIRLINE_NAMES: Dict[str, str] = {
    # ICAO codes (3-letter)
    "UAL": "United Airlines",
    "DAL": "Delta Air Lines",
    "AAL": "American Airlines",
    "SWA": "Southwest Airlines",
    "JBU": "JetBlue Airways",
    "ASA": "Alaska Airlines",
    "UAE": "Emirates",
    "AFR": "Air France",
    "CPA": "Cathay Pacific",
    "CSN": "China Southern",
    "HAL": "Hawaiian Airlines",
    "ACA": "Air Canada",
    "MXA": "Mexicana",
    "QFA": "Qantas",
    "ANA": "All Nippon Airways",
    "BAW": "British Airways",
    "DLH": "Lufthansa",
    "KAL": "Korean Air",
    "JAL": "Japan Airlines",
    "SIA": "Singapore Airlines",
    "THY": "Turkish Airlines",
    "EVA": "EVA Air",
    "CCA": "Air China",
    "SAS": "SAS",
    "ICE": "Icelandair",
    "FIN": "Finnair",
    "TAP": "TAP Portugal",
    "KLM": "KLM Royal Dutch",
    "QTR": "Qatar Airways",
    "ETH": "Ethiopian Airlines",
    "VIR": "Virgin Atlantic",
    "NKS": "Spirit Airlines",
    "FFT": "Frontier Airlines",
    "SKW": "SkyWest Airlines",
    "RPA": "Republic Airways",
    "ENY": "Envoy Air",
    "PDT": "Piedmont Airlines",
    "CPZ": "Compass Airlines",
    "EDV": "Endeavor Air",
    "OTH": "Other",
    # Airlines in AIRLINES dict but previously missing here
    "AAY": "Allegiant Air",
    "AMX": "Aeromexico",
    "ETD": "Etihad Airways",
    "EZY": "easyJet",
    "FDB": "flydubai",
    "RYR": "Ryanair",
    "SAA": "South African Airways",
    "SCX": "Sun Country Airlines",
    "TAM": "LATAM Airlines",
    # Airlines from calibration profiles (known_profiles.py)
    "SKY": "Skymark Airlines",
    "ADO": "Air Do",
    "SFJ": "StarFlyer",
    "CES": "China Eastern Airlines",
    "SNJ": "Solaseed Air",
    "IBX": "IBEX Airlines",
    "AAR": "Asiana Airlines",
    "APJ": "Peach Aviation",
    "AVA": "Avianca",
    "AZU": "Azul Brazilian Airlines",
    "CAW": "Comair",
    "ELY": "El Al",
    "EWG": "Eurowings",
    "FAS": "FlySafair",
    "GAI": "Gol Airlines",
    "GLO": "Gol Linhas Aereas",
    "HDA": "Honda Jet",
    "JJP": "Jetstar Japan",
    "JNA": "JetSMART",
    "JST": "Jetstar Airways",
    "LAN": "LATAM Chile",
    "MAS": "Malaysia Airlines",
    "MNX": "Mango Airlines",
    "SLK": "Silk Air",
    "SPI": "SpiceJet",
    "SUN": "Sun Express",
    "THA": "Thai Airways",
    "TRA": "Transavia",
    "TWB": "T'way Air",
    "VOZ": "Virgin Australia",
    "WJA": "WestJet",
    # IATA codes (2-letter) — some callsigns use these
    "CZ": "China Southern",
    "MU": "China Eastern",
    "CA": "Air China",
    "NH": "All Nippon Airways",
    "JL": "Japan Airlines",
    "KE": "Korean Air",
    "SQ": "Singapore Airlines",
    "TK": "Turkish Airlines",
    "BR": "EVA Air",
    "EK": "Emirates",
    "QR": "Qatar Airways",
    "LH": "Lufthansa",
    "BA": "British Airways",
    "AF": "Air France",
    "AC": "Air Canada",
    "QF": "Qantas",
    "HA": "Hawaiian Airlines",
    "WS": "WestJet",
}

# ============================================================================
# SEPARATION CONSTANTS (FAA/ICAO Standards)
# ============================================================================

# Wake turbulence categories
WAKE_CATEGORY: Dict[str, str] = {
    "A380": "SUPER",
    "B747": "HEAVY", "B777": "HEAVY", "B787": "HEAVY", "A330": "HEAVY",
    "A340": "HEAVY", "A350": "HEAVY", "A345": "HEAVY",
    "A320": "LARGE", "A321": "LARGE", "A319": "LARGE", "A318": "LARGE",
    "B737": "LARGE", "B738": "LARGE", "B739": "LARGE",
    "CRJ9": "LARGE", "E175": "LARGE", "E190": "LARGE",
}

# Minimum separation in nautical miles (lead aircraft → following aircraft)
WAKE_SEPARATION_NM: Dict[Tuple[str, str], float] = {
    ("SUPER", "SUPER"): 4.0,
    ("SUPER", "HEAVY"): 6.0,
    ("SUPER", "LARGE"): 7.0,
    ("SUPER", "SMALL"): 8.0,
    ("HEAVY", "HEAVY"): 4.0,
    ("HEAVY", "LARGE"): 5.0,
    ("HEAVY", "SMALL"): 6.0,
    ("LARGE", "LARGE"): 3.0,
    ("LARGE", "SMALL"): 4.0,
    ("SMALL", "SMALL"): 3.0,
}
DEFAULT_SEPARATION_NM = 3.0

# Taxi speed standards (ICAO Doc 9157 / Annex 14 design speeds)
# 1 knot ≈ 0.5144 m/s; 1° latitude ≈ 111,000 m
_KTS_TO_DEG_PER_SEC = 0.5144 / 111_000  # ~4.63e-6 °/s per knot

TAXI_SPEED_STRAIGHT_KTS = 25    # ICAO standard taxiway design speed
TAXI_SPEED_TURN_KTS = 15        # Reduced speed through turns
TAXI_SPEED_RAMP_KTS = 8         # Near-gate / ramp area
TAXI_SPEED_PUSHBACK_KTS = 3     # Tug-assisted pushback

MAX_SPEED_BELOW_FL100_KTS = 250  # 14 CFR 91.117: 250 kts IAS below 10,000 ft MSL
MAX_VELOCITY_KTS = 600            # Hard safety cap — no commercial aircraft exceeds this

# ILS Category I decision height (ft AGL) — primary approach→landing trigger
DECISION_HEIGHT_FT = 200
# Stabilized approach gate (ft AGL) — unstabilized above this → go-around
STABILIZED_APPROACH_GATE_FT = 500
STABILIZED_MAX_SPEED_OVER_VREF = 30  # kts above Vref (generous for sim)
STABILIZED_MAX_SINK_RATE = 1500       # fpm (generous — real airlines use 1000)

# Reference approach speeds (Vref) by aircraft type (kts, typical landing weight)
VREF_SPEEDS: Dict[str, int] = {
    "A318": 125, "A319": 130, "A320": 133, "A321": 138,
    "B737": 130, "B738": 135, "B739": 137,
    "CRJ9": 128, "E175": 126, "E190": 130,
    "A330": 140, "A340": 145, "A345": 145,
    "A350": 142, "B777": 149, "B787": 143,
    "B747": 152, "A380": 145,
    # Fighter jets (Easter egg)
    "F14": 155, "F15": 150, "F16": 148, "F18": 150, "F22": 155, "F35": 152,
}
_DEFAULT_VREF = 135  # A320-class fallback

# Convert NM to degrees (approximate at this latitude)
NM_TO_DEG = 1.0 / 60.0

# Minimum separation distances
MIN_APPROACH_SEPARATION_DEG = 3.0 * NM_TO_DEG  # 3 NM minimum on approach
MIN_TAXI_SEPARATION_DEG = 0.001  # ~100m for taxi operations
MIN_TAXI_SEPARATION_ARRIVAL_DEG = 0.0006  # ~60m for arriving aircraft
CROSSING_ZONE_DEG = 0.002  # ~200m — detect perpendicular taxiway crossing conflicts
MIN_GATE_SEPARATION_DEG = 0.010  # ~800m in 3D scale for gate area

# Aircraft fuselage half-lengths in meters (nose-to-center)
AIRCRAFT_HALF_LENGTH_M: Dict[str, float] = {
    "A318": 15.6,  # 31.4m total
    "A319": 16.8,  # 33.8m
    "A320": 18.9,  # 37.6m
    "A321": 22.2,  # 44.5m
    "B737": 19.6,  # 39.5m (B737-800 representative)
    "B738": 19.8,  # 39.5m
    "B739": 21.0,  # 42.1m
    "CRJ9": 18.4,  # 36.4m
    "E175": 15.9,  # 31.7m
    "E190": 18.2,  # 36.2m
    "A330": 29.6,  # 58.8m (A330-300)
    "A340": 31.7,  # 63.7m (A340-300)
    "A345": 37.6,  # 75.3m (A340-600)
    "A350": 33.1,  # 66.8m (A350-900)
    "B777": 36.9,  # 73.9m (B777-300)
    "B787": 28.3,  # 56.7m (B787-8)
    "B747": 35.3,  # 70.7m (B747-400)
    "A380": 36.4,  # 72.7m
}
_DEFAULT_HALF_LENGTH_M = 18.9  # A320-class fallback

# ============================================================================
# TAKEOFF PERFORMANCE DATA (14 CFR 25.107 / manufacturer performance manuals)
# ============================================================================
# type: (V1_kts, VR_kts, V2_kts, accel_kts_per_s, initial_climb_fpm)
TAKEOFF_PERFORMANCE: Dict[str, Tuple[int, int, int, float, int]] = {
    "A318": (125, 130, 135, 3.0, 2500),
    "A319": (128, 133, 138, 2.8, 2400),
    "A320": (130, 135, 140, 2.7, 2300),
    "A321": (135, 140, 145, 2.5, 2200),
    "B737": (128, 133, 138, 2.8, 2500),
    "B738": (132, 137, 142, 2.6, 2300),
    "B739": (134, 139, 144, 2.5, 2200),
    "CRJ9": (120, 125, 130, 3.2, 2800),
    "E175": (118, 123, 128, 3.3, 3000),
    "E190": (122, 127, 132, 3.1, 2700),
    "A330": (140, 145, 150, 2.0, 1800),
    "A340": (145, 150, 155, 1.8, 1600),
    "A345": (145, 150, 155, 1.8, 1600),
    "A350": (138, 143, 148, 2.2, 2000),
    "B777": (142, 147, 152, 2.0, 1900),
    "B787": (138, 143, 148, 2.3, 2100),
    "B747": (150, 155, 160, 1.6, 1500),
    "A380": (150, 155, 165, 1.5, 1400),
}
_DEFAULT_TAKEOFF_PERF = (130, 135, 140, 2.7, 2300)  # A320-class fallback

# Departure wake turbulence separation (FAA 7110.65 5-8-1 / ICAO Doc 4444 6.3.3)
DEPARTURE_SEPARATION_S: Dict[Tuple[str, str], int] = {
    ("SUPER", "SUPER"): 180, ("SUPER", "HEAVY"): 180,
    ("SUPER", "LARGE"): 180, ("SUPER", "SMALL"): 180,
    ("HEAVY", "HEAVY"): 120, ("HEAVY", "LARGE"): 120,
    ("HEAVY", "SMALL"): 120, ("LARGE", "SMALL"): 120,
}
DEFAULT_DEPARTURE_SEPARATION_S = 60  # Default same-runway spacing

MIN_ARRIVAL_SEPARATION_S = 60  # Minimum seconds between consecutive landings

# ============================================================================
# AIRLINE FLEET — callsign prefix to typical aircraft types
# ============================================================================

AIRLINE_FLEET: Dict[str, list] = {
    "UAL": ["B738", "B739", "A320", "A319", "B777", "B787"],  # United Airlines
    "DAL": ["B738", "B739", "A320", "A321", "A330", "B777"],  # Delta Air Lines
    "AAL": ["B738", "A321", "A320", "B777", "B787"],          # American Airlines
    "SWA": ["B737", "B738"],                                  # Southwest Airlines
    "JBU": ["A320", "A321", "A319"],                          # JetBlue Airways
    "ASA": ["B738", "B739", "A320"],                          # Alaska Airlines
    "UAE": ["A380", "B777", "A345"],                          # Emirates
    "AFR": ["A320", "A318", "A319", "A330"],                  # Air France
    "CPA": ["A330", "B777", "A350"],                          # Cathay Pacific
    # US regional carriers
    "SKW": ["CRJ9", "E175"],                                   # SkyWest Airlines
    "RPA": ["E175", "A319"],                                    # Republic Airways
    "ENY": ["E175", "CRJ9"],                                    # Envoy Air
    "PDT": ["E175", "CRJ9"],                                    # Piedmont Airlines
    "EDV": ["CRJ9", "E175"],                                    # Endeavor Air
}

CALLSIGN_PREFIXES = list(AIRLINE_FLEET.keys())

# ============================================================================
# STAR / SID CORRIDORS (approach/departure procedure templates)
# ============================================================================

_STAR_CORRIDORS: Dict[str, dict] = {
    "NORTH": {
        "name": "BDEGA",
        "transition_distances": [0.40, 0.33, 0.26],
        "transition_altitudes": [12000, 9500, 7500],
        "base_distances": [0.20, 0.16, 0.12, 0.07],
        "base_altitudes": [6000, 4500, 3200, 2500],
    },
    "EAST": {
        "name": "DYAMD",
        "transition_distances": [0.34, 0.27, 0.21],
        "transition_altitudes": [11000, 8500, 6500],
        "base_distances": [0.14, 0.11, 0.08, 0.05],
        "base_altitudes": [4800, 3800, 3000, 2500],
    },
    "SOUTH": {
        "name": "SERFR",
        "transition_distances": [0.38, 0.30, 0.24],
        "transition_altitudes": [11500, 9000, 7000],
        "base_distances": [0.18, 0.14, 0.10, 0.06],
        "base_altitudes": [5500, 4200, 3200, 2500],
    },
    "WEST": {
        "name": "OCEANIC",
        "transition_distances": [0.44, 0.36, 0.28],
        "transition_altitudes": [13000, 10000, 8000],
        "base_distances": [0.22, 0.17, 0.12, 0.07],
        "base_altitudes": [7000, 5000, 3500, 2500],
    },
}

_SID_CORRIDORS: Dict[str, dict] = {
    "NORTH": {
        "name": "NORTH DEPARTURE",
        "initial_turn_offset": 0,
        "turn_start_wp": 1,
        "turn_end_wp": 4,
    },
    "EAST": {
        "name": "EAST DEPARTURE",
        "initial_turn_offset": 0,
        "turn_start_wp": 2,
        "turn_end_wp": 5,
    },
    "SOUTH": {
        "name": "SOUTH DEPARTURE",
        "initial_turn_offset": 0,
        "turn_start_wp": 1,
        "turn_end_wp": 4,
    },
    "WEST": {
        "name": "WEST DEPARTURE",
        "initial_turn_offset": 0,
        "turn_start_wp": 3,
        "turn_end_wp": 6,
    },
}

# ============================================================================
# AIRPORT COUNTRY LOOKUP (fallback for origin/destination labeling)
# ============================================================================

_AIRPORT_COUNTRY: Dict[str, str] = {
    "SFO": "United States", "LAX": "United States", "ORD": "United States",
    "DFW": "United States", "JFK": "United States", "ATL": "United States",
    "DEN": "United States", "SEA": "United States", "BOS": "United States",
    "PHX": "United States", "LAS": "United States", "MCO": "United States",
    "MIA": "United States", "CLT": "United States", "MSP": "United States",
    "DTW": "United States", "EWR": "United States", "PHL": "United States",
    "IAH": "United States", "SAN": "United States", "PDX": "United States",
    "LHR": "United Kingdom", "CDG": "France", "FRA": "Germany",
    "AMS": "Netherlands", "HKG": "Hong Kong", "NRT": "Japan",
    "SIN": "Singapore", "SYD": "Australia", "DXB": "UAE", "ICN": "South Korea",
    "HND": "Japan",
    # European
    "GVA": "Switzerland", "MUC": "Germany", "DUS": "Germany",
    "HAM": "Germany", "BER": "Germany", "STR": "Germany", "CGN": "Germany",
    "ORY": "France", "NCE": "France", "LYS": "France", "MRS": "France",
    "TLS": "France", "BOD": "France",
    "LGW": "United Kingdom", "MAN": "United Kingdom", "EDI": "United Kingdom",
    "STN": "United Kingdom",
    "EIN": "Netherlands", "RTM": "Netherlands",
    "ATH": "Greece", "IST": "Turkey",
    # Asia-Pacific
    "KIX": "Japan", "FUK": "Japan", "CTS": "Japan",
    "GMP": "South Korea", "PUS": "South Korea", "CJU": "South Korea",
    "MEL": "Australia", "BNE": "Australia",
    # Americas
    "GIG": "Brazil", "CGH": "Brazil", "GRU": "Brazil",
    "YYZ": "Canada", "YVR": "Canada",
    "MEX": "Mexico", "CUN": "Mexico",
    "SCL": "Chile",
    # Middle East / Africa
    "AUH": "UAE", "DOH": "Qatar",
    "CMN": "Morocco", "CAI": "Egypt",
    "JNB": "South Africa", "CPT": "South Africa",
}

# ============================================================================
# EVENT BUFFER CONSTANTS
# ============================================================================

_MAX_BUFFER_SIZE = 10000  # Cap to prevent unbounded memory growth

# ============================================================================
# SFO REFERENCE CENTER (for airport offset calculations)
# ============================================================================

_SFO_CENTER = (37.6213, -122.379)

# Minimum gates to avoid constant saturation with moderate flight counts
MIN_GATES_FOR_OPERATIONS = 15
MAX_OVERFLOW_STANDS = 10  # Maximum dynamically generated remote parking positions
