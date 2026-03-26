"""Airport statistical profile — learned distributions for synthetic flight generation.

An AirportProfile is a pure data object containing per-airport distributions
(airline shares, route frequencies, fleet mix, delay stats, hourly patterns)
learned from real data sources (BTS, OpenSky, OurAirports). The synthetic
generator samples from these distributions instead of hardcoded dicts.
"""

import json
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Directory where profile JSONs are stored
_PROFILES_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "calibration" / "profiles"

# BTS T-100 AIRCRAFT_TYPE numeric codes → ICAO type designators.
# BTS uses DOT numeric codes; we map the most common ones to standard ICAO
# type codes used by the simulation and GSE models.
BTS_AIRCRAFT_TYPE_MAP: dict[str, str] = {
    # Airbus single-aisle
    "06460": "A320", "16461": "A321", "06944": "A320", "06689": "A319",
    # Airbus wide-body
    "10260": "A330", "10261": "A330", "10262": "A350",
    # Boeing 737 family
    "06725": "B737", "06031": "B738", "16031": "B739", "0A875": "B738",
    "06700": "B739", "06795": "B738", "16795": "B739", "11033": "B738",
    # Boeing 757/767
    "07024": "B767", "06820": "B738", "16820": "B738",
    # Boeing 777
    "10874": "B777", "07028": "B777",
    # Boeing 787
    "10876": "B787", "10877": "B787", "10875": "A321",
    "10049": "B787", "10050": "B787", "10052": "A321",
    # Regional jets
    "06580": "E175", "11025": "E175", "11027": "CRJ9", "11022": "CRJ7",
    "11030": "E175",
    # Other narrowbody
    "06673": "A320", "16673": "A321", "06830": "A320", "16831": "A321",
    "06035": "A319", "0A050": "A321", "01260": "B738", "01268": "A320",
    "06003": "A319", "06918": "A321", "01189": "A320",
    "07041": "A320", "71072": "A320", "9900Y": "B738",
    # Boeing 757
    "06024": "B752",
}


@dataclass
class AirportProfile:
    """Statistical profile for a single airport, used to drive synthetic generation."""

    icao_code: str  # e.g., "KSFO"
    iata_code: str  # e.g., "SFO"

    # Airline market share: {"UAL": 0.46, "SWA": 0.12, ...}
    airline_shares: dict[str, float] = field(default_factory=dict)

    # Route frequencies: {"LAX": 0.12, "ORD": 0.08, ...}
    domestic_route_shares: dict[str, float] = field(default_factory=dict)
    international_route_shares: dict[str, float] = field(default_factory=dict)
    domestic_ratio: float = 0.7  # fraction of flights that are domestic

    # Fleet mix per airline: {"UAL": {"B738": 0.35, "A320": 0.25}, ...}
    fleet_mix: dict[str, dict[str, float]] = field(default_factory=dict)

    # Hourly traffic profile: 24-element list of relative weights (sums to ~1.0)
    hourly_profile: list[float] = field(default_factory=list)

    # Taxi time statistics (from BTS OTP data, in minutes)
    taxi_out_mean_min: float = 0.0
    taxi_out_p95_min: float = 0.0
    taxi_in_mean_min: float = 0.0
    taxi_in_p95_min: float = 0.0

    # Turnaround time statistics (from BTS OTP tail-number matching, in minutes)
    turnaround_median_min: float = 0.0
    turnaround_p75_min: float = 0.0
    turnaround_p95_min: float = 0.0

    # Delay statistics
    delay_rate: float = 0.15  # fraction of flights delayed
    delay_distribution: dict[str, float] = field(default_factory=dict)  # delay code → weight
    mean_delay_minutes: float = 20.0

    # Metadata
    data_source: str = "fallback"
    region: str = ""
    profile_date: str = ""
    sample_size: int = 0

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(asdict(self), indent=2)

    def save(self, path: Optional[Path] = None) -> Path:
        """Save profile to JSON file."""
        if path is None:
            path = _PROFILES_DIR / f"{self.icao_code}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json())
        return path

    @classmethod
    def from_json(cls, data: dict) -> "AirportProfile":
        """Create profile from a JSON-parsed dict.

        Normalizes BTS numeric aircraft type codes to ICAO designators.
        """
        profile = cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        profile._normalize_fleet_mix()
        return profile

    def _normalize_fleet_mix(self) -> None:
        """Map BTS numeric aircraft type codes to ICAO type designators.

        Unknown numeric codes that don't match any entry in BTS_AIRCRAFT_TYPE_MAP
        and don't look like standard ICAO type designators (e.g. "A320") are
        mapped to A320 as a narrowbody default, with a warning logged.
        """
        import re
        icao_pattern = re.compile(r"^[A-Z][A-Z0-9]{2,3}$")
        for airline, fleet in list(self.fleet_mix.items()):
            normalized: dict[str, float] = {}
            for code, weight in fleet.items():
                if code in BTS_AIRCRAFT_TYPE_MAP:
                    icao_code = BTS_AIRCRAFT_TYPE_MAP[code]
                elif icao_pattern.match(code):
                    icao_code = code  # Already looks like an ICAO type
                else:
                    logger.warning(
                        "Unknown BTS fleet code '%s' for airline %s — mapping to A320",
                        code, airline,
                    )
                    icao_code = "A320"
                # Merge weights if multiple BTS codes map to same ICAO type
                normalized[icao_code] = normalized.get(icao_code, 0.0) + weight
            self.fleet_mix[airline] = normalized

    @classmethod
    def load(cls, path: Path) -> "AirportProfile":
        """Load profile from a JSON file."""
        data = json.loads(path.read_text())
        return cls.from_json(data)


