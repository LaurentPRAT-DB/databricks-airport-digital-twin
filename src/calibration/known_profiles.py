"""Hand-researched real statistics for major airports.

These profiles approximate real-world data from public sources (FAA ATADS,
BTS summaries, Wikipedia, airline annual reports) for the top airports.
They serve as an intermediate data source between raw BTS CSV parsing
and the generic fallback profile, providing differentiated per-airport
distributions immediately without requiring large CSV downloads.

Sources:
- FAA Air Traffic Activity Data System (ATADS)
- BTS T-100 summary statistics (public tables)
- Airline investor presentations / annual reports
- OAG / Cirium public summaries
- Wikipedia airport articles (carrier statistics sections)
"""

from __future__ import annotations

from src.calibration.profile import AirportProfile


def get_known_profile(iata: str) -> AirportProfile | None:
    """Return a hand-researched profile for a well-known airport, or None."""
    builder = _KNOWN_PROFILES.get(iata)
    if builder is None:
        return None
    return builder()


def _sfo() -> AirportProfile:
    return AirportProfile(
        icao_code="KSFO", iata_code="SFO",
        airline_shares={
            "UAL": 0.46, "SWA": 0.12, "ASA": 0.09, "DAL": 0.07,
            "AAL": 0.06, "JBU": 0.04, "BAW": 0.03, "ANA": 0.03,
            "CPA": 0.02, "UAE": 0.02, "KAL": 0.02, "SIA": 0.02,
            "EVA": 0.02,
        },
        domestic_route_shares={
            "LAX": 0.15, "ORD": 0.08, "JFK": 0.07, "SEA": 0.07,
            "DEN": 0.06, "BOS": 0.05, "DFW": 0.04, "ATL": 0.04,
            "PHX": 0.04, "LAS": 0.04, "PDX": 0.04, "SAN": 0.03,
            "EWR": 0.03, "IAH": 0.03, "MSP": 0.03, "DTW": 0.02,
            "MIA": 0.02, "CLT": 0.02, "MCO": 0.02, "PHL": 0.02,
        },
        international_route_shares={
            "LHR": 0.12, "NRT": 0.10, "ICN": 0.08, "HKG": 0.08,
            "SIN": 0.06, "SYD": 0.05, "CDG": 0.05, "FRA": 0.05,
            "AMS": 0.04, "DXB": 0.04, "GRU": 0.03,
        },
        domestic_ratio=0.72,
        fleet_mix={
            "UAL": {"B738": 0.30, "A320": 0.20, "B777": 0.15, "B787": 0.15, "E175": 0.10, "A319": 0.10},
            "SWA": {"B738": 0.70, "B737": 0.30},
            "ASA": {"B738": 0.40, "E175": 0.35, "A320": 0.25},
            "DAL": {"B738": 0.35, "A321": 0.25, "A320": 0.20, "B737": 0.20},
            "AAL": {"B738": 0.30, "A321": 0.30, "B777": 0.20, "A320": 0.20},
        },
        hourly_profile=[
            0.005, 0.003, 0.002, 0.002, 0.005, 0.015,
            0.055, 0.070, 0.075, 0.065, 0.050, 0.045,
            0.040, 0.040, 0.045, 0.050, 0.060, 0.065,
            0.070, 0.065, 0.050, 0.040, 0.025, 0.008,
        ],
        delay_rate=0.22,
        delay_distribution={
            "71": 0.25, "72": 0.10, "68": 0.20, "81": 0.18,
            "62": 0.10, "63": 0.07, "67": 0.05, "61": 0.03, "41": 0.02,
        },
        mean_delay_minutes=28.0,
        data_source="known_stats",
        sample_size=180000,
    )


def _jfk() -> AirportProfile:
    return AirportProfile(
        icao_code="KJFK", iata_code="JFK",
        airline_shares={
            "DAL": 0.24, "JBU": 0.20, "AAL": 0.12, "UAL": 0.08,
            "BAW": 0.06, "UAE": 0.05, "ANA": 0.03, "CPA": 0.03,
            "KAL": 0.03, "AFR": 0.03, "SIA": 0.02, "TAP": 0.02,
            "DLH": 0.02, "VIR": 0.02, "ELY": 0.02,
        },
        domestic_route_shares={
            "LAX": 0.14, "SFO": 0.10, "BOS": 0.07, "MIA": 0.06,
            "ORD": 0.05, "ATL": 0.05, "DFW": 0.04, "SEA": 0.04,
            "SAN": 0.04, "DEN": 0.04, "MCO": 0.04, "LAS": 0.03,
            "PHX": 0.03, "DTW": 0.03, "CLT": 0.03, "MSP": 0.02,
            "IAH": 0.02, "PHL": 0.02, "PDX": 0.02,
        },
        international_route_shares={
            "LHR": 0.15, "CDG": 0.08, "FRA": 0.06, "AMS": 0.05,
            "NRT": 0.05, "ICN": 0.05, "DXB": 0.05, "HKG": 0.04,
            "SIN": 0.03, "SYD": 0.03, "GRU": 0.04,
        },
        domestic_ratio=0.55,
        fleet_mix={
            "DAL": {"A321": 0.30, "B738": 0.25, "A330": 0.20, "B767": 0.15, "B739": 0.10},
            "JBU": {"A320": 0.45, "A321": 0.35, "E190": 0.20},
            "AAL": {"B777": 0.30, "A321": 0.25, "B738": 0.25, "B787": 0.20},
            "BAW": {"B777": 0.40, "A380": 0.30, "B787": 0.30},
            "UAE": {"A380": 0.50, "B777": 0.50},
        },
        hourly_profile=[
            0.008, 0.005, 0.003, 0.003, 0.005, 0.015,
            0.055, 0.065, 0.070, 0.060, 0.050, 0.045,
            0.042, 0.045, 0.050, 0.055, 0.065, 0.070,
            0.065, 0.058, 0.045, 0.038, 0.020, 0.010,
        ],
        delay_rate=0.28,
        delay_distribution={
            "81": 0.22, "71": 0.18, "68": 0.18, "72": 0.12,
            "62": 0.10, "63": 0.08, "67": 0.06, "61": 0.04, "41": 0.02,
        },
        mean_delay_minutes=32.0,
        data_source="known_stats",
        sample_size=200000,
    )


def _atl() -> AirportProfile:
    return AirportProfile(
        icao_code="KATL", iata_code="ATL",
        airline_shares={
            "DAL": 0.73, "SWA": 0.08, "AAL": 0.04, "UAL": 0.04,
            "ASA": 0.03, "SPI": 0.03, "JBU": 0.02, "FFT": 0.02,
        },
        domestic_route_shares={
            "ORD": 0.06, "DFW": 0.05, "LAX": 0.05, "JFK": 0.05,
            "MIA": 0.05, "MCO": 0.05, "EWR": 0.04, "BOS": 0.04,
            "DEN": 0.04, "SEA": 0.03, "SFO": 0.03, "PHX": 0.03,
            "CLT": 0.03, "MSP": 0.03, "DTW": 0.03, "LAS": 0.03,
            "IAH": 0.03, "PHL": 0.03, "SAN": 0.02, "PDX": 0.02,
        },
        international_route_shares={
            "LHR": 0.10, "CDG": 0.08, "FRA": 0.07, "AMS": 0.07,
            "NRT": 0.06, "ICN": 0.06, "GRU": 0.06,
        },
        domestic_ratio=0.82,
        fleet_mix={
            "DAL": {"B738": 0.30, "A321": 0.25, "B739": 0.15, "A320": 0.10, "B767": 0.10, "A330": 0.10},
            "SWA": {"B738": 0.70, "B737": 0.30},
        },
        hourly_profile=[
            0.003, 0.002, 0.001, 0.001, 0.005, 0.020,
            0.065, 0.075, 0.078, 0.068, 0.055, 0.048,
            0.045, 0.045, 0.048, 0.055, 0.070, 0.075,
            0.070, 0.060, 0.045, 0.035, 0.020, 0.008,
        ],
        delay_rate=0.18,
        delay_distribution={
            "71": 0.20, "68": 0.18, "81": 0.15, "72": 0.12,
            "62": 0.12, "63": 0.08, "67": 0.06, "61": 0.05, "41": 0.04,
        },
        mean_delay_minutes=22.0,
        data_source="known_stats",
        sample_size=300000,
    )


