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
    from psycopg2.extras import RealDictCursor
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

        w = WorkspaceClient()

        # Generate database credential for Lakebase Autoscaling
        cred = w.postgres.generate_database_credential(endpoint=endpoint_name)
        token = cred.token

        # Get current user email
        me = w.current_user.me()
        user_email = me.user_name

        return (token, user_email)

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


# Singleton instance
_lakebase_service: Optional[LakebaseService] = None


def get_lakebase_service() -> LakebaseService:
    """Get or create Lakebase service singleton."""
    global _lakebase_service
    if _lakebase_service is None:
        _lakebase_service = LakebaseService()
    return _lakebase_service
