"""Lakebase (PostgreSQL) service for low-latency flight data serving.

This service connects to Databricks Lakebase Autoscaling (managed PostgreSQL) for
sub-10ms query latency, ideal for real-time frontend serving.

Supports two authentication modes:
1. Direct credentials (LAKEBASE_USER/PASSWORD) for local development
2. OAuth via Databricks SDK for Databricks Apps (Lakebase Autoscaling)
"""

import os
import logging
from typing import Optional
from contextlib import contextmanager

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor, execute_values
    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False

logger = logging.getLogger(__name__)


def _get_oauth_token(endpoint_name: str) -> Optional[tuple[str, str]]:
    """Get OAuth token for Lakebase Autoscaling using Databricks SDK.

    Args:
        endpoint_name: Full endpoint resource name
            (e.g., 'projects/my-app/branches/production/endpoints/primary')

    Returns:
        Tuple of (token, user_email) or None if unavailable.
    """
    try:
        from databricks.sdk import WorkspaceClient
        import threading

        # Use a timeout to prevent WorkspaceClient() from hanging on U2M
        # browser-based OAuth flow in headless environments (Databricks Apps).
        result: list = []
        error: list = []

        def _try_get_token():
            try:
                w = WorkspaceClient()
                cred = w.postgres.generate_database_credential(endpoint=endpoint_name)
                me = w.current_user.me()
                result.append((cred.token, me.user_name))
            except Exception as e:
                error.append(e)

        thread = threading.Thread(target=_try_get_token, daemon=True)
        thread.start()
        thread.join(timeout=10)  # 10s max — if U2M kicks in it will hang

        if result:
            return result[0]
        if error:
            logger.debug(f"OAuth token generation failed: {error[0]}")
        else:
            logger.warning("OAuth token generation timed out (possible U2M flow in headless env)")
        return None

    except Exception as e:
        logger.debug(f"OAuth token generation failed: {e}")
        return None