def _ord() -> AirportProfile:
    return AirportProfile(
        icao_code="KORD", iata_code="ORD",
        airline_shares={
            "UAL": 0.45, "AAL": 0.35, "SWA": 0.05, "DAL": 0.04,
            "ASA": 0.03, "SPI": 0.03, "JBU": 0.02,
        },
        domestic_route_shares={
            "LAX": 0.08, "SFO": 0.07, "JFK": 0.06, "DFW": 0.05,
            "ATL": 0.05, "DEN": 0.05, "BOS": 0.04, "MIA": 0.04,
            "SEA": 0.04, "LAS": 0.04, "MCO": 0.03, "PHX": 0.03,
            "MSP": 0.03, "DTW": 0.03, "EWR": 0.03, "CLT": 0.03,
            "IAH": 0.03, "SAN": 0.02, "PDX": 0.02, "PHL": 0.02,
        },
        international_route_shares={
            "LHR": 0.12, "NRT": 0.08, "FRA": 0.08, "CDG": 0.06,
            "AMS": 0.05, "ICN": 0.06, "HKG": 0.04, "DXB": 0.03,
        },
        domestic_ratio=0.75,
        fleet_mix={
            "UAL": {"B738": 0.30, "A320": 0.20, "B777": 0.15, "B787": 0.15, "E175": 0.10, "A319": 0.10},
            "AAL": {"B738": 0.30, "A321": 0.25, "B777": 0.15, "E175": 0.15, "A320": 0.15},
            "SWA": {"B738": 0.65, "B737": 0.35},
        },
        hourly_profile=[
            0.003, 0.002, 0.002, 0.002, 0.005, 0.018,
            0.060, 0.070, 0.075, 0.065, 0.052, 0.045,
            0.042, 0.045, 0.050, 0.055, 0.065, 0.072,
            0.068, 0.058, 0.045, 0.035, 0.020, 0.008,
        ],
        delay_rate=0.25,
        delay_distribution={
            "71": 0.22, "81": 0.20, "68": 0.16, "72": 0.14,
            "62": 0.10, "63": 0.06, "67": 0.06, "61": 0.04, "41": 0.02,
        },
        mean_delay_minutes=30.0,
        data_source="known_stats",
        sample_size=280000,
    )


def _lax() -> AirportProfile:
    return AirportProfile(
        icao_code="KLAX", iata_code="LAX",
        airline_shares={
            "DAL": 0.16, "AAL": 0.15, "UAL": 0.14, "SWA": 0.10,
            "ASA": 0.08, "JBU": 0.05, "SPI": 0.04, "BAW": 0.03,
            "ANA": 0.03, "KAL": 0.03, "SIA": 0.02, "CPA": 0.02,
            "QFA": 0.02, "UAE": 0.02, "AFR": 0.02,
        },
        domestic_route_shares={
            "SFO": 0.12, "JFK": 0.08, "ORD": 0.06, "SEA": 0.05,
            "DFW": 0.05, "ATL": 0.05, "DEN": 0.05, "LAS": 0.05,
            "PHX": 0.04, "BOS": 0.04, "MCO": 0.03, "MIA": 0.03,
            "EWR": 0.03, "IAH": 0.03, "MSP": 0.02, "CLT": 0.02,
            "SAN": 0.02, "PDX": 0.02, "DTW": 0.02,
        },
        international_route_shares={
            "NRT": 0.10, "ICN": 0.08, "LHR": 0.08, "SYD": 0.06,
            "HKG": 0.06, "CDG": 0.05, "SIN": 0.05, "FRA": 0.04,
            "AMS": 0.04, "DXB": 0.04, "GRU": 0.03,
        },
        domestic_ratio=0.65,
        fleet_mix={
            "DAL": {"A321": 0.30, "B738": 0.25, "A330": 0.20, "B777": 0.15, "B739": 0.10},
            "AAL": {"B738": 0.25, "A321": 0.25, "B777": 0.25, "B787": 0.15, "A320": 0.10},
            "UAL": {"B738": 0.25, "A320": 0.20, "B777": 0.20, "B787": 0.15, "E175": 0.10, "A319": 0.10},
            "SWA": {"B738": 0.65, "B737": 0.35},
        },
        hourly_profile=[
            0.010, 0.008, 0.005, 0.004, 0.008, 0.018,
            0.055, 0.065, 0.070, 0.062, 0.050, 0.045,
            0.042, 0.042, 0.048, 0.055, 0.062, 0.068,
            0.065, 0.058, 0.048, 0.038, 0.022, 0.012,
        ],
        delay_rate=0.20,
        delay_distribution={
            "81": 0.22, "68": 0.18, "71": 0.15, "72": 0.12,
            "62": 0.12, "63": 0.08, "67": 0.06, "61": 0.04, "41": 0.03,
        },
        mean_delay_minutes=25.0,
        data_source="known_stats",
        sample_size=250000,
    )


def _dfw() -> AirportProfile:
    return AirportProfile(
        icao_code="KDFW", iata_code="DFW",
        airline_shares={
            "AAL": 0.65, "SWA": 0.08, "UAL": 0.06, "DAL": 0.05,
            "SPI": 0.04, "ASA": 0.03, "JBU": 0.02, "BAW": 0.02,
            "KAL": 0.02, "QFA": 0.02,
        },
        domestic_route_shares={
            "LAX": 0.07, "ORD": 0.06, "ATL": 0.05, "MIA": 0.05,
            "JFK": 0.04, "DEN": 0.04, "PHX": 0.04, "SFO": 0.04,
            "LAS": 0.04, "CLT": 0.04, "SEA": 0.03, "BOS": 0.03,
            "MCO": 0.03, "EWR": 0.03, "IAH": 0.03, "MSP": 0.03,
            "DTW": 0.02, "PHL": 0.02, "SAN": 0.02, "PDX": 0.02,
        },
        international_route_shares={
            "LHR": 0.12, "NRT": 0.08, "CDG": 0.07, "FRA": 0.06,
            "ICN": 0.06, "HKG": 0.05, "GRU": 0.05, "DXB": 0.04,
        },
        domestic_ratio=0.80,
        fleet_mix={
            "AAL": {"B738": 0.30, "A321": 0.25, "B777": 0.15, "B787": 0.10, "A320": 0.10, "E175": 0.10},
            "SWA": {"B738": 0.65, "B737": 0.35},
        },
        hourly_profile=[
            0.003, 0.002, 0.002, 0.002, 0.005, 0.018,
            0.062, 0.072, 0.075, 0.065, 0.052, 0.048,
            0.045, 0.045, 0.050, 0.055, 0.065, 0.072,
            0.068, 0.060, 0.045, 0.035, 0.020, 0.008,
        ],
        delay_rate=0.20,
        delay_distribution={
            "71": 0.22, "68": 0.18, "81": 0.16, "72": 0.14,
            "62": 0.10, "63": 0.08, "67": 0.05, "61": 0.04, "41": 0.03,
        },
        mean_delay_minutes=24.0,
        data_source="known_stats",
        sample_size=270000,
    )


