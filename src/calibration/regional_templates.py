"""Regional templates for airport calibration.

Provides region-specific defaults for delay stats, hourly profiles, and
domestic ratios. These templates are derived from averaging the 33
hand-researched known airport profiles grouped by geographic region.

Used as a fallback when no real data is available for an airport —
a European airport gets European delay patterns, a Middle Eastern airport
gets Middle Eastern traffic patterns, etc.
"""

from __future__ import annotations


# ISO 3166-1 alpha-2 country code → region name
COUNTRY_TO_REGION: dict[str, str] = {
    # North America
    "US": "north_america", "CA": "north_america",
    # Central America & Caribbean
    "MX": "central_america", "GT": "central_america", "HN": "central_america",
    "SV": "central_america", "NI": "central_america", "CR": "central_america",
    "PA": "central_america", "CU": "central_america", "DO": "central_america",
    "JM": "central_america", "TT": "central_america", "BS": "central_america",
    "BB": "central_america", "PR": "central_america",
    # South America
    "BR": "south_america", "AR": "south_america", "CL": "south_america",
    "CO": "south_america", "PE": "south_america", "VE": "south_america",
    "EC": "south_america", "BO": "south_america", "PY": "south_america",
    "UY": "south_america",
    # Western Europe
    "GB": "europe_west", "IE": "europe_west", "FR": "europe_west",
    "DE": "europe_west", "NL": "europe_west", "BE": "europe_west",
    "LU": "europe_west", "CH": "europe_west", "AT": "europe_west",
    "DK": "europe_west", "SE": "europe_west", "NO": "europe_west",
    "FI": "europe_west", "IS": "europe_west",
    # Southern Europe
    "ES": "europe_south", "PT": "europe_south", "IT": "europe_south",
    "GR": "europe_south", "HR": "europe_south", "SI": "europe_south",
    "MT": "europe_south", "CY": "europe_south", "AL": "europe_south",
    "ME": "europe_south", "MK": "europe_south", "RS": "europe_south",
    "BA": "europe_south", "BG": "europe_south", "RO": "europe_south",
    # Eastern Europe
    "PL": "europe_west", "CZ": "europe_west", "SK": "europe_west",
    "HU": "europe_west", "LT": "europe_west", "LV": "europe_west",
    "EE": "europe_west",
    # Turkey (straddles Europe/Middle East)
    "TR": "middle_east",
    # Middle East
    "AE": "middle_east", "SA": "middle_east", "QA": "middle_east",
    "BH": "middle_east", "KW": "middle_east", "OM": "middle_east",
    "IL": "middle_east", "JO": "middle_east", "LB": "middle_east",
    "IQ": "middle_east", "IR": "middle_east",
    # East Asia
    "JP": "east_asia", "KR": "east_asia", "CN": "east_asia",
    "TW": "east_asia", "HK": "east_asia", "MO": "east_asia",
    "MN": "east_asia",
    # Southeast Asia
    "SG": "southeast_asia", "TH": "southeast_asia", "MY": "southeast_asia",
    "ID": "southeast_asia", "PH": "southeast_asia", "VN": "southeast_asia",
    "MM": "southeast_asia", "KH": "southeast_asia", "LA": "southeast_asia",
    "BN": "southeast_asia",
    # South Asia
    "IN": "southeast_asia", "PK": "southeast_asia", "BD": "southeast_asia",
    "LK": "southeast_asia", "NP": "southeast_asia",
    # Oceania
    "AU": "oceania", "NZ": "oceania", "FJ": "oceania", "PG": "oceania",
    "NC": "oceania", "PF": "oceania",
    # Africa
    "ZA": "africa", "MA": "africa", "EG": "africa", "NG": "africa",
    "KE": "africa", "ET": "africa", "TZ": "africa", "GH": "africa",
    "SN": "africa", "CI": "africa", "CM": "africa", "DZ": "africa",
    "TN": "africa", "LY": "africa", "AO": "africa", "MZ": "africa",
    "UG": "africa", "RW": "africa", "MU": "africa",
}