class LakebaseService:
    """Service for querying flight data from Lakebase Autoscaling PostgreSQL."""

    def __init__(self):
        """Initialize Lakebase connection parameters from environment."""
        self._connection_string = os.getenv("LAKEBASE_CONNECTION_STRING")
        self._host = os.getenv("LAKEBASE_HOST")
        self._port = os.getenv("LAKEBASE_PORT", "5432")
        self._database = os.getenv("LAKEBASE_DATABASE", "databricks_postgres")
        self._user = os.getenv("LAKEBASE_USER")
        self._password = os.getenv("LAKEBASE_PASSWORD")
        self._schema = os.getenv("LAKEBASE_SCHEMA", "public")
        # Lakebase Autoscaling uses endpoint name instead of instance name
        self._endpoint_name = os.getenv("LAKEBASE_ENDPOINT_NAME")
        self._use_oauth = os.getenv("LAKEBASE_USE_OAUTH", "false").lower() == "true"
        self._cached_credentials: Optional[tuple[str, str]] = None
        self._airport_columns_ensured = False
        self._ml_tables_ensured = False

    @property
    def is_available(self) -> bool:
        """Check if Lakebase connection is configured and available."""
        if not PSYCOPG2_AVAILABLE:
            logger.debug("psycopg2 not installed - Lakebase unavailable")
            return False

        if self._connection_string:
            return True

        # For OAuth mode (Autoscaling), need host and endpoint name
        if self._use_oauth and self._host and self._endpoint_name:
            return True

        # For direct mode, need all credentials
        return bool(self._host and self._user and self._password)

    def _get_credentials(self) -> Optional[tuple[str, str]]:
        """Get user and password, using OAuth if configured."""
        if self._use_oauth and self._endpoint_name:
            if self._cached_credentials is None:
                self._cached_credentials = _get_oauth_token(self._endpoint_name)
            return self._cached_credentials

        if self._user and self._password:
            return (self._password, self._user)

        return None

    @contextmanager
    def _get_connection(self):
        """Context manager for database connections with auto-cleanup."""
        conn = None
        try:
            if self._connection_string:
                conn = psycopg2.connect(self._connection_string)
            else:
                creds = self._get_credentials()
                if not creds:
                    raise RuntimeError("No Lakebase credentials available")

                password, user = creds
                conn = psycopg2.connect(
                    host=self._host,
                    port=self._port,
                    database=self._database,
                    user=user,
                    password=password,
                    sslmode="require",
                    options=f"-c search_path={self._schema}",
                    connect_timeout=5,
                )
            yield conn
        finally:
            if conn:
                conn.close()

    def _ensure_airport_columns(self) -> None:
        """Run ALTER TABLE ADD COLUMN IF NOT EXISTS for airport_icao migration.

        Safe to call multiple times — only runs once per service lifetime.
        """
        if self._airport_columns_ensured or not self.is_available:
            return

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    # Add airport_icao column to tables that need it
                    for table in ["flight_schedule", "baggage_status", "gse_fleet", "gse_turnaround"]:
                        cur.execute(
                            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS "
                            f"airport_icao VARCHAR(4) NOT NULL DEFAULT 'KSFO'"
                        )
                    conn.commit()
            self._airport_columns_ensured = True
            logger.debug("Ensured airport_icao columns exist on all tables")
        except Exception as e:
            logger.debug(f"Airport column migration check: {e}")

    def get_flights(self, limit: int = 100) -> Optional[list[dict]]:
        """
        Fetch current flight positions from Lakebase.

        Args:
            limit: Maximum number of flights to return.

        Returns:
            List of flight dictionaries, or None if query fails.
        """
        if not self.is_available:
            return None

        try:
            with self._get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(
                        """
                        SELECT
                            icao24,
                            callsign,
                            latitude,
                            longitude,
                            altitude,
                            velocity,
                            heading,
                            on_ground,
                            vertical_rate,
                            EXTRACT(EPOCH FROM last_seen)::bigint as last_seen,
                            flight_phase,
                            data_source
                        FROM flight_status
                        WHERE last_seen > NOW() - INTERVAL '5 minutes'
                        ORDER BY last_seen DESC
                        LIMIT %s
                        """,
                        (limit,),
                    )
                    rows = cur.fetchall()
                    logger.info(f"Lakebase returned {len(rows)} flights")
                    return [dict(row) for row in rows]

        except Exception as e:
            logger.warning(f"Lakebase query failed: {e}")
            # Invalidate cached credentials on failure (might be expired)
            self._cached_credentials = None
            return None

    def get_flight_by_icao24(self, icao24: str) -> Optional[dict]:
        """
        Fetch a specific flight by ICAO24 address.

        Args:
            icao24: The ICAO24 address to look up.

        Returns:
            Flight dictionary, or None if not found.
        """
        if not self.is_available:
            return None

        try:
            with self._get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(
                        """
                        SELECT
                            icao24,
                            callsign,
                            latitude,
                            longitude,
                            altitude,
                            velocity,
                            heading,
                            on_ground,
                            vertical_rate,
                            EXTRACT(EPOCH FROM last_seen)::bigint as last_seen,
                            flight_phase,
                            data_source
                        FROM flight_status
                        WHERE icao24 = %s
                        """,
                        (icao24,),
                    )
                    row = cur.fetchone()
                    return dict(row) if row else None

        except Exception as e:
            logger.warning(f"Lakebase query failed for {icao24}: {e}")
            self._cached_credentials = None
            return None

    def health_check(self) -> bool:
        """Check if Lakebase connection is healthy."""
        if not self.is_available:
            return False

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    return True
        except Exception as e:
            logger.warning(f"Lakebase health check failed: {e}")
            self._cached_credentials = None
            return False

    # =========================================================================
    # Weather Operations
    # =========================================================================

    def upsert_weather(self, obs: dict) -> bool:
        """
        Upsert weather observation to Lakebase.

        Args:
            obs: Weather observation dictionary with METAR/TAF data.

        Returns:
            True if successful, False otherwise.
        """
        if not self.is_available:
            return False

        try:
            import json
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO weather_observations (
                            station, observation_time, wind_direction, wind_speed_kts,
                            wind_gust_kts, visibility_sm, clouds, temperature_c,
                            dewpoint_c, altimeter_inhg, weather, flight_category,
                            raw_metar, taf_text, taf_valid_from, taf_valid_to
                        ) VALUES (
                            %(station)s, %(observation_time)s, %(wind_direction)s, %(wind_speed_kts)s,
                            %(wind_gust_kts)s, %(visibility_sm)s, %(clouds)s, %(temperature_c)s,
                            %(dewpoint_c)s, %(altimeter_inhg)s, %(weather)s, %(flight_category)s,
                            %(raw_metar)s, %(taf_text)s, %(taf_valid_from)s, %(taf_valid_to)s
                        )
                        ON CONFLICT (station) DO UPDATE SET
                            observation_time = EXCLUDED.observation_time,
                            wind_direction = EXCLUDED.wind_direction,
                            wind_speed_kts = EXCLUDED.wind_speed_kts,
                            wind_gust_kts = EXCLUDED.wind_gust_kts,
                            visibility_sm = EXCLUDED.visibility_sm,
                            clouds = EXCLUDED.clouds,
                            temperature_c = EXCLUDED.temperature_c,
                            dewpoint_c = EXCLUDED.dewpoint_c,
                            altimeter_inhg = EXCLUDED.altimeter_inhg,
                            weather = EXCLUDED.weather,
                            flight_category = EXCLUDED.flight_category,
                            raw_metar = EXCLUDED.raw_metar,
                            taf_text = EXCLUDED.taf_text,
                            taf_valid_from = EXCLUDED.taf_valid_from,
                            taf_valid_to = EXCLUDED.taf_valid_to
                        """,
                        {
                            **obs,
                            "clouds": json.dumps(obs.get("clouds", [])),
                            "weather": json.dumps(obs.get("weather", [])),
                        }
                    )
                    conn.commit()
                    return True

        except Exception as e:
            logger.warning(f"Lakebase weather upsert failed: {e}")
            self._cached_credentials = None
            return False

    def get_weather(self, station: str) -> Optional[dict]:
        """
        Get weather observation from Lakebase.

        Args:
            station: ICAO station identifier (e.g., KSFO).

        Returns:
            Weather observation dictionary, or None if not found.
        """
        if not self.is_available:
            return None

        try:
            import json
            with self._get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(
                        """
                        SELECT
                            station, observation_time, wind_direction, wind_speed_kts,
                            wind_gust_kts, visibility_sm, clouds, temperature_c,
                            dewpoint_c, altimeter_inhg, weather, flight_category,
                            raw_metar, taf_text, taf_valid_from, taf_valid_to
                        FROM weather_observations
                        WHERE station = %s
                        """,
                        (station,),
                    )
                    row = cur.fetchone()
                    if row:
                        result = dict(row)
                        # Parse JSON fields
                        if result.get("clouds"):
                            result["clouds"] = json.loads(result["clouds"]) if isinstance(result["clouds"], str) else result["clouds"]
                        if result.get("weather"):
                            result["weather"] = json.loads(result["weather"]) if isinstance(result["weather"], str) else result["weather"]
                        return result
                    return None

        except Exception as e:
            logger.warning(f"Lakebase weather query failed for {station}: {e}")
            self._cached_credentials = None
            return None

    # =========================================================================
    # Schedule Operations (airport-scoped)
    # =========================================================================

    def upsert_schedule(self, flights: list[dict], airport_icao: str = "KSFO") -> int:
        """
        Upsert flight schedule to Lakebase.

        Args:
            flights: List of scheduled flight dictionaries.
            airport_icao: ICAO code to scope the schedule to.

        Returns:
            Number of flights upserted.
        """
        if not self.is_available or not flights:
            return 0

        self._ensure_airport_columns()

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    count = 0
                    for flight in flights:
                        cur.execute(
                            """
                            INSERT INTO flight_schedule (
                                airport_icao, flight_number, airline, airline_code, origin, destination,
                                scheduled_time, estimated_time, actual_time, gate, status,
                                delay_minutes, delay_reason, aircraft_type, flight_type
                            ) VALUES (
                                %(airport_icao)s, %(flight_number)s, %(airline)s, %(airline_code)s, %(origin)s, %(destination)s,
                                %(scheduled_time)s, %(estimated_time)s, %(actual_time)s, %(gate)s, %(status)s,
                                %(delay_minutes)s, %(delay_reason)s, %(aircraft_type)s, %(flight_type)s
                            )
                            ON CONFLICT (airport_icao, flight_number, scheduled_time) DO UPDATE SET
                                airline = EXCLUDED.airline,
                                airline_code = EXCLUDED.airline_code,
                                origin = EXCLUDED.origin,
                                destination = EXCLUDED.destination,
                                estimated_time = EXCLUDED.estimated_time,
                                actual_time = EXCLUDED.actual_time,
                                gate = EXCLUDED.gate,
                                status = EXCLUDED.status,
                                delay_minutes = EXCLUDED.delay_minutes,
                                delay_reason = EXCLUDED.delay_reason,
                                aircraft_type = EXCLUDED.aircraft_type,
                                flight_type = EXCLUDED.flight_type
                            """,
                            {**flight, "airport_icao": airport_icao}
                        )
                        count += 1
                    conn.commit()
                    logger.info(f"Upserted {count} flights to Lakebase schedule for {airport_icao}")
                    return count

        except Exception as e:
            logger.warning(f"Lakebase schedule upsert failed: {e}")
            self._cached_credentials = None
            return 0

    def get_schedule(
        self,
        flight_type: Optional[str] = None,
        hours_behind: int = 1,
        hours_ahead: int = 2,
        limit: int = 100,
        airport_icao: str = "KSFO",
    ) -> Optional[list[dict]]:
        """
        Get flight schedule from Lakebase.

        Args:
            flight_type: "arrival" or "departure", or None for both.
            hours_behind: Hours into past to include.
            hours_ahead: Hours into future to include.
            limit: Maximum flights to return.
            airport_icao: ICAO code to filter by.

        Returns:
            List of scheduled flights, or None if query fails.
        """
        if not self.is_available:
            return None

        self._ensure_airport_columns()

        try:
            with self._get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    type_clause = ""
                    params: list = [airport_icao]
                    if flight_type:
                        type_clause = "AND flight_type = %s"
                        params.append(flight_type)

                    cur.execute(
                        f"""
                        SELECT
                            flight_number, airline, airline_code, origin, destination,
                            scheduled_time, estimated_time, actual_time, gate, status,
                            delay_minutes, delay_reason, aircraft_type, flight_type
                        FROM flight_schedule
                        WHERE airport_icao = %s
                        AND scheduled_time BETWEEN NOW() - INTERVAL '%s hours' AND NOW() + INTERVAL '%s hours'
                        {type_clause}
                        ORDER BY scheduled_time ASC
                        LIMIT %s
                        """,
                        params[:1] + [hours_behind, hours_ahead] + params[1:] + [limit],
                    )
                    rows = cur.fetchall()
                    return [dict(row) for row in rows]

        except Exception as e:
            logger.warning(f"Lakebase schedule query failed: {e}")
            self._cached_credentials = None
            return None

    def clear_old_schedule(self, hours_old: int = 24, airport_icao: str = "KSFO") -> int:
        """Remove old schedule entries from Lakebase for a specific airport."""
        if not self.is_available:
            return 0

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM flight_schedule WHERE airport_icao = %s AND scheduled_time < NOW() - INTERVAL '%s hours'",
                        (airport_icao, hours_old)
                    )
                    deleted = cur.rowcount
                    conn.commit()
                    return deleted

        except Exception as e:
            logger.warning(f"Lakebase schedule cleanup failed: {e}")
            self._cached_credentials = None
            return 0

    def has_synthetic_data(self, airport_icao: str) -> bool:
        """Check if Lakebase has synthetic schedule data for this airport.

        Args:
            airport_icao: ICAO code to check.

        Returns:
            True if flight_schedule has rows for this airport.
        """
        if not self.is_available:
            return False

        self._ensure_airport_columns()

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT EXISTS(SELECT 1 FROM flight_schedule WHERE airport_icao = %s LIMIT 1)",
                        (airport_icao,),
                    )
                    row = cur.fetchone()
                    return row[0] if row else False

        except Exception as e:
            logger.warning(f"Lakebase has_synthetic_data check failed for {airport_icao}: {e}")
            self._cached_credentials = None
            return False

    # =========================================================================
    # Baggage Operations (airport-scoped)
    # =========================================================================

    def upsert_baggage_stats(self, stats: dict, airport_icao: str = "KSFO") -> bool:
        """
        Upsert baggage statistics for a flight to Lakebase.

        Args:
            stats: Baggage stats dictionary with flight_number as key.
            airport_icao: ICAO code to scope the data to.

        Returns:
            True if successful, False otherwise.
        """
        if not self.is_available:
            return False

        self._ensure_airport_columns()

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO baggage_status (
                            airport_icao, flight_number, total_bags, checked_in, loaded, unloaded,
                            on_carousel, loading_progress_pct, connecting_bags, misconnects, carousel
                        ) VALUES (
                            %(airport_icao)s, %(flight_number)s, %(total_bags)s, %(checked_in)s, %(loaded)s, %(unloaded)s,
                            %(on_carousel)s, %(loading_progress_pct)s, %(connecting_bags)s, %(misconnects)s, %(carousel)s
                        )
                        ON CONFLICT (airport_icao, flight_number) DO UPDATE SET
                            total_bags = EXCLUDED.total_bags,
                            checked_in = EXCLUDED.checked_in,
                            loaded = EXCLUDED.loaded,
                            unloaded = EXCLUDED.unloaded,
                            on_carousel = EXCLUDED.on_carousel,
                            loading_progress_pct = EXCLUDED.loading_progress_pct,
                            connecting_bags = EXCLUDED.connecting_bags,
                            misconnects = EXCLUDED.misconnects,
                            carousel = EXCLUDED.carousel
                        """,
                        {**stats, "airport_icao": airport_icao}
                    )
                    conn.commit()
                    return True

        except Exception as e:
            logger.warning(f"Lakebase baggage upsert failed: {e}")
            self._cached_credentials = None
            return False

    def get_baggage_stats(self, flight_number: str, airport_icao: str = "KSFO") -> Optional[dict]:
        """
        Get baggage statistics for a flight from Lakebase.

        Args:
            flight_number: Flight number to look up.
            airport_icao: ICAO code to scope the query to.

        Returns:
            Baggage stats dictionary, or None if not found.
        """
        if not self.is_available:
            return None

        self._ensure_airport_columns()

        try:
            with self._get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(
                        """
                        SELECT
                            flight_number, total_bags, checked_in, loaded, unloaded,
                            on_carousel, loading_progress_pct, connecting_bags, misconnects, carousel
                        FROM baggage_status
                        WHERE airport_icao = %s AND flight_number = %s
                        """,
                        (airport_icao, flight_number),
                    )
                    row = cur.fetchone()
                    return dict(row) if row else None

        except Exception as e:
            logger.warning(f"Lakebase baggage query failed for {flight_number}: {e}")
            self._cached_credentials = None
            return None

    # =========================================================================
    # GSE Fleet Operations (airport-scoped)
    # =========================================================================

    def upsert_gse_fleet(self, units: list[dict], airport_icao: str = "KSFO") -> int:
        """
        Upsert GSE fleet units to Lakebase.

        Args:
            units: List of GSE unit dictionaries.
            airport_icao: ICAO code to scope the data to.

        Returns:
            Number of units upserted.
        """
        if not self.is_available or not units:
            return 0

        self._ensure_airport_columns()

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    count = 0
                    for unit in units:
                        cur.execute(
                            """
                            INSERT INTO gse_fleet (
                                airport_icao, unit_id, gse_type, status, assigned_flight,
                                assigned_gate, position_x, position_y
                            ) VALUES (
                                %(airport_icao)s, %(unit_id)s, %(gse_type)s, %(status)s, %(assigned_flight)s,
                                %(assigned_gate)s, %(position_x)s, %(position_y)s
                            )
                            ON CONFLICT (airport_icao, unit_id) DO UPDATE SET
                                gse_type = EXCLUDED.gse_type,
                                status = EXCLUDED.status,
                                assigned_flight = EXCLUDED.assigned_flight,
                                assigned_gate = EXCLUDED.assigned_gate,
                                position_x = EXCLUDED.position_x,
                                position_y = EXCLUDED.position_y
                            """,
                            {**unit, "airport_icao": airport_icao}
                        )
                        count += 1
                    conn.commit()
                    return count

        except Exception as e:
            logger.warning(f"Lakebase GSE fleet upsert failed: {e}")
            self._cached_credentials = None
            return 0

    def get_gse_fleet(self, airport_icao: str = "KSFO") -> Optional[list[dict]]:
        """
        Get all GSE fleet units from Lakebase.

        Args:
            airport_icao: ICAO code to filter by.

        Returns:
            List of GSE unit dictionaries, or None if query fails.
        """
        if not self.is_available:
            return None

        self._ensure_airport_columns()

        try:
            with self._get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(
                        """
                        SELECT
                            unit_id, gse_type, status, assigned_flight,
                            assigned_gate, position_x, position_y
                        FROM gse_fleet
                        WHERE airport_icao = %s
                        ORDER BY gse_type, unit_id
                        """,
                        (airport_icao,)
                    )
                    rows = cur.fetchall()
                    return [dict(row) for row in rows]

        except Exception as e:
            logger.warning(f"Lakebase GSE fleet query failed: {e}")
            self._cached_credentials = None
            return None

    # =========================================================================
    # Airport Config Cache Operations
    # =========================================================================

    def _ensure_airport_config_table(self) -> bool:
        """Create airport_config_cache table if it doesn't exist."""
        if not self.is_available:
            return False

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS airport_config_cache (
                            icao_code VARCHAR(10) PRIMARY KEY,
                            config_json JSONB NOT NULL,
                            updated_at TIMESTAMPTZ DEFAULT NOW()
                        )
                        """
                    )
                    conn.commit()
                    return True

        except Exception as e:
            logger.warning(f"Failed to create airport_config_cache table: {e}")
            self._cached_credentials = None
            return False

    def upsert_airport_config(self, icao_code: str, config: dict) -> bool:
        """
        Upsert airport configuration to Lakebase cache.

        Args:
            icao_code: ICAO airport code (e.g., KSFO).
            config: Airport configuration dictionary.

        Returns:
            True if successful, False otherwise.
        """
        if not self.is_available:
            return False

        try:
            import json
            self._ensure_airport_config_table()

            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO airport_config_cache (icao_code, config_json, updated_at)
                        VALUES (%s, %s, NOW())
                        ON CONFLICT (icao_code) DO UPDATE SET
                            config_json = EXCLUDED.config_json,
                            updated_at = EXCLUDED.updated_at
                        """,
                        (icao_code, json.dumps(config)),
                    )
                    conn.commit()
                    logger.info(f"Cached airport config for {icao_code} in Lakebase")
                    return True

        except Exception as e:
            logger.warning(f"Lakebase airport config upsert failed: {e}")
            self._cached_credentials = None
            return False

    def get_airport_config(self, icao_code: str) -> Optional[dict]:
        """
        Get airport configuration from Lakebase cache.

        Args:
            icao_code: ICAO airport code (e.g., KSFO).

        Returns:
            Airport configuration dictionary, or None if not found.
        """
        if not self.is_available:
            return None

        try:
            import json
            self._ensure_airport_config_table()

            with self._get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(
                        "SELECT config_json FROM airport_config_cache WHERE icao_code = %s",
                        (icao_code,),
                    )
                    row = cur.fetchone()
                    if row:
                        config = row["config_json"]
                        if isinstance(config, str):
                            config = json.loads(config)
                        return config
                    return None

        except Exception as e:
            logger.warning(f"Lakebase airport config query failed for {icao_code}: {e}")
            self._cached_credentials = None
            return None

    # =========================================================================
    # GSE Turnaround Operations (airport-scoped)
    # =========================================================================

    def upsert_turnaround(self, turnaround: dict, airport_icao: str = "KSFO") -> bool:
        """
        Upsert turnaround status to Lakebase.

        Args:
            turnaround: Turnaround status dictionary.
            airport_icao: ICAO code to scope the data to.

        Returns:
            True if successful, False otherwise.
        """
        if not self.is_available:
            return False

        self._ensure_airport_columns()

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO gse_turnaround (
                            airport_icao, icao24, flight_number, gate, arrival_time, current_phase,
                            phase_progress_pct, total_progress_pct, estimated_departure, aircraft_type
                        ) VALUES (
                            %(airport_icao)s, %(icao24)s, %(flight_number)s, %(gate)s, %(arrival_time)s, %(current_phase)s,
                            %(phase_progress_pct)s, %(total_progress_pct)s, %(estimated_departure)s, %(aircraft_type)s
                        )
                        ON CONFLICT (airport_icao, icao24) DO UPDATE SET
                            flight_number = EXCLUDED.flight_number,
                            gate = EXCLUDED.gate,
                            arrival_time = EXCLUDED.arrival_time,
                            current_phase = EXCLUDED.current_phase,
                            phase_progress_pct = EXCLUDED.phase_progress_pct,
                            total_progress_pct = EXCLUDED.total_progress_pct,
                            estimated_departure = EXCLUDED.estimated_departure,
                            aircraft_type = EXCLUDED.aircraft_type
                        """,
                        {**turnaround, "airport_icao": airport_icao}
                    )
                    conn.commit()
                    return True

        except Exception as e:
            logger.warning(f"Lakebase turnaround upsert failed: {e}")
            self._cached_credentials = None
            return False

    def get_turnaround(self, icao24: str, airport_icao: str = "KSFO") -> Optional[dict]:
        """
        Get turnaround status from Lakebase.

        Args:
            icao24: Aircraft ICAO24 address.
            airport_icao: ICAO code to scope the query to.

        Returns:
            Turnaround status dictionary, or None if not found.
        """
        if not self.is_available:
            return None

        self._ensure_airport_columns()

        try:
            with self._get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(
                        """
                        SELECT
                            icao24, flight_number, gate, arrival_time, current_phase,
                            phase_progress_pct, total_progress_pct, estimated_departure, aircraft_type
                        FROM gse_turnaround
                        WHERE airport_icao = %s AND icao24 = %s
                        """,
                        (airport_icao, icao24),
                    )
                    row = cur.fetchone()
                    return dict(row) if row else None

        except Exception as e:
            logger.warning(f"Lakebase turnaround query failed for {icao24}: {e}")
            self._cached_credentials = None
            return None

    def delete_turnaround(self, icao24: str, airport_icao: str = "KSFO") -> bool:
        """Delete turnaround when aircraft departs."""
        if not self.is_available:
            return False

        self._ensure_airport_columns()

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM gse_turnaround WHERE airport_icao = %s AND icao24 = %s",
                        (airport_icao, icao24)
                    )
                    conn.commit()
                    return cur.rowcount > 0

        except Exception as e:
            logger.warning(f"Lakebase turnaround delete failed for {icao24}: {e}")
            self._cached_credentials = None
            return False


    # =========================================================================
    # ML Training Data Tables (append-only)
    # =========================================================================

    def _ensure_ml_tables(self) -> None:
        """Create ML training data tables if they don't exist.

        Safe to call multiple times — only runs once per service lifetime.
        """
        if self._ml_tables_ensured or not self.is_available:
            return

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS flight_position_snapshots (
                            id BIGSERIAL,
                            session_id VARCHAR(36) NOT NULL,
                            airport_icao VARCHAR(4) NOT NULL,
                            icao24 VARCHAR(10) NOT NULL,
                            callsign VARCHAR(10),
                            latitude DOUBLE PRECISION,
                            longitude DOUBLE PRECISION,
                            altitude DOUBLE PRECISION,
                            velocity DOUBLE PRECISION,
                            heading DOUBLE PRECISION,
                            vertical_rate DOUBLE PRECISION,
                            on_ground BOOLEAN,
                            flight_phase VARCHAR(20),
                            aircraft_type VARCHAR(10),
                            assigned_gate VARCHAR(10),
                            origin_airport VARCHAR(10),
                            destination_airport VARCHAR(10),
                            snapshot_time TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                    """)
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS flight_phase_transitions (
                            id BIGSERIAL,
                            session_id VARCHAR(36) NOT NULL,
                            airport_icao VARCHAR(4) NOT NULL,
                            icao24 VARCHAR(10) NOT NULL,
                            callsign VARCHAR(10),
                            from_phase VARCHAR(20) NOT NULL,
                            to_phase VARCHAR(20) NOT NULL,
                            latitude DOUBLE PRECISION,
                            longitude DOUBLE PRECISION,
                            altitude DOUBLE PRECISION,
                            aircraft_type VARCHAR(10),
                            assigned_gate VARCHAR(10),
                            event_time TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                    """)
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS gate_assignment_events (
                            id BIGSERIAL,
                            session_id VARCHAR(36) NOT NULL,
                            airport_icao VARCHAR(4) NOT NULL,
                            icao24 VARCHAR(10) NOT NULL,
                            callsign VARCHAR(10),
                            gate VARCHAR(10) NOT NULL,
                            event_type VARCHAR(10) NOT NULL,
                            aircraft_type VARCHAR(10),
                            event_time TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                    """)
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS ml_predictions (
                            id BIGSERIAL,
                            session_id VARCHAR(36) NOT NULL,
                            airport_icao VARCHAR(4) NOT NULL,
                            prediction_type VARCHAR(30) NOT NULL,
                            icao24 VARCHAR(10),
                            result_json JSONB,
                            event_time TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                    """)
                    # Indexes for efficient querying
                    cur.execute("""
                        CREATE INDEX IF NOT EXISTS idx_fps_session_airport
                        ON flight_position_snapshots (session_id, airport_icao, snapshot_time)
                    """)
                    cur.execute("""
                        CREATE INDEX IF NOT EXISTS idx_fpt_session_airport
                        ON flight_phase_transitions (session_id, airport_icao, event_time)
                    """)
                    cur.execute("""
                        CREATE INDEX IF NOT EXISTS idx_gae_session_airport
                        ON gate_assignment_events (session_id, airport_icao, event_time)
                    """)
                    cur.execute("""
                        CREATE INDEX IF NOT EXISTS idx_mlp_session_airport
                        ON ml_predictions (session_id, airport_icao, event_time)
                    """)
                    conn.commit()
            self._ml_tables_ensured = True
            logger.debug("Ensured ML training data tables exist")
        except Exception as e:
            logger.debug(f"ML tables creation check: {e}")

    def insert_flight_snapshots(
        self, snapshots: list[dict], session_id: str, airport_icao: str
    ) -> int:
        """Batch-insert flight position snapshots."""
        if not self.is_available or not snapshots:
            return 0

        self._ensure_ml_tables()

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    values = [
                        (
                            session_id, airport_icao,
                            s["icao24"], s.get("callsign"),
                            s.get("latitude"), s.get("longitude"),
                            s.get("altitude"), s.get("velocity"),
                            s.get("heading"), s.get("vertical_rate"),
                            s.get("on_ground"), s.get("flight_phase"),
                            s.get("aircraft_type"), s.get("assigned_gate"),
                            s.get("origin_airport"), s.get("destination_airport"),
                            s.get("snapshot_time"),
                        )
                        for s in snapshots
                    ]
                    execute_values(
                        cur,
                        """INSERT INTO flight_position_snapshots (
                            session_id, airport_icao,
                            icao24, callsign,
                            latitude, longitude,
                            altitude, velocity,
                            heading, vertical_rate,
                            on_ground, flight_phase,
                            aircraft_type, assigned_gate,
                            origin_airport, destination_airport,
                            snapshot_time
                        ) VALUES %s""",
                        values,
                    )
                    conn.commit()
                    return len(values)
        except Exception as e:
            logger.warning(f"Failed to insert flight snapshots: {e}")
            self._cached_credentials = None
            return 0

    def insert_phase_transitions(
        self, events: list[dict], session_id: str, airport_icao: str
    ) -> int:
        """Batch-insert phase transition events."""
        if not self.is_available or not events:
            return 0

        self._ensure_ml_tables()

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    values = [
                        (
                            session_id, airport_icao,
                            e["icao24"], e.get("callsign"),
                            e["from_phase"], e["to_phase"],
                            e.get("latitude"), e.get("longitude"),
                            e.get("altitude"), e.get("aircraft_type"),
                            e.get("assigned_gate"), e.get("event_time"),
                        )
                        for e in events
                    ]
                    execute_values(
                        cur,
                        """INSERT INTO flight_phase_transitions (
                            session_id, airport_icao,
                            icao24, callsign,
                            from_phase, to_phase,
                            latitude, longitude,
                            altitude, aircraft_type,
                            assigned_gate, event_time
                        ) VALUES %s""",
                        values,
                    )
                    conn.commit()
                    return len(values)
        except Exception as e:
            logger.warning(f"Failed to insert phase transitions: {e}")
            self._cached_credentials = None
            return 0

    def insert_gate_events(
        self, events: list[dict], session_id: str, airport_icao: str
    ) -> int:
        """Batch-insert gate assignment events."""
        if not self.is_available or not events:
            return 0

        self._ensure_ml_tables()

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    values = [
                        (
                            session_id, airport_icao,
                            e["icao24"], e.get("callsign"),
                            e["gate"], e["event_type"],
                            e.get("aircraft_type"), e.get("event_time"),
                        )
                        for e in events
                    ]
                    execute_values(
                        cur,
                        """INSERT INTO gate_assignment_events (
                            session_id, airport_icao,
                            icao24, callsign,
                            gate, event_type,
                            aircraft_type, event_time
                        ) VALUES %s""",
                        values,
                    )
                    conn.commit()
                    return len(values)
        except Exception as e:
            logger.warning(f"Failed to insert gate events: {e}")
            self._cached_credentials = None
            return 0

    def insert_ml_predictions(
        self, predictions: list[dict], session_id: str, airport_icao: str
    ) -> int:
        """Batch-insert ML prediction results."""
        if not self.is_available or not predictions:
            return 0

        self._ensure_ml_tables()

        try:
            import json
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    values = [
                        (
                            session_id, airport_icao,
                            p["prediction_type"], p.get("icao24"),
                            json.dumps(p.get("result_json", {})),
                            p.get("event_time"),
                        )
                        for p in predictions
                    ]
                    execute_values(
                        cur,
                        """INSERT INTO ml_predictions (
                            session_id, airport_icao,
                            prediction_type, icao24,
                            result_json, event_time
                        ) VALUES %s""",
                        values,
                    )
                    conn.commit()
                    return len(values)
        except Exception as e:
            logger.warning(f"Failed to insert ML predictions: {e}")
            self._cached_credentials = None
            return 0


# Singleton instance
_lakebase_service: Optional[LakebaseService] = None


def get_lakebase_service() -> LakebaseService:
    """Get or create Lakebase service singleton."""
    global _lakebase_service
    if _lakebase_service is None:
        _lakebase_service = LakebaseService()
    return _lakebase_service