def _den() -> AirportProfile:
    return AirportProfile(
        icao_code="KDEN", iata_code="DEN",
        airline_shares={
            "UAL": 0.40, "SWA": 0.20, "FFT": 0.10, "DAL": 0.06,
            "AAL": 0.06, "ASA": 0.04, "SPI": 0.04, "JBU": 0.03,
        },
        domestic_route_shares={
            "LAX": 0.07, "SFO": 0.06, "ORD": 0.05, "PHX": 0.05,
            "SEA": 0.05, "DFW": 0.04, "ATL": 0.04, "LAS": 0.04,
            "JFK": 0.03, "BOS": 0.03, "MIA": 0.03, "MSP": 0.03,
            "IAH": 0.03, "SAN": 0.03, "CLT": 0.03, "MCO": 0.03,
            "DTW": 0.02, "EWR": 0.02, "PHL": 0.02, "PDX": 0.02,
        },
        international_route_shares={
            "LHR": 0.15, "FRA": 0.10, "NRT": 0.08, "CDG": 0.08,
            "ICN": 0.06, "AMS": 0.06,
        },
        domestic_ratio=0.88,
        fleet_mix={
            "UAL": {"B738": 0.30, "A320": 0.25, "E175": 0.15, "B787": 0.10, "B777": 0.10, "A319": 0.10},
            "SWA": {"B738": 0.65, "B737": 0.35},
            "FFT": {"A320": 0.50, "A321": 0.30, "A319": 0.20},
        },
        hourly_profile=[
            0.003, 0.002, 0.002, 0.002, 0.005, 0.020,
            0.065, 0.075, 0.078, 0.065, 0.052, 0.045,
            0.042, 0.045, 0.050, 0.055, 0.065, 0.072,
            0.068, 0.058, 0.042, 0.035, 0.018, 0.008,
        ],
        delay_rate=0.18,
        delay_distribution={
            "71": 0.25, "81": 0.18, "68": 0.16, "72": 0.12,
            "62": 0.10, "63": 0.07, "67": 0.05, "61": 0.04, "41": 0.03,
        },
        mean_delay_minutes=22.0,
        data_source="known_stats",
        sample_size=220000,
    )


def _sea() -> AirportProfile:
    return AirportProfile(
        icao_code="KSEA", iata_code="SEA",
        airline_shares={
            "ASA": 0.45, "DAL": 0.15, "UAL": 0.08, "SWA": 0.08,
            "AAL": 0.05, "JBU": 0.03, "KAL": 0.03, "ANA": 0.02,
            "CPA": 0.02, "EVA": 0.02, "BAW": 0.02,
        },
        domestic_route_shares={
            "LAX": 0.10, "SFO": 0.08, "PDX": 0.07, "PHX": 0.05,
            "DEN": 0.05, "LAS": 0.05, "ORD": 0.04, "JFK": 0.04,
            "SAN": 0.04, "ATL": 0.03, "DFW": 0.03, "BOS": 0.03,
            "MCO": 0.03, "MIA": 0.03, "MSP": 0.02, "IAH": 0.02,
            "EWR": 0.02, "DTW": 0.02, "CLT": 0.02, "PHL": 0.02,
        },
        international_route_shares={
            "NRT": 0.12, "ICN": 0.10, "LHR": 0.08, "HKG": 0.06,
            "SIN": 0.05, "SYD": 0.04, "CDG": 0.04, "FRA": 0.04,
        },
        domestic_ratio=0.78,
        fleet_mix={
            "ASA": {"B738": 0.35, "B739": 0.20, "E175": 0.20, "A320": 0.15, "A321": 0.10},
            "DAL": {"B738": 0.30, "A321": 0.25, "A320": 0.20, "A330": 0.15, "B767": 0.10},
        },
        hourly_profile=[
            0.005, 0.003, 0.002, 0.002, 0.005, 0.015,
            0.055, 0.068, 0.072, 0.062, 0.050, 0.045,
            0.040, 0.042, 0.048, 0.055, 0.062, 0.068,
            0.065, 0.058, 0.045, 0.035, 0.022, 0.010,
        ],
        delay_rate=0.16,
        delay_distribution={
            "71": 0.20, "68": 0.18, "81": 0.16, "72": 0.12,
            "62": 0.12, "63": 0.08, "67": 0.06, "61": 0.04, "41": 0.04,
        },
        mean_delay_minutes=20.0,
        data_source="known_stats",
        sample_size=170000,
    )


def _mia() -> AirportProfile:
    return AirportProfile(
        icao_code="KMIA", iata_code="MIA",
        airline_shares={
            "AAL": 0.68, "DAL": 0.06, "UAL": 0.05, "JBU": 0.04,
            "SPI": 0.04, "AVA": 0.03, "LAN": 0.02, "BAW": 0.02,
            "UAE": 0.02, "AFR": 0.02,
        },
        domestic_route_shares={
            "JFK": 0.08, "ATL": 0.06, "DFW": 0.06, "ORD": 0.05,
            "LAX": 0.05, "CLT": 0.05, "DEN": 0.04, "BOS": 0.04,
            "PHL": 0.04, "EWR": 0.04, "SFO": 0.03, "IAH": 0.03,
            "DTW": 0.03, "MSP": 0.03, "MCO": 0.03,
        },
        international_route_shares={
            "LHR": 0.08, "CDG": 0.06, "GRU": 0.08, "FRA": 0.05,
            "AMS": 0.04, "DXB": 0.04, "NRT": 0.03,
        },
        domestic_ratio=0.55,
        fleet_mix={
            "AAL": {"B738": 0.25, "A321": 0.25, "B777": 0.20, "B787": 0.15, "A320": 0.15},
        },
        hourly_profile=[
            0.008, 0.005, 0.003, 0.003, 0.005, 0.015,
            0.055, 0.068, 0.072, 0.062, 0.050, 0.045,
            0.042, 0.045, 0.050, 0.055, 0.062, 0.068,
            0.065, 0.058, 0.045, 0.035, 0.022, 0.010,
        ],
        delay_rate=0.22,
        delay_distribution={
            "71": 0.28, "72": 0.14, "68": 0.16, "81": 0.14,
            "62": 0.10, "63": 0.06, "67": 0.05, "61": 0.04, "41": 0.03,
        },
        mean_delay_minutes=26.0,
        data_source="known_stats",
        sample_size=160000,
    )


def _ewr() -> AirportProfile:
    return AirportProfile(
        icao_code="KEWR", iata_code="EWR",
        airline_shares={
            "UAL": 0.62, "DAL": 0.08, "JBU": 0.06, "AAL": 0.05,
            "SWA": 0.04, "SPI": 0.04, "ASA": 0.03, "SIA": 0.02,
            "BAW": 0.02, "DLH": 0.02,
        },
        domestic_route_shares={
            "LAX": 0.08, "SFO": 0.08, "ORD": 0.06, "ATL": 0.05,
            "DFW": 0.05, "MIA": 0.05, "DEN": 0.04, "BOS": 0.04,
            "SEA": 0.04, "MCO": 0.04, "PHX": 0.03, "LAS": 0.03,
            "CLT": 0.03, "IAH": 0.03, "SAN": 0.02,
        },
        international_route_shares={
            "LHR": 0.12, "FRA": 0.08, "CDG": 0.07, "NRT": 0.06,
            "AMS": 0.05, "SIN": 0.05, "ICN": 0.05, "HKG": 0.04,
            "DXB": 0.04, "GRU": 0.04,
        },
        domestic_ratio=0.60,
        fleet_mix={
            "UAL": {"B738": 0.25, "A320": 0.20, "B777": 0.18, "B787": 0.15, "E175": 0.12, "A319": 0.10},
        },
        hourly_profile=[
            0.008, 0.005, 0.003, 0.003, 0.005, 0.018,
            0.058, 0.068, 0.072, 0.062, 0.050, 0.045,
            0.042, 0.045, 0.050, 0.055, 0.062, 0.068,
            0.065, 0.058, 0.045, 0.035, 0.020, 0.010,
        ],
        delay_rate=0.30,
        delay_distribution={
            "81": 0.22, "71": 0.20, "68": 0.18, "72": 0.12,
            "62": 0.10, "63": 0.06, "67": 0.06, "61": 0.04, "41": 0.02,
        },
        mean_delay_minutes=35.0,
        data_source="known_stats",
        sample_size=150000,
    )