# Regional templates with averaged statistics from known airports
REGION_TEMPLATES: dict[str, dict] = {
    "north_america": {
        "domestic_ratio": 0.78,
        "delay_rate": 0.20,
        "mean_delay_minutes": 24.0,
        "delay_distribution": {
            "71": 0.20, "68": 0.18, "81": 0.16, "72": 0.12,
            "62": 0.10, "63": 0.08, "67": 0.06, "61": 0.04, "41": 0.04,
        },
        "hourly_profile": [
            0.004, 0.002, 0.002, 0.002, 0.005, 0.018,
            0.060, 0.072, 0.076, 0.064, 0.052, 0.046,
            0.042, 0.045, 0.050, 0.055, 0.064, 0.071,
            0.067, 0.058, 0.044, 0.035, 0.020, 0.008,
        ],
    },
    "europe_west": {
        "domestic_ratio": 0.10,
        "delay_rate": 0.18,
        "mean_delay_minutes": 21.0,
        "delay_distribution": {
            "81": 0.20, "68": 0.18, "71": 0.16, "72": 0.12,
            "62": 0.12, "63": 0.08, "67": 0.06, "61": 0.04, "41": 0.04,
        },
        "hourly_profile": [
            0.002, 0.001, 0.001, 0.001, 0.005, 0.017,
            0.057, 0.064, 0.066, 0.060, 0.054, 0.050,
            0.048, 0.050, 0.054, 0.057, 0.060, 0.062,
            0.058, 0.053, 0.045, 0.035, 0.021, 0.008,
        ],
    },
    "europe_south": {
        "domestic_ratio": 0.35,
        "delay_rate": 0.18,
        "mean_delay_minutes": 22.0,
        "delay_distribution": {
            "81": 0.20, "68": 0.18, "71": 0.16, "72": 0.12,
            "62": 0.12, "63": 0.08, "67": 0.06, "61": 0.04, "41": 0.04,
        },
        "hourly_profile": [
            0.002, 0.001, 0.001, 0.001, 0.005, 0.018,
            0.058, 0.068, 0.072, 0.062, 0.050, 0.045,
            0.042, 0.045, 0.050, 0.056, 0.063, 0.069,
            0.066, 0.058, 0.045, 0.035, 0.020, 0.008,
        ],
    },
    "middle_east": {
        "domestic_ratio": 0.02,
        "delay_rate": 0.11,
        "mean_delay_minutes": 17.0,
        "delay_distribution": {
            "68": 0.22, "81": 0.18, "71": 0.12, "62": 0.15,
            "63": 0.10, "72": 0.08, "67": 0.06, "61": 0.05, "41": 0.04,
        },
        "hourly_profile": [
            0.020, 0.025, 0.030, 0.035, 0.039, 0.035,
            0.052, 0.059, 0.059, 0.045, 0.035, 0.030,
            0.030, 0.039, 0.052, 0.057, 0.059, 0.049,
            0.035, 0.043, 0.052, 0.057, 0.043, 0.030,
        ],
    },
    "east_asia": {
        "domestic_ratio": 0.40,
        "delay_rate": 0.14,
        "mean_delay_minutes": 18.0,
        "delay_distribution": {
            "71": 0.20, "68": 0.18, "81": 0.16, "72": 0.10,
            "62": 0.12, "63": 0.10, "67": 0.06, "61": 0.05, "41": 0.03,
        },
        "hourly_profile": [
            0.004, 0.003, 0.002, 0.002, 0.004, 0.012,
            0.058, 0.072, 0.076, 0.066, 0.054, 0.048,
            0.044, 0.048, 0.054, 0.064, 0.070, 0.076,
            0.068, 0.058, 0.044, 0.030, 0.014, 0.004,
        ],
    },
    "southeast_asia": {
        "domestic_ratio": 0.20,
        "delay_rate": 0.12,
        "mean_delay_minutes": 16.0,
        "delay_distribution": {
            "71": 0.20, "68": 0.18, "81": 0.16, "72": 0.12,
            "62": 0.12, "63": 0.08, "67": 0.06, "61": 0.04, "41": 0.04,
        },
        "hourly_profile": [
            0.022, 0.019, 0.015, 0.010, 0.012, 0.020,
            0.048, 0.058, 0.062, 0.056, 0.046, 0.041,
            0.039, 0.041, 0.046, 0.052, 0.058, 0.062,
            0.058, 0.052, 0.046, 0.041, 0.035, 0.026,
        ],
    },
    "south_america": {
        "domestic_ratio": 0.58,
        "delay_rate": 0.22,
        "mean_delay_minutes": 28.0,
        "delay_distribution": {
            "71": 0.20, "68": 0.18, "81": 0.16, "72": 0.14,
            "62": 0.10, "63": 0.08, "67": 0.06, "61": 0.04, "41": 0.04,
        },
        "hourly_profile": [
            0.008, 0.005, 0.003, 0.003, 0.005, 0.015,
            0.055, 0.065, 0.070, 0.060, 0.050, 0.045,
            0.042, 0.045, 0.050, 0.055, 0.062, 0.068,
            0.065, 0.058, 0.045, 0.035, 0.020, 0.010,
        ],
    },
    "central_america": {
        "domestic_ratio": 0.50,
        "delay_rate": 0.20,
        "mean_delay_minutes": 24.0,
        "delay_distribution": {
            "81": 0.20, "68": 0.18, "71": 0.16, "72": 0.12,
            "62": 0.12, "63": 0.08, "67": 0.06, "61": 0.04, "41": 0.04,
        },
        "hourly_profile": [
            0.005, 0.003, 0.002, 0.002, 0.005, 0.018,
            0.058, 0.068, 0.072, 0.062, 0.050, 0.045,
            0.042, 0.045, 0.050, 0.055, 0.062, 0.068,
            0.065, 0.058, 0.045, 0.035, 0.020, 0.010,
        ],
    },
    "africa": {
        "domestic_ratio": 0.40,
        "delay_rate": 0.16,
        "mean_delay_minutes": 20.0,
        "delay_distribution": {
            "68": 0.20, "71": 0.18, "81": 0.16, "72": 0.12,
            "62": 0.12, "63": 0.08, "67": 0.06, "61": 0.04, "41": 0.04,
        },
        "hourly_profile": [
            0.005, 0.003, 0.002, 0.002, 0.005, 0.018,
            0.058, 0.068, 0.072, 0.062, 0.050, 0.045,
            0.042, 0.045, 0.050, 0.055, 0.062, 0.068,
            0.065, 0.058, 0.045, 0.035, 0.020, 0.010,
        ],
    },
    "oceania": {
        "domestic_ratio": 0.55,
        "delay_rate": 0.14,
        "mean_delay_minutes": 18.0,
        "delay_distribution": {
            "71": 0.18, "68": 0.18, "81": 0.16, "72": 0.12,
            "62": 0.12, "63": 0.08, "67": 0.06, "61": 0.05, "41": 0.05,
        },
        "hourly_profile": [
            0.000, 0.000, 0.000, 0.000, 0.000, 0.008,
            0.060, 0.072, 0.078, 0.068, 0.055, 0.048,
            0.045, 0.048, 0.055, 0.062, 0.068, 0.072,
            0.065, 0.055, 0.042, 0.030, 0.015, 0.002,
        ],
    },
}


def get_region(country_code: str) -> str:
    """Look up region for a country code, defaulting to europe_west."""
    return COUNTRY_TO_REGION.get(country_code.upper(), "europe_west")


def get_regional_template(country_code: str) -> dict:
    """Return the regional template for a given country code."""
    region = get_region(country_code)
    return REGION_TEMPLATES[region]
