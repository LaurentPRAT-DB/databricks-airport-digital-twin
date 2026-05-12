"""OpenSky Network service for live ADS-B flight data.

Fetches real-time aircraft positions from the OpenSky Network REST API
and converts them to our FlightPosition schema.

API docs: https://openskynetwork.github.io/opensky-api/rest.html
Rate limits: 10 requests per 10 seconds (anonymous), better with account.
"""

import logging
import time
from datetime import datetime, timezone
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# OpenSky state vector field indices
_ICAO24 = 0
_CALLSIGN = 1
_ORIGIN_COUNTRY = 2
_TIME_POSITION = 3
_LAST_CONTACT = 4
_LONGITUDE = 5
_LATITUDE = 6
_BARO_ALTITUDE = 7  # meters
_ON_GROUND = 8
_VELOCITY = 9  # m/s
_TRUE_TRACK = 10  # degrees
_VERTICAL_RATE = 11  # m/s
_GEO_ALTITUDE = 13  # meters

# Unit conversions (public for reuse by recordings API)
M_TO_FT = 3.28084
MS_TO_KTS = 1.94384
MS_TO_FTMIN = 196.85

# Default bounding box radius in degrees (~30nm ≈ 0.5°)
_DEFAULT_RADIUS_DEG = 0.5

OPENSKY_API_URL = "https://opensky-network.org/api/states/all"


def determine_flight_phase(
    altitude_ft: float, vertical_rate_ftmin: float, on_ground: bool
) -> str:
    """Determine flight phase from altitude, vertical rate, and ground status.

    Phase names are aligned with the simulation engine vocabulary so that
    recorded/live OpenSky data and simulated data share the same phase
    strings, avoiding UI mismatches.
    """
    if on_ground:
        return "parked"
    if altitude_ft < 3000 and vertical_rate_ftmin > 200:
        return "takeoff"
    if altitude_ft < 3000 and vertical_rate_ftmin < -200:
        return "landing"
    # Short final: shallow glideslope at low altitude is still landing
    if altitude_ft < 2000 and vertical_rate_ftmin < -50:
        return "landing"
    if altitude_ft < 10000 and vertical_rate_ftmin < -500:
        return "approaching"
    if altitude_ft < 10000 and vertical_rate_ftmin > 500:
        return "departing"
    # Low altitude with mild descent — approaching, not cruising
    if altitude_ft < 5000 and vertical_rate_ftmin < -50:
        return "approaching"
    if vertical_rate_ftmin > 200:
        return "departing"
    if vertical_rate_ftmin < -200:
        return "approaching"
    return "enroute"


# ── Live gate proximity matching ────────────────────────────────────────

from src.inference.opensky_events import haversine_m, GATE_MATCH_RADIUS_M

_STATIONARY_KTS = 5.0  # Below this speed, aircraft is considered stopped


def assign_nearest_gates(
    flights: list[dict], gates: list[dict], max_dist_m: float = GATE_MATCH_RADIUS_M
) -> None:
    """Assign nearest gate to on-ground stationary aircraft (mutates in-place)."""
    if not gates:
        return

    gate_positions: list[tuple[str, float, float]] = []
    for g in gates:
        gid = g.get("ref") or g.get("id") or ""
        geo = g.get("geo", {})
        glat, glon = geo.get("latitude"), geo.get("longitude")
        if gid and glat is not None and glon is not None:
            gate_positions.append((str(gid), float(glat), float(glon)))

    if not gate_positions:
        return

    for f in flights:
        if f.get("assigned_gate"):
            continue
        if not f.get("on_ground"):
            continue
        if float(f.get("velocity", 0) or 0) > _STATIONARY_KTS:
            continue

        lat, lon = f.get("latitude"), f.get("longitude")
        if lat is None or lon is None:
            continue

        best_id, best_dist = None, float("inf")
        for gid, glat, glon in gate_positions:
            d = haversine_m(lat, lon, glat, glon)
            if d < best_dist:
                best_id, best_dist = gid, d

        if best_dist <= max_dist_m:
            f["assigned_gate"] = best_id