def _bos() -> AirportProfile:
    return AirportProfile(
        icao_code="KBOS", iata_code="BOS",
        airline_shares={
            "JBU": 0.28, "DAL": 0.20, "AAL": 0.12, "UAL": 0.10,
            "SWA": 0.08, "ASA": 0.05, "SPI": 0.04, "BAW": 0.03,
            "ACA": 0.02, "DLH": 0.02,
        },
        domestic_route_shares={
            "JFK": 0.08, "ORD": 0.06, "LAX": 0.06, "SFO": 0.05,
            "ATL": 0.05, "DFW": 0.04, "DEN": 0.04, "MIA": 0.04,
            "CLT": 0.04, "EWR": 0.04, "PHL": 0.03, "DTW": 0.03,
            "MCO": 0.03, "MSP": 0.03, "SEA": 0.03,
        },
        international_route_shares={
            "LHR": 0.15, "CDG": 0.08, "FRA": 0.06, "AMS": 0.06,
            "NRT": 0.05, "DXB": 0.04,
        },
        domestic_ratio=0.78,
        fleet_mix={
            "JBU": {"A320": 0.45, "A321": 0.35, "E190": 0.20},
            "DAL": {"B738": 0.30, "A321": 0.25, "A320": 0.20, "B739": 0.15, "A330": 0.10},
        },
        hourly_profile=[
            0.005, 0.003, 0.002, 0.002, 0.005, 0.018,
            0.060, 0.070, 0.075, 0.065, 0.050, 0.045,
            0.042, 0.045, 0.050, 0.055, 0.062, 0.068,
            0.065, 0.058, 0.045, 0.035, 0.020, 0.008,
        ],
        delay_rate=0.22,
        delay_distribution={
            "71": 0.22, "81": 0.18, "68": 0.18, "72": 0.12,
            "62": 0.10, "63": 0.08, "67": 0.06, "61": 0.04, "41": 0.02,
        },
        mean_delay_minutes=26.0,
        data_source="known_stats",
        sample_size=140000,
    )


def _lhr() -> AirportProfile:
    return AirportProfile(
        icao_code="EGLL", iata_code="LHR",
        airline_shares={
            "BAW": 0.40, "VIR": 0.05, "UAL": 0.04, "AAL": 0.04,
            "DAL": 0.03, "DLH": 0.03, "AFR": 0.03, "SIA": 0.03,
            "CPA": 0.03, "UAE": 0.03, "QFA": 0.02, "ANA": 0.02,
            "ACA": 0.02, "THY": 0.02, "TAP": 0.02,
        },
        domestic_route_shares={},
        international_route_shares={
            "JFK": 0.10, "LAX": 0.06, "DXB": 0.05, "SIN": 0.04,
            "HKG": 0.04, "NRT": 0.04, "CDG": 0.04, "FRA": 0.04,
            "AMS": 0.04, "ORD": 0.03, "SFO": 0.03, "SYD": 0.03,
            "ICN": 0.03, "BOS": 0.03, "MIA": 0.03,
        },
        domestic_ratio=0.05,
        fleet_mix={
            "BAW": {"A320": 0.20, "A321": 0.15, "B777": 0.25, "A350": 0.15, "A380": 0.10, "B787": 0.15},
            "UAE": {"A380": 0.50, "B777": 0.50},
            "SIA": {"A350": 0.40, "A380": 0.30, "B777": 0.30},
        },
        hourly_profile=[
            0.002, 0.001, 0.001, 0.001, 0.005, 0.015,
            0.055, 0.060, 0.060, 0.058, 0.055, 0.055,
            0.055, 0.055, 0.055, 0.055, 0.055, 0.055,
            0.055, 0.055, 0.050, 0.040, 0.025, 0.008,
        ],
        delay_rate=0.20,
        delay_distribution={
            "81": 0.25, "68": 0.18, "71": 0.15, "72": 0.12,
            "62": 0.10, "63": 0.08, "67": 0.05, "61": 0.04, "41": 0.03,
        },
        mean_delay_minutes=22.0,
        data_source="known_stats",
        sample_size=240000,
    )


def _dxb() -> AirportProfile:
    return AirportProfile(
        icao_code="OMDB", iata_code="DXB",
        airline_shares={
            "UAE": 0.60, "FDB": 0.12, "ETD": 0.05, "SIA": 0.03,
            "BAW": 0.03, "DLH": 0.02, "QFA": 0.02, "CPA": 0.02,
            "ANA": 0.02, "THY": 0.02,
        },
        domestic_route_shares={},
        international_route_shares={
            "LHR": 0.08, "JFK": 0.05, "SIN": 0.05, "BKK": 0.05,
            "HKG": 0.04, "CDG": 0.04, "FRA": 0.04, "NRT": 0.03,
            "SYD": 0.03, "ICN": 0.03, "BOM": 0.05, "DEL": 0.05,
            "DAC": 0.04, "CMB": 0.03, "JNB": 0.03,
        },
        domestic_ratio=0.02,
        fleet_mix={
            "UAE": {"B777": 0.50, "A380": 0.30, "B787": 0.20},
            "FDB": {"B738": 0.60, "B737": 0.40},
        },
        hourly_profile=[
            0.020, 0.025, 0.030, 0.035, 0.040, 0.035,
            0.055, 0.060, 0.060, 0.045, 0.035, 0.030,
            0.030, 0.040, 0.055, 0.060, 0.060, 0.050,
            0.035, 0.045, 0.055, 0.060, 0.045, 0.030,
        ],
        delay_rate=0.12,
        delay_distribution={
            "68": 0.22, "81": 0.18, "71": 0.12, "62": 0.15,
            "63": 0.10, "72": 0.08, "67": 0.06, "61": 0.05, "41": 0.04,
        },
        mean_delay_minutes=18.0,
        data_source="known_stats",
        sample_size=260000,
    )


def _nrt() -> AirportProfile:
    return AirportProfile(
        icao_code="RJAA", iata_code="NRT",
        airline_shares={
            "ANA": 0.25, "JAL": 0.22, "JJP": 0.08, "APJ": 0.07,
            "UAL": 0.05, "DAL": 0.04, "AAL": 0.03, "SIA": 0.03,
            "CPA": 0.03, "KAL": 0.03, "EVA": 0.03,
        },
        domestic_route_shares={},
        international_route_shares={
            "ICN": 0.10, "HKG": 0.08, "SIN": 0.06, "LAX": 0.06,
            "SFO": 0.05, "ORD": 0.04, "LHR": 0.04, "CDG": 0.04,
            "FRA": 0.04, "SYD": 0.03, "BKK": 0.05, "DXB": 0.03,
        },
        domestic_ratio=0.15,
        fleet_mix={
            "ANA": {"B777": 0.30, "B787": 0.35, "A320": 0.20, "B738": 0.15},
            "JAL": {"B777": 0.30, "B787": 0.30, "A350": 0.20, "B738": 0.20},
        },
        hourly_profile=[
            0.000, 0.000, 0.000, 0.000, 0.000, 0.005,
            0.060, 0.075, 0.080, 0.070, 0.055, 0.050,
            0.050, 0.055, 0.060, 0.070, 0.075, 0.075,
            0.065, 0.055, 0.040, 0.025, 0.010, 0.000,
        ],
        delay_rate=0.10,
        delay_distribution={
            "71": 0.20, "68": 0.18, "81": 0.15, "62": 0.15,
            "63": 0.10, "72": 0.08, "67": 0.06, "61": 0.05, "41": 0.03,
        },
        mean_delay_minutes=15.0,
        data_source="known_stats",
        sample_size=130000,
    )