class AirportProfileLoader:
    """Loads airport profiles with fallback chain.

    On Databricks (DATABRICKS_WAREHOUSE_ID set): UC first, local JSON as fallback.
    Locally: local JSON first, UC as fallback.
    """

    def __init__(self, profiles_dir: Optional[Path] = None):
        self._profiles_dir = profiles_dir or _PROFILES_DIR
        self._cache: dict[str, AirportProfile] = {}
        # Detect Databricks environment
        import os
        self._on_databricks = bool(os.environ.get("DATABRICKS_WAREHOUSE_ID", ""))

    def get_profile(self, airport_code: str) -> AirportProfile:
        """Get profile for an airport (IATA or ICAO code).

        Loading order on Databricks:
        1. In-memory cache
        2. Unity Catalog airport_profiles table
        3. Local JSON file (data/calibration/profiles/{ICAO}.json)
        4. Known-stats profiles (known_profiles.py)
        5. OpenFlights auto-build (if routes.dat cached locally)
        6. Hardcoded fallback

        Loading order locally (no warehouse ID):
        1. In-memory cache
        2. Local JSON file
        3. Known-stats profiles
        4. OpenFlights auto-build
        5. Unity Catalog (skipped — no warehouse)
        6. Hardcoded fallback
        """
        # Normalize to ICAO
        icao = _iata_to_icao(airport_code)

        if icao in self._cache:
            return self._cache[icao]

        iata = _icao_to_iata(icao) if len(icao) == 4 else airport_code

        # On Databricks: UC first (source of truth)
        if self._on_databricks:
            uc_profile = self._load_from_unity_catalog(icao)
            if uc_profile is not None:
                self._cache[icao] = uc_profile
                return uc_profile

        # Try local JSON
        json_path = self._profiles_dir / f"{icao}.json"
        if json_path.exists():
            try:
                profile = AirportProfile.load(json_path)
                self._cache[icao] = profile
                logger.info("Loaded calibration profile for %s from %s", icao, json_path)
                return profile
            except Exception as e:
                logger.warning("Failed to load profile %s: %s", json_path, e)

        # Try hand-researched known profiles (known_profiles.py)
        from src.calibration.known_profiles import get_known_profile
        known = get_known_profile(iata)
        if known is not None:
            self._cache[icao] = known
            logger.info("Loaded known-stats profile for %s (%s)", icao, iata)
            return known

        # Try OpenFlights auto-build (if routes.dat exists locally)
        openflights_profile = self._try_openflights(iata)
        if openflights_profile is not None:
            self._cache[icao] = openflights_profile
            return openflights_profile

        # Local dev: try UC as late fallback (usually skipped — no warehouse)
        if not self._on_databricks:
            uc_profile = self._load_from_unity_catalog(icao)
            if uc_profile is not None:
                self._cache[icao] = uc_profile
                return uc_profile

        # Fallback to hardcoded
        profile = _build_fallback_profile(airport_code)
        self._cache[icao] = profile
        logger.info("Using fallback profile for %s", icao)
        return profile

    def _try_openflights(self, iata: str) -> Optional[AirportProfile]:
        """Try to build profile from locally cached OpenFlights routes.dat.

        Only uses the file if already downloaded — does not trigger downloads
        at runtime to avoid blocking the request path.
        """
        try:
            from src.calibration.openflights_ingest import build_profile_from_openflights
            profile = build_profile_from_openflights(
                iata, download=False,  # never download at runtime
            )
            if profile is not None and (
                profile.domestic_route_shares or profile.international_route_shares
            ):
                logger.info("Built OpenFlights profile for %s (%d routes)", iata, profile.sample_size)
                return profile
        except Exception as e:
            logger.debug("OpenFlights auto-build failed for %s: %s", iata, e)
        return None

    def _load_from_unity_catalog(self, icao: str) -> Optional[AirportProfile]:
        """Try to load profile from Unity Catalog airport_profiles table.

        Returns None if not running on Databricks or table is not available.
        """
        try:
            import os
            warehouse_id = os.environ.get("DATABRICKS_WAREHOUSE_ID", "")
            if not warehouse_id:
                return None

            from databricks.sdk import WorkspaceClient
            from databricks.sdk.service.sql import StatementState

            catalog = os.environ.get("DATABRICKS_CATALOG", "serverless_stable_3n0ihb_catalog")
            schema = os.environ.get("DATABRICKS_SCHEMA", "airport_digital_twin")

            client = WorkspaceClient()
            sql = (
                f"SELECT profile_json FROM {catalog}.{schema}.airport_profiles "
                f"WHERE icao_code = '{icao}' LIMIT 1"
            )
            response = client.statement_execution.execute_statement(
                warehouse_id=warehouse_id,
                statement=sql,
                wait_timeout="30s",
            )

            if (
                response.status
                and response.status.state == StatementState.SUCCEEDED
                and response.result
                and response.result.data_array
            ):
                row = response.result.data_array[0]
                profile_json = row[0]
                data = json.loads(profile_json)
                profile = AirportProfile.from_json(data)
                logger.info("Loaded profile for %s from Unity Catalog", icao)
                return profile

        except ImportError:
            logger.debug("Databricks SDK not available, skipping UC lookup")
        except Exception as e:
            logger.debug("UC profile lookup for %s failed: %s", icao, e)

        return None

    def update_cache(self, icao: str, profile: AirportProfile) -> None:
        """Inject an auto-calibrated profile into the in-memory cache."""
        self._cache[icao] = profile
        logger.info("Updated cache for %s (source: %s)", icao, profile.data_source)

    def clear_cache(self) -> None:
        """Clear cached profiles."""
        self._cache.clear()

    def list_available(self) -> list[str]:
        """List ICAO codes with available profile JSON files."""
        if not self._profiles_dir.exists():
            return []
        return sorted(p.stem for p in self._profiles_dir.glob("*.json"))