class LiveGateTracker:
    """Tracks gate assignments across live polling cycles.

    Detects gate arrivals (assign/occupy) and departures (release) by
    comparing consecutive polls. Persists events to Lakebase.
    """

    def __init__(self) -> None:
        self._parked: dict[str, tuple[str, str, str]] = {}  # icao24 -> (gate, callsign, parked_since_iso)

    def update(
        self,
        flights: list[dict],
        session_id: str,
        airport_icao: str,
    ) -> list[dict]:
        """Process a poll cycle. Returns gate events emitted this cycle."""
        from datetime import datetime, timezone

        now_iso = datetime.now(timezone.utc).isoformat()
        events: list[dict] = []
        seen: set[str] = set()

        for f in flights:
            icao24 = f.get("icao24", "")
            if not icao24:
                continue
            seen.add(icao24)

            gate = f.get("assigned_gate")
            callsign = f.get("callsign", icao24)
            on_ground = f.get("on_ground", False)
            velocity = float(f.get("velocity", 0) or 0)

            was_parked = icao24 in self._parked

            if gate and on_ground and velocity < _STATIONARY_KTS:
                if not was_parked or self._parked[icao24][0] != gate:
                    # New gate assignment
                    if was_parked:
                        old_gate = self._parked[icao24][0]
                        events.append({
                            "icao24": icao24, "callsign": callsign,
                            "gate": old_gate, "event_type": "release",
                            "event_time": now_iso,
                        })
                    self._parked[icao24] = (gate, callsign, now_iso)
                    events.append({
                        "icao24": icao24, "callsign": callsign,
                        "gate": gate, "event_type": "assign",
                        "event_time": now_iso,
                    })
                    events.append({
                        "icao24": icao24, "callsign": callsign,
                        "gate": gate, "event_type": "occupy",
                        "event_time": now_iso,
                    })
            elif was_parked:
                # Was parked, now moving or airborne — gate departure
                old_gate, old_cs, _ = self._parked.pop(icao24)
                events.append({
                    "icao24": icao24, "callsign": old_cs,
                    "gate": old_gate, "event_type": "release",
                    "event_time": now_iso,
                })
                logger.info("Gate departure: %s left gate %s at %s", callsign, old_gate, airport_icao)

        # Aircraft that disappeared from the feed — release their gates
        for icao24 in list(self._parked):
            if icao24 not in seen:
                old_gate, old_cs, _ = self._parked.pop(icao24)
                events.append({
                    "icao24": icao24, "callsign": old_cs,
                    "gate": old_gate, "event_type": "release",
                    "event_time": now_iso,
                })

        # Persist to Lakebase
        if events:
            try:
                from app.backend.services.lakebase_service import get_lakebase_service
                lakebase = get_lakebase_service()
                if lakebase.is_available:
                    lakebase.insert_gate_events(events, session_id, airport_icao)
            except Exception as e:
                logger.warning("Failed to persist live gate events: %s", e)

        return events


# Per-airport tracker singletons
_gate_trackers: dict[str, LiveGateTracker] = {}


def get_gate_tracker(airport_icao: str) -> LiveGateTracker:
    """Get or create a LiveGateTracker for the given airport."""
    if airport_icao not in _gate_trackers:
        _gate_trackers[airport_icao] = LiveGateTracker()
    return _gate_trackers[airport_icao]