def _sin() -> AirportProfile:
    return AirportProfile(
        icao_code="WSSS", iata_code="SIN",
        airline_shares={
            "SIA": 0.35, "SLK": 0.10, "JBU": 0.02, "CPA": 0.05,
            "QFA": 0.04, "UAE": 0.04, "ANA": 0.03, "BAW": 0.03,
            "DLH": 0.03, "KAL": 0.03, "THY": 0.02, "THA": 0.04,
            "MAS": 0.04, "GAI": 0.04,
        },
        domestic_route_shares={},
        international_route_shares={
            "HKG": 0.08, "NRT": 0.06, "SYD": 0.06, "LHR": 0.06,
            "ICN": 0.05, "BKK": 0.06, "DXB": 0.05, "FRA": 0.04,
            "CDG": 0.04, "AMS": 0.03, "LAX": 0.03, "SFO": 0.03,
        },
        domestic_ratio=0.02,
        fleet_mix={
            "SIA": {"A350": 0.30, "B777": 0.30, "A380": 0.20, "B787": 0.20},
        },
        hourly_profile=[
            0.025, 0.020, 0.015, 0.010, 0.012, 0.020,
            0.045, 0.055, 0.060, 0.055, 0.045, 0.040,
            0.038, 0.040, 0.045, 0.050, 0.055, 0.060,
            0.055, 0.050, 0.045, 0.040, 0.035, 0.028,
        ],
        delay_rate=0.10,
        delay_distribution={
            "68": 0.20, "81": 0.18, "71": 0.15, "62": 0.15,
            "63": 0.10, "72": 0.08, "67": 0.06, "61": 0.05, "41": 0.03,
        },
        mean_delay_minutes=15.0,
        data_source="known_stats",
        sample_size=180000,
    )


def _hkg() -> AirportProfile:
    return AirportProfile(
        icao_code="VHHH", iata_code="HKG",
        airline_shares={
            "CPA": 0.35, "HDA": 0.10, "SIA": 0.04, "UAE": 0.04,
            "BAW": 0.03, "QFA": 0.03, "ANA": 0.03, "JAL": 0.03,
            "KAL": 0.03, "DAL": 0.02, "UAL": 0.02, "AAL": 0.02,
        },
        domestic_route_shares={},
        international_route_shares={
            "NRT": 0.08, "SIN": 0.07, "ICN": 0.06, "LHR": 0.05,
            "SYD": 0.04, "DXB": 0.04, "SFO": 0.04, "LAX": 0.04,
            "FRA": 0.03, "CDG": 0.03, "BKK": 0.05, "TPE": 0.06,
        },
        domestic_ratio=0.02,
        fleet_mix={
            "CPA": {"A350": 0.35, "B777": 0.30, "A321": 0.20, "A330": 0.15},
        },
        hourly_profile=[
            0.020, 0.015, 0.010, 0.008, 0.010, 0.018,
            0.050, 0.060, 0.065, 0.058, 0.048, 0.042,
            0.040, 0.042, 0.048, 0.055, 0.060, 0.065,
            0.060, 0.055, 0.048, 0.040, 0.030, 0.022,
        ],
        delay_rate=0.14,
        delay_distribution={
            "71": 0.22, "81": 0.18, "68": 0.16, "72": 0.12,
            "62": 0.12, "63": 0.08, "67": 0.05, "61": 0.04, "41": 0.03,
        },
        mean_delay_minutes=18.0,
        data_source="known_stats",
        sample_size=200000,
    )


def _cdg() -> AirportProfile:
    return AirportProfile(
        icao_code="LFPG", iata_code="CDG",
        airline_shares={
            "AFR": 0.45, "EZY": 0.06, "DAL": 0.03, "UAL": 0.03,
            "AAL": 0.03, "BAW": 0.03, "DLH": 0.03, "SIA": 0.02,
            "UAE": 0.02, "CPA": 0.02, "ANA": 0.02, "KAL": 0.02,
        },
        domestic_route_shares={},
        international_route_shares={
            "JFK": 0.08, "LHR": 0.06, "FRA": 0.05, "AMS": 0.05,
            "NRT": 0.04, "DXB": 0.04, "HKG": 0.04, "LAX": 0.03,
            "SFO": 0.03, "SIN": 0.03, "ICN": 0.03, "GRU": 0.03,
        },
        domestic_ratio=0.15,
        fleet_mix={
            "AFR": {"A320": 0.25, "A321": 0.20, "B777": 0.20, "A350": 0.15, "A330": 0.10, "B787": 0.10},
        },
        hourly_profile=[
            0.002, 0.001, 0.001, 0.001, 0.005, 0.018,
            0.058, 0.065, 0.065, 0.060, 0.055, 0.050,
            0.050, 0.050, 0.055, 0.058, 0.060, 0.060,
            0.058, 0.052, 0.045, 0.035, 0.020, 0.008,
        ],
        delay_rate=0.18,
        delay_distribution={
            "81": 0.22, "68": 0.18, "71": 0.15, "72": 0.12,
            "62": 0.12, "63": 0.08, "67": 0.06, "61": 0.04, "41": 0.03,
        },
        mean_delay_minutes=22.0,
        data_source="known_stats",
        sample_size=220000,
    )


def _fra() -> AirportProfile:
    return AirportProfile(
        icao_code="EDDF", iata_code="FRA",
        airline_shares={
            "DLH": 0.55, "EWG": 0.05, "UAL": 0.03, "SIA": 0.03,
            "BAW": 0.02, "UAE": 0.02, "ANA": 0.02, "CPA": 0.02,
            "AAL": 0.02, "DAL": 0.02, "KAL": 0.02, "THY": 0.02,
        },
        domestic_route_shares={},
        international_route_shares={
            "LHR": 0.06, "JFK": 0.05, "CDG": 0.05, "AMS": 0.05,
            "NRT": 0.04, "SIN": 0.04, "DXB": 0.04, "HKG": 0.04,
            "ICN": 0.03, "SFO": 0.03, "ORD": 0.03, "LAX": 0.03,
        },
        domestic_ratio=0.10,
        fleet_mix={
            "DLH": {"A320": 0.25, "A321": 0.20, "B747": 0.10, "A350": 0.15, "A330": 0.15, "B777": 0.15},
        },
        hourly_profile=[
            0.002, 0.001, 0.001, 0.001, 0.005, 0.018,
            0.058, 0.065, 0.068, 0.060, 0.055, 0.052,
            0.050, 0.050, 0.055, 0.058, 0.060, 0.062,
            0.058, 0.052, 0.045, 0.035, 0.020, 0.008,
        ],
        delay_rate=0.18,
        delay_distribution={
            "81": 0.20, "68": 0.18, "71": 0.16, "72": 0.12,
            "62": 0.12, "63": 0.08, "67": 0.06, "61": 0.04, "41": 0.04,
        },
        mean_delay_minutes=22.0,
        data_source="known_stats",
        sample_size=210000,
    )


def _ams() -> AirportProfile:
    return AirportProfile(
        icao_code="EHAM", iata_code="AMS",
        airline_shares={
            "KLM": 0.50, "TRA": 0.08, "EZY": 0.05, "DAL": 0.03,
            "UAL": 0.03, "BAW": 0.03, "DLH": 0.02, "SIA": 0.02,
            "CPA": 0.02, "UAE": 0.02, "ANA": 0.02,
        },
        domestic_route_shares={},
        international_route_shares={
            "LHR": 0.07, "JFK": 0.05, "CDG": 0.05, "FRA": 0.05,
            "NRT": 0.04, "SIN": 0.04, "DXB": 0.04, "HKG": 0.03,
            "ICN": 0.03, "SFO": 0.03, "LAX": 0.03, "ORD": 0.03,
        },
        domestic_ratio=0.05,
        fleet_mix={
            "KLM": {"B738": 0.25, "A321": 0.15, "B777": 0.20, "B787": 0.15, "A330": 0.15, "E190": 0.10},
        },
        hourly_profile=[
            0.002, 0.001, 0.001, 0.001, 0.005, 0.015,
            0.055, 0.062, 0.065, 0.060, 0.055, 0.050,
            0.050, 0.050, 0.055, 0.058, 0.060, 0.062,
            0.058, 0.052, 0.045, 0.035, 0.022, 0.008,
        ],
        delay_rate=0.16,
        delay_distribution={
            "81": 0.20, "68": 0.18, "71": 0.16, "72": 0.12,
            "62": 0.12, "63": 0.08, "67": 0.06, "61": 0.04, "41": 0.04,
        },
        mean_delay_minutes=20.0,
        data_source="known_stats",
        sample_size=200000,
    )


