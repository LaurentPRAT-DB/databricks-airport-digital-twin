"""Delta table service for querying flight data via Databricks SQL.

This service connects to Databricks SQL Warehouse to query Delta tables
in Unity Catalog, providing near real-time flight data from the Gold layer.
"""

import os
import logging
from typing import Optional

try:
    from databricks import sql
    DATABRICKS_SQL_AVAILABLE = True
except ImportError:
    DATABRICKS_SQL_AVAILABLE = False

logger = logging.getLogger(__name__)


class DeltaService:
    """Service for querying flight data from Delta tables via Databricks SQL."""

    def __init__(self):
        """Initialize Databricks SQL connection parameters from environment."""
        self._host = os.getenv("DATABRICKS_HOST") or os.getenv("DATABRICKS_SERVER_HOSTNAME")
        self._http_path = os.getenv("DATABRICKS_HTTP_PATH") or os.getenv("DATABRICKS_WAREHOUSE_HTTP_PATH")
        self._token = os.getenv("DATABRICKS_TOKEN") or os.getenv("DATABRICKS_ACCESS_TOKEN")
        self._catalog = os.getenv("DATABRICKS_CATALOG", "main")
        self._schema = os.getenv("DATABRICKS_SCHEMA", "airport_digital_twin")

        # For Databricks Apps, use OAuth
        self._use_oauth = os.getenv("DATABRICKS_USE_OAUTH", "false").lower() == "true"

    @property
    def is_available(self) -> bool:
        """Check if Databricks SQL connection is configured."""
        if not DATABRICKS_SQL_AVAILABLE:
            logger.debug("databricks-sql-connector not installed - Delta unavailable")
            return False

        # Need host and http_path at minimum
        # Token can come from default auth chain in Databricks Apps
        return bool(self._host and self._http_path)

    def _get_connection(self):
        """Create a new Databricks SQL connection."""
        connection_params = {
            "server_hostname": self._host,
            "http_path": self._http_path,
            "catalog": self._catalog,
            "schema": self._schema,
        }

        if self._token:
            # Local dev: use explicit token
            connection_params["access_token"] = self._token
        else:
            # Databricks Apps: use ambient M2M credentials from the
            # service principal.  Setting auth_type prevents the
            # databricks-sql-connector from falling back to U2M OAuth
            # which opens a localhost listener that hangs in production.
            connection_params["auth_type"] = "databricks-oauth"

        # Prevent indefinite hang if warehouse is stopped or unreachable
        connection_params["_socket_timeout"] = 10

        return sql.connect(**connection_params)

    def get_flights(self, limit: int = 100) -> Optional[list[dict]]:
        """
        Fetch current flight positions from Delta Gold table.

        Args:
            limit: Maximum number of flights to return.

        Returns:
            List of flight dictionaries, or None if query fails.
        """
        if not self.is_available:
            return None

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    # Use parameterized query to prevent SQL injection
                    query = f"""
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
                            UNIX_TIMESTAMP(last_seen) as last_seen,
                            flight_phase,
                            data_source
                        FROM {self._catalog}.{self._schema}.flight_status_gold
                        WHERE last_seen > CURRENT_TIMESTAMP() - INTERVAL 5 MINUTES
                        ORDER BY last_seen DESC
                        LIMIT :limit
                    """
                    cursor.execute(query, {"limit": limit})
                    columns = [desc[0] for desc in cursor.description]
                    rows = cursor.fetchall()

                    flights = []
                    for row in rows:
                        flight = dict(zip(columns, row))
                        flights.append(flight)

                    logger.info(f"Delta tables returned {len(flights)} flights")
                    return flights

        except Exception as e:
            logger.warning(f"Delta table query failed: {e}")
            return None

    def get_flight_by_icao24(self, icao24: str) -> Optional[dict]:
        """
        Fetch a specific flight by ICAO24 address from Delta tables.

        Args:
            icao24: The ICAO24 address to look up.

        Returns:
            Flight dictionary, or None if not found.
        """
        if not self.is_available:
            return None

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    # Use parameterized query to prevent SQL injection
                    query = f"""
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
                            UNIX_TIMESTAMP(last_seen) as last_seen,
                            flight_phase,
                            data_source
                        FROM {self._catalog}.{self._schema}.flight_status_gold
                        WHERE icao24 = :icao24
                    """
                    cursor.execute(query, {"icao24": icao24})
                    columns = [desc[0] for desc in cursor.description]
                    row = cursor.fetchone()

                    if row:
                        return dict(zip(columns, row))
                    return None

        except Exception as e:
            logger.warning(f"Delta table query failed for {icao24}: {e}")
            return None

    def get_trajectory(
        self,
        icao24: str,
        minutes: int = 60,
        limit: int = 1000,
    ) -> Optional[list[dict]]:
        """
        Fetch trajectory history for a specific flight from Delta.

        Args:
            icao24: The ICAO24 address to get trajectory for.
            minutes: How many minutes of history to retrieve.
            limit: Maximum number of positions to return.

        Returns:
            List of position dictionaries ordered by time, or None if query fails.
        """
        if not self.is_available:
            return None

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    # Use parameterized query to prevent SQL injection
                    # Note: INTERVAL requires literal value, so we validate minutes as int
                    if not isinstance(minutes, int) or minutes < 1 or minutes > 1440:
                        minutes = 60  # Safe default
                    query = f"""
                        SELECT
                            icao24,
                            callsign,
                            latitude,
                            longitude,
                            altitude,
                            velocity,
                            heading,
                            vertical_rate,
                            on_ground,
                            flight_phase,
                            UNIX_TIMESTAMP(recorded_at) as timestamp
                        FROM {self._catalog}.{self._schema}.flight_positions_history
                        WHERE icao24 = :icao24
                          AND recorded_at > CURRENT_TIMESTAMP() - INTERVAL {minutes} MINUTE
                        ORDER BY recorded_at ASC
                        LIMIT :limit
                    """
                    cursor.execute(query, {"icao24": icao24, "limit": limit})
                    columns = [desc[0] for desc in cursor.description]
                    rows = cursor.fetchall()

                    positions = [dict(zip(columns, row)) for row in rows]
                    logger.info(f"Trajectory for {icao24}: {len(positions)} positions from Delta")
                    return positions

        except Exception as e:
            logger.warning(f"Trajectory query failed for {icao24}: {e}")
            return None

    def health_check(self) -> bool:
        """Check if Databricks SQL connection is healthy."""
        if not self.is_available:
            return False

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT 1")
                    return True
        except Exception as e:
            logger.warning(f"Delta health check failed: {e}")
            return False


# Singleton instance
_delta_service: Optional[DeltaService] = None


def get_delta_service() -> DeltaService:
    """Get or create Delta service singleton."""
    global _delta_service
    if _delta_service is None:
        _delta_service = DeltaService()
    return _delta_service