class OpenSkyService:
    """Fetches live ADS-B data from the OpenSky Network API."""

    AUTH_URL = "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        timeout: float = 15.0,
    ):
        self._client_id = client_id
        self._client_secret = client_secret
        self._token: Optional[str] = None
        self._timeout = timeout
        self._last_fetch_time: Optional[float] = None
        self._last_flight_count: int = 0
        self._last_error: Optional[str] = None
        self._client = httpx.AsyncClient(timeout=timeout)
        self._reachable: Optional[bool] = None  # None = not tested yet

    async def _get_token(self) -> Optional[str]:
        """Get OAuth2 access token using client credentials flow."""
        if not self._client_id or not self._client_secret:
            return None
        if self._token:
            return self._token
        try:
            response = await self._client.post(
                self.AUTH_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
            )
            if response.status_code == 200:
                self._token = response.json().get("access_token")
            return self._token
        except Exception as e:
            logger.warning("OpenSky OAuth2 token fetch failed: %s", e)
            return None

    async def fetch_flights(
        self,
        lat: float,
        lon: float,
        radius_deg: float = _DEFAULT_RADIUS_DEG,
    ) -> list[dict]:
        """Fetch live flights within a bounding box around the given coordinates.

        Args:
            lat: Airport center latitude.
            lon: Airport center longitude.
            radius_deg: Bounding box half-size in degrees (~0.5° ≈ 30nm).

        Returns:
            List of dicts compatible with FlightPosition fields.
        """
        params = {
            "lamin": lat - radius_deg,
            "lamax": lat + radius_deg,
            "lomin": lon - radius_deg,
            "lomax": lon + radius_deg,
        }

        try:
            headers = {}
            token = await self._get_token()
            if token:
                headers["Authorization"] = f"Bearer {token}"

            response = await self._client.get(OPENSKY_API_URL, params=params, headers=headers)

            if response.status_code == 429:
                logger.warning("OpenSky rate limited (429), backing off")
                self._last_error = "Rate limited"
                return []

            response.raise_for_status()
            data = response.json()

            states = data.get("states") or []
            flights = []

            for state in states:
                flight = self._state_to_flight(state)
                if flight:
                    flights.append(flight)

            flights = self._deduplicate(flights)

            self._last_fetch_time = time.time()
            self._last_flight_count = len(flights)
            self._last_error = None

            logger.info("OpenSky: fetched %d flights near (%.2f, %.2f)", len(flights), lat, lon)
            return flights

        except httpx.HTTPStatusError as e:
            self._last_error = f"HTTP {e.response.status_code}"
            logger.warning("OpenSky API error: %s", e)
            return []
        except Exception as e:
            self._last_error = str(e)
            logger.warning("OpenSky fetch failed: %s", e)
            return []

    @staticmethod
    def _deduplicate(flights: list[dict]) -> list[dict]:
        """Remove duplicate entries for the same physical aircraft.

        OpenSky can report the same callsign under multiple icao24 codes.
        For each callsign, keep only the entry with the most recent last_seen.
        Entries without a meaningful callsign (empty or equal to icao24) are
        kept as-is since they can't be matched.
        """
        by_callsign: dict[str, dict] = {}
        no_callsign: list[dict] = []
        for f in flights:
            cs = f.get("callsign", "")
            icao24 = f.get("icao24", "")
            if not cs or cs == icao24.upper():
                no_callsign.append(f)
                continue
            existing = by_callsign.get(cs)
            if existing is None or (f.get("last_seen") or 0) > (existing.get("last_seen") or 0):
                by_callsign[cs] = f
        return list(by_callsign.values()) + no_callsign

    def _state_to_flight(self, state: list) -> Optional[dict]:
        """Convert an OpenSky state vector to our flight dict format."""
        if len(state) < 12:
            return None

        icao24 = state[_ICAO24]
        callsign = (state[_CALLSIGN] or "").strip()
        latitude = state[_LATITUDE]
        longitude = state[_LONGITUDE]

        # Skip flights with no position
        if latitude is None or longitude is None:
            return None

        on_ground = bool(state[_ON_GROUND])
        baro_alt_m = state[_BARO_ALTITUDE] or 0.0
        velocity_ms = state[_VELOCITY] or 0.0
        heading = state[_TRUE_TRACK]
        vrate_ms = state[_VERTICAL_RATE] or 0.0
        last_contact = state[_LAST_CONTACT]

        # Convert units
        altitude_ft = baro_alt_m * M_TO_FT
        velocity_kts = velocity_ms * MS_TO_KTS
        vrate_ftmin = vrate_ms * MS_TO_FTMIN

        flight_phase = determine_flight_phase(altitude_ft, vrate_ftmin, on_ground)

        return {
            "icao24": icao24,
            "callsign": callsign or icao24.upper(),
            "latitude": latitude,
            "longitude": longitude,
            "altitude": altitude_ft,
            "velocity": velocity_kts,
            "heading": heading,
            "on_ground": on_ground,
            "vertical_rate": vrate_ftmin,
            "last_seen": last_contact,
            "data_source": "opensky",
            "flight_phase": flight_phase,
            "aircraft_type": None,
            "assigned_gate": None,
            "origin_airport": None,
            "destination_airport": None,
        }

    async def probe_connectivity(self) -> bool:
        """Test if the OpenSky API is reachable (TCP connect + HTTP response).

        Sets self._reachable and returns the result. Safe to call multiple times.
        """
        try:
            response = await self._client.get(
                OPENSKY_API_URL,
                params={"lamin": 0, "lamax": 0.01, "lomin": 0, "lomax": 0.01},
            )
            self._reachable = response.status_code in (200, 429)
            logger.info("OpenSky connectivity probe: reachable=%s (HTTP %s)",
                        self._reachable, response.status_code)
        except Exception as e:
            self._reachable = False
            logger.warning("OpenSky connectivity probe failed: %s: %s",
                           type(e).__name__, e)
        return self._reachable

    def get_status(self) -> dict:
        """Return service health status."""
        return {
            "available": self._reachable if self._reachable is not None else True,
            "reachable": self._reachable,
            "last_fetch_time": (
                datetime.fromtimestamp(self._last_fetch_time, tz=timezone.utc).isoformat()
                if self._last_fetch_time
                else None
            ),
            "last_flight_count": self._last_flight_count,
            "last_error": self._last_error,
            "authenticated": self._client_id is not None,
        }

    async def close(self):
        """Close the HTTP client."""
        await self._client.aclose()