def _syd() -> AirportProfile:
    return AirportProfile(
        icao_code="YSSY", iata_code="SYD",
        airline_shares={
            "QFA": 0.30, "VOZ": 0.20, "JST": 0.12, "SIA": 0.04,
            "UAE": 0.04, "CPA": 0.03, "ANA": 0.02, "UAL": 0.02,
            "DAL": 0.02, "AAL": 0.02, "BAW": 0.02,
        },
        domestic_route_shares={
            "MEL": 0.20, "BNE": 0.15, "PER": 0.10, "ADL": 0.08,
            "CBR": 0.06, "GC": 0.05,
        },
        international_route_shares={
            "SIN": 0.10, "HKG": 0.08, "NRT": 0.07, "LHR": 0.07,
            "LAX": 0.06, "AKL": 0.06, "DXB": 0.05, "ICN": 0.04,
            "SFO": 0.04,
        },
        domestic_ratio=0.55,
        fleet_mix={
            "QFA": {"A330": 0.25, "B738": 0.25, "A380": 0.15, "B787": 0.15, "B737": 0.20},
            "VOZ": {"B738": 0.50, "B737": 0.30, "A320": 0.20},
        },
        hourly_profile=[
            0.000, 0.000, 0.000, 0.000, 0.000, 0.008,
            0.060, 0.072, 0.078, 0.068, 0.055, 0.048,
            0.045, 0.048, 0.055, 0.062, 0.068, 0.072,
            0.065, 0.055, 0.042, 0.030, 0.015, 0.002,
        ],
        delay_rate=0.14,
        delay_distribution={
            "71": 0.18, "68": 0.18, "81": 0.16, "72": 0.12,
            "62": 0.12, "63": 0.08, "67": 0.06, "61": 0.05, "41": 0.05,
        },
        mean_delay_minutes=18.0,
        data_source="known_stats",
        sample_size=160000,
    )


def _icn() -> AirportProfile:
    return AirportProfile(
        icao_code="RKSI", iata_code="ICN",
        airline_shares={
            "KAL": 0.30, "AAR": 0.20, "JNA": 0.08, "TWB": 0.06,
            "SIA": 0.03, "CPA": 0.03, "ANA": 0.03, "JAL": 0.03,
            "UAE": 0.03, "UAL": 0.02, "DAL": 0.02, "AAL": 0.02,
        },
        domestic_route_shares={},
        international_route_shares={
            "NRT": 0.10, "HKG": 0.07, "SIN": 0.06, "SFO": 0.04,
            "LAX": 0.04, "LHR": 0.04, "CDG": 0.03, "FRA": 0.03,
            "DXB": 0.03, "SYD": 0.03, "BKK": 0.05, "ORD": 0.03,
        },
        domestic_ratio=0.10,
        fleet_mix={
            "KAL": {"B777": 0.30, "A330": 0.20, "B787": 0.20, "A321": 0.15, "B738": 0.15},
            "AAR": {"A321": 0.30, "A330": 0.25, "B738": 0.25, "A320": 0.20},
        },
        hourly_profile=[
            0.010, 0.008, 0.005, 0.005, 0.008, 0.018,
            0.055, 0.065, 0.070, 0.060, 0.050, 0.045,
            0.042, 0.045, 0.050, 0.055, 0.062, 0.068,
            0.065, 0.058, 0.048, 0.040, 0.028, 0.015,
        ],
        delay_rate=0.12,
        delay_distribution={
            "71": 0.18, "68": 0.18, "81": 0.16, "72": 0.12,
            "62": 0.12, "63": 0.08, "67": 0.06, "61": 0.05, "41": 0.05,
        },
        mean_delay_minutes=16.0,
        data_source="known_stats",
        sample_size=190000,
    )


def _gru() -> AirportProfile:
    return AirportProfile(
        icao_code="SBGR", iata_code="GRU",
        airline_shares={
            "TAM": 0.35, "GLO": 0.25, "AZU": 0.15, "UAE": 0.03,
            "AFR": 0.03, "BAW": 0.02, "DAL": 0.02, "UAL": 0.02,
            "AAL": 0.02, "CPA": 0.02, "DLH": 0.02,
        },
        domestic_route_shares={
            "CGH": 0.12, "BSB": 0.08, "SSA": 0.07, "REC": 0.06,
            "CNF": 0.06, "POA": 0.05, "CWB": 0.05, "FOR": 0.04,
        },
        international_route_shares={
            "JFK": 0.08, "MIA": 0.07, "LHR": 0.06, "CDG": 0.06,
            "FRA": 0.05, "AMS": 0.04, "DXB": 0.04, "LAX": 0.03,
        },
        domestic_ratio=0.60,
        fleet_mix={
            "TAM": {"A320": 0.30, "A321": 0.20, "B777": 0.15, "B787": 0.15, "A350": 0.10, "A319": 0.10},
            "GLO": {"B738": 0.60, "B737": 0.40},
        },
        hourly_profile=[
            0.008, 0.005, 0.003, 0.003, 0.005, 0.015,
            0.055, 0.065, 0.070, 0.060, 0.050, 0.045,
            0.042, 0.045, 0.050, 0.055, 0.062, 0.068,
            0.065, 0.058, 0.045, 0.035, 0.020, 0.010,
        ],
        delay_rate=0.22,
        delay_distribution={
            "71": 0.20, "68": 0.18, "81": 0.16, "72": 0.14,
            "62": 0.10, "63": 0.08, "67": 0.06, "61": 0.04, "41": 0.04,
        },
        mean_delay_minutes=28.0,
        data_source="known_stats",
        sample_size=150000,
    )


def _jnb() -> AirportProfile:
    return AirportProfile(
        icao_code="FAOR", iata_code="JNB",
        airline_shares={
            "SAA": 0.35, "MNX": 0.15, "CAW": 0.10, "FAS": 0.08,
            "UAE": 0.05, "BAW": 0.04, "DLH": 0.03, "AFR": 0.03,
            "SIA": 0.03, "CPA": 0.02, "QFA": 0.02,
        },
        domestic_route_shares={
            "CPT": 0.25, "DUR": 0.15, "PLZ": 0.06, "ELS": 0.05,
            "BFN": 0.04,
        },
        international_route_shares={
            "LHR": 0.10, "DXB": 0.08, "FRA": 0.06, "CDG": 0.05,
            "AMS": 0.05, "NRT": 0.04, "SIN": 0.04, "HKG": 0.04,
        },
        domestic_ratio=0.50,
        fleet_mix={
            "SAA": {"A320": 0.25, "A330": 0.20, "B738": 0.20, "A340": 0.15, "A319": 0.10, "B737": 0.10},
        },
        hourly_profile=[
            0.005, 0.003, 0.002, 0.002, 0.005, 0.018,
            0.058, 0.068, 0.072, 0.062, 0.050, 0.045,
            0.042, 0.045, 0.050, 0.055, 0.062, 0.068,
            0.065, 0.058, 0.045, 0.035, 0.020, 0.010,
        ],
        delay_rate=0.16,
        delay_distribution={
            "71": 0.18, "68": 0.20, "81": 0.16, "72": 0.10,
            "62": 0.12, "63": 0.08, "67": 0.06, "61": 0.05, "41": 0.05,
        },
        mean_delay_minutes=20.0,
        data_source="known_stats",
        sample_size=100000,
    )


# Remaining US airports with less detailed but still differentiated profiles