# ============================================================================
# Unity Catalog persistence
# ============================================================================

def save_to_unity_catalog(
    profile: AirportProfile,
    client: "WorkspaceClient",
    warehouse_id: str,
    catalog: str = "serverless_stable_3n0ihb_catalog",
    schema: str = "airport_digital_twin",
) -> bool:
    """Persist a single AirportProfile to the airport_profiles Delta table.

    Uses MERGE to upsert by icao_code. Returns True on success, False on failure.
    """
    from databricks.sdk.service.sql import StatementState

    profile_json = profile.to_json().replace("'", "''")
    sql = (
        f"MERGE INTO {catalog}.{schema}.airport_profiles AS target "
        f"USING (SELECT '{profile.icao_code}' AS icao_code) AS source "
        f"ON target.icao_code = source.icao_code "
        f"WHEN MATCHED THEN UPDATE SET "
        f"  iata_code = '{profile.iata_code}', "
        f"  profile_json = '{profile_json}', "
        f"  data_source = '{profile.data_source}', "
        f"  sample_size = {profile.sample_size}, "
        f"  profile_date = current_timestamp(), "
        f"  updated_at = current_timestamp() "
        f"WHEN NOT MATCHED THEN INSERT "
        f"  (icao_code, iata_code, profile_json, data_source, sample_size, "
        f"   profile_date, created_at, updated_at) "
        f"VALUES ('{profile.icao_code}', '{profile.iata_code}', '{profile_json}', "
        f"  '{profile.data_source}', {profile.sample_size}, "
        f"  current_timestamp(), current_timestamp(), current_timestamp())"
    )
    try:
        response = client.statement_execution.execute_statement(
            warehouse_id=warehouse_id,
            statement=sql,
            wait_timeout="30s",
        )
        if response.status and response.status.state == StatementState.SUCCEEDED:
            logger.info("Persisted %s (%s) to UC", profile.icao_code, profile.iata_code)
            return True
        logger.warning("Failed to persist %s: %s", profile.icao_code, response.status)
        return False
    except Exception as e:
        logger.error("Error persisting %s to UC: %s", profile.icao_code, e)
        return False