# Singleton
_opensky_service: Optional[OpenSkyService] = None


def _resolve_opensky_credentials() -> tuple[Optional[str], Optional[str]]:
    """Resolve OpenSky OAuth2 credentials: Databricks secrets first, then env vars.

    Returns:
        (client_id, client_secret) tuple, or (None, None) for anonymous access.
    """
    import os

    # Try Databricks secrets (secure, no plaintext in app.yaml)
    try:
        from databricks.sdk import WorkspaceClient
        w = WorkspaceClient()
        client_id = w.dbutils.secrets.get(scope="airport-digital-twin", key="opensky-client-id")
        client_secret = w.dbutils.secrets.get(scope="airport-digital-twin", key="opensky-client-secret")
        if client_id and client_secret:
            logger.info("OpenSky OAuth2 credentials loaded from Databricks secrets")
            return client_id, client_secret
        else:
            logger.warning("Databricks secrets returned empty values for OpenSky credentials")
    except Exception as e:
        logger.warning("Failed to load OpenSky credentials from Databricks secrets: %s: %s",
                       type(e).__name__, e)

    # Fall back to env vars (local dev)
    client_id = os.getenv("OPENSKY_CLIENT_ID")
    client_secret = os.getenv("OPENSKY_CLIENT_SECRET")
    if client_id and client_secret:
        logger.info("OpenSky OAuth2 credentials loaded from environment variables")
        return client_id, client_secret

    logger.warning("No OpenSky credentials found — using anonymous access (lower rate limits)")
    return None, None


def get_opensky_service() -> OpenSkyService:
    """Get or create the OpenSky service singleton."""
    global _opensky_service
    if _opensky_service is None:
        client_id, client_secret = _resolve_opensky_credentials()
        _opensky_service = OpenSkyService(client_id=client_id, client_secret=client_secret)
    return _opensky_service


# ── Flight origin enrichment ────────────────────────────────────────


import math


def _bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Compute initial bearing (degrees) from point 1 to point 2."""
    lat1, lon1, lat2, lon2 = (math.radians(x) for x in (lat1, lon1, lat2, lon2))
    dlon = lon2 - lon1
    y = math.sin(dlon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def _haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in nautical miles."""
    lat1, lon1, lat2, lon2 = (math.radians(x) for x in (lat1, lon1, lat2, lon2))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * 3440.065 * math.asin(math.sqrt(a))


async def enrich_origins_opensky(
    icao24_set: set[str],
    begin_ts: int,
    end_ts: int,
) -> dict[str, tuple[Optional[str], Optional[str]]]:
    """Level 1: Look up departure/arrival airports via OpenSky flights API.

    Returns dict of icao24 -> (departure_icao, arrival_icao).
    Only returns entries that were successfully resolved.
    Rate-limited: batches requests with small delays.
    """
    service = get_opensky_service()
    if service._reachable is False:
        return {}

    results: dict[str, tuple[Optional[str], Optional[str]]] = {}
    api_url = "https://opensky-network.org/api/flights/aircraft"

    for icao24 in icao24_set:
        try:
            headers = {}
            token = await service._get_token()
            if token:
                headers["Authorization"] = f"Bearer {token}"

            resp = await service._client.get(
                api_url,
                params={"icao24": icao24, "begin": begin_ts, "end": end_ts},
                headers=headers,
            )
            if resp.status_code == 429:
                logger.info("OpenSky flights API rate limited, stopping lookups")
                break
            if resp.status_code != 200:
                continue

            flights = resp.json()
            if not flights:
                continue

            # Use the flight record closest to our time window
            best = flights[0]
            dep = best.get("estDepartureAirport")
            arr = best.get("estArrivalAirport")
            if dep or arr:
                results[icao24] = (dep, arr)

        except Exception as e:
            logger.debug("OpenSky flights lookup failed for %s: %s", icao24, e)
            continue

    logger.info("OpenSky flights API enriched %d/%d aircraft", len(results), len(icao24_set))
    return results