def _phx() -> AirportProfile:
    return AirportProfile(
        icao_code="KPHX", iata_code="PHX",
        airline_shares={"AAL": 0.40, "SWA": 0.30, "UAL": 0.08, "DAL": 0.06, "ASA": 0.05, "FFT": 0.05, "JBU": 0.03, "SPI": 0.03},
        domestic_route_shares={"LAX": 0.08, "DEN": 0.07, "DFW": 0.06, "LAS": 0.06, "SFO": 0.05, "ORD": 0.05, "SEA": 0.04, "ATL": 0.04, "MSP": 0.03, "SAN": 0.03},
        international_route_shares={"LHR": 0.15, "CDG": 0.10},
        domestic_ratio=0.92, delay_rate=0.14, mean_delay_minutes=18.0,
        delay_distribution={"71": 0.15, "68": 0.18, "81": 0.16, "72": 0.10, "62": 0.12, "63": 0.10, "67": 0.08, "61": 0.06, "41": 0.05},
        fleet_mix={"AAL": {"B738": 0.35, "A321": 0.30, "A320": 0.20, "E175": 0.15}, "SWA": {"B738": 0.65, "B737": 0.35}},
        hourly_profile=[0.003, 0.002, 0.002, 0.002, 0.005, 0.020, 0.065, 0.075, 0.078, 0.065, 0.052, 0.045, 0.042, 0.045, 0.050, 0.055, 0.065, 0.072, 0.068, 0.058, 0.042, 0.035, 0.018, 0.008],
        data_source="known_stats", sample_size=140000,
    )


def _las() -> AirportProfile:
    return AirportProfile(
        icao_code="KLAS", iata_code="LAS",
        airline_shares={"SWA": 0.30, "SPI": 0.12, "UAL": 0.10, "DAL": 0.08, "AAL": 0.08, "ASA": 0.06, "JBU": 0.05, "FFT": 0.05},
        domestic_route_shares={"LAX": 0.10, "SFO": 0.07, "DEN": 0.06, "PHX": 0.05, "SEA": 0.05, "ORD": 0.04, "DFW": 0.04, "ATL": 0.04, "JFK": 0.03, "BOS": 0.03},
        international_route_shares={"LHR": 0.15, "CDG": 0.08},
        domestic_ratio=0.93, delay_rate=0.14, mean_delay_minutes=18.0,
        delay_distribution={"71": 0.12, "68": 0.20, "81": 0.18, "72": 0.08, "62": 0.12, "63": 0.10, "67": 0.08, "61": 0.06, "41": 0.06},
        fleet_mix={"SWA": {"B738": 0.65, "B737": 0.35}, "SPI": {"A320": 0.50, "A321": 0.30, "A319": 0.20}},
        hourly_profile=[0.005, 0.003, 0.002, 0.002, 0.005, 0.018, 0.055, 0.065, 0.070, 0.062, 0.050, 0.045, 0.042, 0.045, 0.050, 0.055, 0.065, 0.070, 0.068, 0.060, 0.048, 0.038, 0.025, 0.012],
        data_source="known_stats", sample_size=150000,
    )


def _mco() -> AirportProfile:
    return AirportProfile(
        icao_code="KMCO", iata_code="MCO",
        airline_shares={"SWA": 0.22, "JBU": 0.12, "DAL": 0.10, "UAL": 0.10, "AAL": 0.10, "SPI": 0.10, "FFT": 0.08, "ASA": 0.05},
        domestic_route_shares={"ATL": 0.07, "JFK": 0.06, "ORD": 0.05, "DFW": 0.05, "BOS": 0.05, "PHL": 0.04, "EWR": 0.04, "DEN": 0.04, "CLT": 0.04, "DTW": 0.03},
        international_route_shares={"LHR": 0.12, "CDG": 0.08},
        domestic_ratio=0.88, delay_rate=0.16, mean_delay_minutes=20.0,
        delay_distribution={"71": 0.22, "68": 0.16, "81": 0.14, "72": 0.14, "62": 0.12, "63": 0.08, "67": 0.06, "61": 0.04, "41": 0.04},
        fleet_mix={"SWA": {"B738": 0.65, "B737": 0.35}, "JBU": {"A320": 0.45, "A321": 0.35, "E190": 0.20}},
        hourly_profile=[0.005, 0.003, 0.002, 0.002, 0.005, 0.018, 0.058, 0.068, 0.072, 0.062, 0.050, 0.045, 0.042, 0.045, 0.050, 0.055, 0.062, 0.068, 0.065, 0.058, 0.045, 0.035, 0.022, 0.010],
        data_source="known_stats", sample_size=160000,
    )


def _clt() -> AirportProfile:
    return AirportProfile(
        icao_code="KCLT", iata_code="CLT",
        airline_shares={"AAL": 0.72, "DAL": 0.05, "UAL": 0.05, "SWA": 0.04, "JBU": 0.03, "SPI": 0.03, "ASA": 0.03},
        domestic_route_shares={"ATL": 0.06, "ORD": 0.05, "DFW": 0.05, "JFK": 0.05, "LAX": 0.04, "BOS": 0.04, "MIA": 0.04, "DEN": 0.04, "EWR": 0.04, "PHL": 0.04},
        international_route_shares={"LHR": 0.15, "CDG": 0.08, "FRA": 0.06},
        domestic_ratio=0.85, delay_rate=0.16, mean_delay_minutes=20.0,
        delay_distribution={"68": 0.20, "71": 0.18, "81": 0.16, "72": 0.12, "62": 0.10, "63": 0.08, "67": 0.06, "61": 0.05, "41": 0.05},
        fleet_mix={"AAL": {"A321": 0.30, "B738": 0.25, "E175": 0.20, "A320": 0.15, "B777": 0.10}},
        hourly_profile=[0.003, 0.002, 0.002, 0.002, 0.005, 0.020, 0.065, 0.075, 0.078, 0.065, 0.052, 0.045, 0.042, 0.045, 0.050, 0.055, 0.065, 0.072, 0.068, 0.058, 0.042, 0.035, 0.018, 0.008],
        data_source="known_stats", sample_size=160000,
    )


def _msp() -> AirportProfile:
    return AirportProfile(
        icao_code="KMSP", iata_code="MSP",
        airline_shares={"DAL": 0.60, "SWA": 0.10, "UAL": 0.06, "AAL": 0.05, "SPI": 0.05, "SUN": 0.04, "ASA": 0.03, "FFT": 0.03},
        domestic_route_shares={"ORD": 0.06, "ATL": 0.05, "DFW": 0.05, "DEN": 0.05, "LAX": 0.04, "JFK": 0.04, "SEA": 0.04, "PHX": 0.04, "LAS": 0.03, "SFO": 0.03},
        international_route_shares={"LHR": 0.12, "CDG": 0.08, "NRT": 0.06, "ICN": 0.06},
        domestic_ratio=0.88, delay_rate=0.16, mean_delay_minutes=20.0,
        delay_distribution={"71": 0.22, "68": 0.18, "81": 0.16, "72": 0.12, "62": 0.10, "63": 0.08, "67": 0.06, "61": 0.04, "41": 0.04},
        fleet_mix={"DAL": {"B738": 0.30, "A321": 0.25, "A320": 0.15, "B739": 0.15, "A330": 0.10, "E175": 0.05}},
        hourly_profile=[0.003, 0.002, 0.002, 0.002, 0.005, 0.020, 0.065, 0.075, 0.078, 0.065, 0.052, 0.045, 0.042, 0.045, 0.050, 0.055, 0.065, 0.072, 0.068, 0.058, 0.042, 0.035, 0.018, 0.008],
        data_source="known_stats", sample_size=130000,
    )


def _dtw() -> AirportProfile:
    return AirportProfile(
        icao_code="KDTW", iata_code="DTW",
        airline_shares={"DAL": 0.65, "SWA": 0.08, "UAL": 0.06, "AAL": 0.05, "SPI": 0.05, "ASA": 0.03, "JBU": 0.02},
        domestic_route_shares={"ATL": 0.06, "ORD": 0.05, "LAX": 0.05, "DFW": 0.05, "JFK": 0.04, "DEN": 0.04, "MSP": 0.04, "SFO": 0.04, "BOS": 0.03, "MIA": 0.03},
        international_route_shares={"LHR": 0.12, "CDG": 0.08, "FRA": 0.08, "NRT": 0.06, "ICN": 0.06, "AMS": 0.05},
        domestic_ratio=0.82, delay_rate=0.18, mean_delay_minutes=22.0,
        delay_distribution={"71": 0.22, "68": 0.18, "81": 0.16, "72": 0.12, "62": 0.10, "63": 0.08, "67": 0.06, "61": 0.04, "41": 0.04},
        fleet_mix={"DAL": {"B738": 0.30, "A321": 0.25, "A320": 0.15, "B739": 0.15, "A330": 0.10, "B767": 0.05}},
        hourly_profile=[0.003, 0.002, 0.002, 0.002, 0.005, 0.020, 0.065, 0.075, 0.078, 0.065, 0.052, 0.045, 0.042, 0.045, 0.050, 0.055, 0.065, 0.072, 0.068, 0.058, 0.042, 0.035, 0.018, 0.008],
        data_source="known_stats", sample_size=120000,
    )