def save_batch_to_unity_catalog(
    profiles: list[AirportProfile],
    client: "WorkspaceClient",
    warehouse_id: str,
    catalog: str = "serverless_stable_3n0ihb_catalog",
    schema: str = "airport_digital_twin",
) -> int:
    """Persist multiple profiles to UC. Returns count of successfully persisted."""
    persisted = 0
    for p in profiles:
        if save_to_unity_catalog(p, client, warehouse_id, catalog, schema):
            persisted += 1
    logger.info("Persisted %d/%d profiles to %s.%s.airport_profiles", persisted, len(profiles), catalog, schema)
    return persisted


# ============================================================================
# IATA ↔ ICAO mapping (common airports)
# ============================================================================

_IATA_TO_ICAO: dict[str, str] = {
    "SFO": "KSFO", "LAX": "KLAX", "ORD": "KORD", "DFW": "KDFW",
    "JFK": "KJFK", "ATL": "KATL", "DEN": "KDEN", "SEA": "KSEA",
    "BOS": "KBOS", "PHX": "KPHX", "LAS": "KLAS", "MCO": "KMCO",
    "MIA": "KMIA", "CLT": "KCLT", "MSP": "KMSP", "DTW": "KDTW",
    "EWR": "KEWR", "PHL": "KPHL", "IAH": "KIAH", "SAN": "KSAN",
    "PDX": "KPDX",
    "LHR": "EGLL", "CDG": "LFPG", "FRA": "EDDF", "AMS": "EHAM",
    "HKG": "VHHH", "NRT": "RJAA", "SIN": "WSSS", "SYD": "YSSY",
    "DXB": "OMDB", "ICN": "RKSI", "GRU": "SBGR", "JNB": "FAOR",
    "CPT": "FACT",
    # New international airports
    "GVA": "LSGG", "ATH": "LGAV", "MAD": "LEMD", "FCO": "LIRF",
    "AUH": "OMAA", "HND": "RJTT", "PEK": "ZBAA", "BKK": "VTBS",
    "CMN": "GMMN", "MEX": "MMMX",
}

_ICAO_TO_IATA: dict[str, str] = {v: k for k, v in _IATA_TO_ICAO.items()}