def enrich_origins_heading(
    aircraft_first_seen: dict[str, dict],
    airport_lat: float,
    airport_lon: float,
    airport_icao: str,
) -> dict[str, tuple[str, str]]:
    """Level 2: Estimate origin from inbound heading using airport database.

    For each aircraft, uses its heading when first detected to compute a
    back-bearing, then finds the nearest major airport along that bearing.

    Args:
        aircraft_first_seen: icao24 -> first snapshot dict with lat/lon/heading/phase
        airport_lat, airport_lon: center of the observed airport
        airport_icao: ICAO code of the current airport (excluded from candidates)

    Returns dict of icao24 -> (origin_icao, destination_icao).
    """
    try:
        from src.ingestion.airport_table import AIRPORTS
    except ImportError:
        logger.warning("Airport table not available for heading-based origin enrichment")
        return {}

    # Build candidate list: (iata, icao, lat, lon, bearing_from_airport, distance_nm)
    candidates: list[tuple[str, str, float, float, float, float]] = []
    for iata, (lat, lon, icao, _country) in AIRPORTS.items():
        if icao == airport_icao:
            continue
        dist = _haversine_nm(airport_lat, airport_lon, lat, lon)
        if dist < 50:
            continue  # Skip very close airports
        bearing = _bearing(airport_lat, airport_lon, lat, lon)
        candidates.append((iata, icao, lat, lon, bearing, dist))

    results: dict[str, tuple[str, str]] = {}

    for icao24, snap in aircraft_first_seen.items():
        heading = snap.get("heading")
        phase = snap.get("phase") or snap.get("flight_phase") or ""
        lat = snap.get("latitude")
        lon = snap.get("longitude")

        if heading is None or lat is None or lon is None:
            continue

        is_arriving = phase in ("approaching", "landing", "taxi_in", "parked")
        is_departing = phase in ("takeoff", "departing", "taxi_out", "pushback")

        if is_arriving:
            # Back-bearing: where did this flight come from?
            back_bearing = (heading + 180) % 360
            # Find best candidate: closest angular match weighted by distance reasonableness
            best_score = float("inf")
            best_icao = None
            for _iata, cand_icao, _lat, _lon, cand_bearing, dist in candidates:
                angle_diff = abs(back_bearing - cand_bearing)
                if angle_diff > 180:
                    angle_diff = 360 - angle_diff
                # Score: angular difference (primary) + distance penalty (prefer 200-2000nm)
                dist_penalty = abs(math.log(max(dist, 100) / 500))
                score = angle_diff + dist_penalty * 10
                if score < best_score:
                    best_score = score
                    best_icao = cand_icao
            if best_icao and best_score < 90:  # Only if reasonable match (<90° off)
                results[icao24] = (best_icao, airport_icao)
        elif is_departing:
            # Departing: heading tells us where it's going
            best_score = float("inf")
            best_icao = None
            for _iata, cand_icao, _lat, _lon, cand_bearing, dist in candidates:
                angle_diff = abs(heading - cand_bearing)
                if angle_diff > 180:
                    angle_diff = 360 - angle_diff
                dist_penalty = abs(math.log(max(dist, 100) / 500))
                score = angle_diff + dist_penalty * 10
                if score < best_score:
                    best_score = score
                    best_icao = cand_icao
            if best_icao and best_score < 90:
                results[icao24] = (airport_icao, best_icao)

    logger.info("Heading-based enrichment resolved %d/%d aircraft",
                len(results), len(aircraft_first_seen))
    return results