def _phl() -> AirportProfile:
    return AirportProfile(
        icao_code="KPHL", iata_code="PHL",
        airline_shares={"AAL": 0.55, "SWA": 0.12, "SPI": 0.08, "UAL": 0.06, "DAL": 0.05, "JBU": 0.04, "FFT": 0.04, "ASA": 0.03},
        domestic_route_shares={"ATL": 0.06, "ORD": 0.05, "DFW": 0.05, "BOS": 0.05, "CLT": 0.05, "MIA": 0.04, "DEN": 0.04, "MCO": 0.04, "LAX": 0.04, "SFO": 0.03},
        international_route_shares={"LHR": 0.15, "CDG": 0.08, "FRA": 0.06},
        domestic_ratio=0.82, delay_rate=0.24, mean_delay_minutes=28.0,
        delay_distribution={"71": 0.20, "81": 0.20, "68": 0.18, "72": 0.12, "62": 0.10, "63": 0.08, "67": 0.06, "61": 0.04, "41": 0.02},
        fleet_mix={"AAL": {"A321": 0.30, "B738": 0.25, "E175": 0.20, "A320": 0.15, "B777": 0.10}},
        hourly_profile=[0.003, 0.002, 0.002, 0.002, 0.005, 0.020, 0.065, 0.075, 0.078, 0.065, 0.052, 0.045, 0.042, 0.045, 0.050, 0.055, 0.065, 0.072, 0.068, 0.058, 0.042, 0.035, 0.018, 0.008],
        data_source="known_stats", sample_size=110000,
    )


def _iah() -> AirportProfile:
    return AirportProfile(
        icao_code="KIAH", iata_code="IAH",
        airline_shares={"UAL": 0.70, "SWA": 0.06, "SPI": 0.05, "DAL": 0.04, "AAL": 0.04, "ASA": 0.03, "JBU": 0.02, "UAE": 0.02},
        domestic_route_shares={"DFW": 0.06, "LAX": 0.05, "ORD": 0.05, "DEN": 0.05, "ATL": 0.04, "SFO": 0.04, "MIA": 0.04, "JFK": 0.04, "LAS": 0.03, "SEA": 0.03},
        international_route_shares={"LHR": 0.10, "NRT": 0.06, "FRA": 0.06, "CDG": 0.05, "AMS": 0.05, "GRU": 0.05},
        domestic_ratio=0.75, delay_rate=0.20, mean_delay_minutes=24.0,
        delay_distribution={"71": 0.22, "68": 0.18, "81": 0.16, "72": 0.12, "62": 0.10, "63": 0.08, "67": 0.06, "61": 0.04, "41": 0.04},
        fleet_mix={"UAL": {"B738": 0.25, "A320": 0.20, "B777": 0.18, "B787": 0.15, "E175": 0.12, "A319": 0.10}},
        hourly_profile=[0.003, 0.002, 0.002, 0.002, 0.005, 0.020, 0.065, 0.075, 0.078, 0.065, 0.052, 0.045, 0.042, 0.045, 0.050, 0.055, 0.065, 0.072, 0.068, 0.058, 0.042, 0.035, 0.018, 0.008],
        data_source="known_stats", sample_size=140000,
    )


def _san() -> AirportProfile:
    return AirportProfile(
        icao_code="KSAN", iata_code="SAN",
        airline_shares={"SWA": 0.30, "UAL": 0.12, "DAL": 0.10, "AAL": 0.10, "ASA": 0.08, "JBU": 0.06, "SPI": 0.06, "FFT": 0.05, "HAL": 0.03},
        domestic_route_shares={"LAX": 0.08, "SFO": 0.07, "DEN": 0.06, "SEA": 0.05, "PHX": 0.05, "ORD": 0.04, "DFW": 0.04, "JFK": 0.04, "ATL": 0.04, "LAS": 0.04},
        international_route_shares={"NRT": 0.12, "LHR": 0.10},
        domestic_ratio=0.92, delay_rate=0.12, mean_delay_minutes=16.0,
        delay_distribution={"68": 0.20, "81": 0.18, "71": 0.15, "62": 0.12, "72": 0.10, "63": 0.10, "67": 0.06, "61": 0.05, "41": 0.04},
        fleet_mix={"SWA": {"B738": 0.65, "B737": 0.35}},
        hourly_profile=[0.003, 0.002, 0.002, 0.002, 0.005, 0.020, 0.062, 0.072, 0.075, 0.065, 0.052, 0.045, 0.042, 0.045, 0.050, 0.055, 0.065, 0.072, 0.068, 0.058, 0.042, 0.035, 0.018, 0.008],
        data_source="known_stats", sample_size=80000,
    )


def _pdx() -> AirportProfile:
    return AirportProfile(
        icao_code="KPDX", iata_code="PDX",
        airline_shares={"ASA": 0.35, "SWA": 0.18, "DAL": 0.10, "UAL": 0.08, "AAL": 0.06, "JBU": 0.05, "SPI": 0.05, "FFT": 0.04, "HAL": 0.03},
        domestic_route_shares={"LAX": 0.08, "SFO": 0.08, "SEA": 0.07, "DEN": 0.06, "LAS": 0.05, "PHX": 0.05, "ORD": 0.04, "DFW": 0.04, "ATL": 0.04, "SAN": 0.03},
        international_route_shares={"NRT": 0.15, "LHR": 0.10},
        domestic_ratio=0.92, delay_rate=0.12, mean_delay_minutes=16.0,
        delay_distribution={"71": 0.18, "68": 0.20, "81": 0.16, "72": 0.10, "62": 0.12, "63": 0.08, "67": 0.06, "61": 0.05, "41": 0.05},
        fleet_mix={"ASA": {"B738": 0.35, "B739": 0.20, "E175": 0.20, "A320": 0.15, "A321": 0.10}},
        hourly_profile=[0.003, 0.002, 0.002, 0.002, 0.005, 0.018, 0.058, 0.068, 0.072, 0.062, 0.050, 0.045, 0.042, 0.045, 0.050, 0.055, 0.062, 0.068, 0.065, 0.058, 0.045, 0.035, 0.020, 0.008],
        data_source="known_stats", sample_size=70000,
    )


# Registry of all known airports
_KNOWN_PROFILES: dict[str, callable] = {
    "SFO": _sfo, "JFK": _jfk, "ATL": _atl, "ORD": _ord, "LAX": _lax,
    "DFW": _dfw, "DEN": _den, "SEA": _sea, "MIA": _mia, "EWR": _ewr,
    "BOS": _bos, "PHX": _phx, "LAS": _las, "MCO": _mco, "CLT": _clt,
    "MSP": _msp, "DTW": _dtw, "PHL": _phl, "IAH": _iah, "SAN": _san,
    "PDX": _pdx,
    "LHR": _lhr, "DXB": _dxb, "NRT": _nrt, "SIN": _sin, "HKG": _hkg,
    "CDG": _cdg, "FRA": _fra, "AMS": _ams, "SYD": _syd, "ICN": _icn,
    "GRU": _gru, "JNB": _jnb,
}


def list_known_airports() -> list[str]:
    """Return list of IATA codes with known profiles."""
    return sorted(_KNOWN_PROFILES.keys())