def _iata_to_icao(code: str) -> str:
    """Convert IATA to ICAO. If already ICAO or unknown, return as-is."""
    if code in _IATA_TO_ICAO:
        return _IATA_TO_ICAO[code]
    return code


def _icao_to_iata(code: str) -> str:
    """Convert ICAO to IATA. If already IATA or unknown, return as-is."""
    if code in _ICAO_TO_IATA:
        return _ICAO_TO_IATA[code]
    return code


# ============================================================================
# Fallback profile builder — uses current hardcoded values
# ============================================================================

def _build_fallback_profile(airport_code: str) -> AirportProfile:
    """Build a fallback profile from the current hardcoded distributions.

    This produces an AirportProfile whose distributions exactly match the
    existing hardcoded constants in schedule_generator.py, so behavior is
    identical when no real-data profile is available.
    """
    icao = _iata_to_icao(airport_code)
    iata = _icao_to_iata(icao) if icao.startswith("K") or len(icao) == 4 else airport_code

    # Airline shares from schedule_generator.AIRLINES
    airline_shares = {
        "UAL": 0.35, "DAL": 0.15, "AAL": 0.15, "SWA": 0.10,
        "ASA": 0.08, "JBU": 0.05, "UAE": 0.04, "BAW": 0.03,
        "ANA": 0.03, "CPA": 0.02,
    }

    # Route shares — uniform over the existing lists
    domestic_airports = [
        "LAX", "ORD", "DFW", "JFK", "ATL", "DEN", "SEA", "BOS", "PHX", "LAS",
        "MCO", "MIA", "CLT", "MSP", "DTW", "EWR", "PHL", "IAH", "SAN", "PDX",
    ]
    international_airports = [
        "LHR", "CDG", "FRA", "AMS", "HKG", "NRT", "SIN", "SYD", "DXB", "ICN",
    ]

    # Remove self from route lists
    domestic_airports = [a for a in domestic_airports if a != iata]
    international_airports = [a for a in international_airports if a != iata]

    n_dom = len(domestic_airports) or 1
    n_intl = len(international_airports) or 1
    domestic_route_shares = {a: 1.0 / n_dom for a in domestic_airports}
    international_route_shares = {a: 1.0 / n_intl for a in international_airports}

    # Fleet mix: narrow body for domestic, wide body for international
    # Same logic as _select_aircraft — uniform choice
    narrow_body = ["A320", "A321", "B737", "B738", "A319", "E175"]
    wide_body = ["B777", "B787", "A330", "A350", "A380"]
    fleet_mix: dict[str, dict[str, float]] = {}
    for airline in airline_shares:
        nb_share = {a: 1.0 / len(narrow_body) for a in narrow_body}
        wb_share = {a: 1.0 / len(wide_body) for a in wide_body}
        fleet_mix[airline] = {**nb_share, **wb_share}

    # Hourly profile from the us_dual_peak midpoints, normalized
    us_dual_peak_mids = [
        1, 1, 0.5, 0.5, 2, 7.5,
        21.5, 21.5, 21.5, 21.5, 12.5, 12.5,
        12.5, 12.5, 12.5, 12.5, 21.5, 21.5,
        21.5, 21.5, 10, 10, 6.5, 1.5,
    ]
    total = sum(us_dual_peak_mids)
    hourly_profile = [v / total for v in us_dual_peak_mids]

    # Delay stats from schedule_generator
    delay_distribution = {
        "61": 0.05, "62": 0.12, "63": 0.10, "67": 0.08,
        "68": 0.15, "71": 0.18, "72": 0.12, "81": 0.15,
        "41": 0.05,
    }

    return AirportProfile(
        icao_code=icao,
        iata_code=iata,
        airline_shares=airline_shares,
        domestic_route_shares=domestic_route_shares,
        international_route_shares=international_route_shares,
        domestic_ratio=0.7,
        fleet_mix=fleet_mix,
        hourly_profile=hourly_profile,
        delay_rate=0.15,
        delay_distribution=delay_distribution,
        mean_delay_minutes=20.0,
        data_source="fallback",
        profile_date="",
        sample_size=0,
    )
