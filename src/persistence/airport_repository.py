"""Airport data repository for Unity Catalog persistence.

Provides CRUD operations for airport configuration data stored in Delta tables.
Supports two execution backends:
1. databricks-sql-connector (preferred in Databricks Apps — uses ambient M2M OAuth)
2. WorkspaceClient statement execution (fallback for notebooks, local dev)
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

from src.persistence.airport_tables import (
    DEFAULT_CATALOG,
    DEFAULT_SCHEMA,
    create_tables,
)

logger = logging.getLogger(__name__)

# Try to import databricks-sql-connector (preferred for Apps)
try:
    from databricks import sql as databricks_sql
    DATABRICKS_SQL_AVAILABLE = True
except ImportError:
    DATABRICKS_SQL_AVAILABLE = False


class AirportRepository:
    """Repository for airport configuration persistence."""

    def __init__(
        self,
        client=None,
        warehouse_id: Optional[str] = None,
        catalog: str = DEFAULT_CATALOG,
        schema: str = DEFAULT_SCHEMA,
        use_sql_connector: bool = False,
        host: Optional[str] = None,
        http_path: Optional[str] = None,
        use_oauth: bool = False,
        token: Optional[str] = None,
    ):
        """
        Initialize repository.

        Args:
            client: Databricks workspace client (created if not provided)
            warehouse_id: SQL warehouse ID
            catalog: Unity Catalog name
            schema: Schema name
            use_sql_connector: If True, prefer databricks-sql-connector over WorkspaceClient
            host: Databricks host (for SQL connector mode)
            http_path: SQL warehouse HTTP path (for SQL connector mode)
            use_oauth: Use ambient OAuth credentials (for Databricks Apps)
            token: PAT token (for local dev with SQL connector)
        """
        self._client = client
        self._warehouse_id = warehouse_id or "b868e84cedeb4262"  # Default warehouse
        self._catalog = catalog
        self._schema = schema
        self._tables_initialized = False
        self._use_sql_connector = use_sql_connector and DATABRICKS_SQL_AVAILABLE
        self._host = host
        self._http_path = http_path
        self._use_oauth = use_oauth
        self._token = token

    @property
    def client(self):
        """Get or create workspace client.

        Uses a threaded timeout to prevent WorkspaceClient() from hanging
        on U2M browser-based OAuth in headless environments (Databricks Apps).
        """
        if self._client is None:
            from databricks.sdk import WorkspaceClient
            import threading

            result: list = []

            def _try_create():
                try:
                    result.append(WorkspaceClient())
                except Exception:
                    pass

            thread = threading.Thread(target=_try_create, daemon=True)
            thread.start()
            thread.join(timeout=10)

            if result:
                self._client = result[0]
            else:
                raise RuntimeError("WorkspaceClient creation timed out (headless env)")
        return self._client

    def _get_sql_connection(self):
        """Create a databricks-sql-connector connection (ambient M2M OAuth)."""
        connection_params = {
            "server_hostname": self._host,
            "http_path": self._http_path,
            "catalog": self._catalog,
            "schema": self._schema,
        }
        if self._token:
            connection_params["access_token"] = self._token
        else:
            # Databricks Apps: use ambient M2M credentials from the
            # service principal.  auth_type prevents the connector from
            # falling back to U2M OAuth (localhost listener).
            connection_params["auth_type"] = "databricks-oauth"
        connection_params["_socket_timeout"] = 30
        return databricks_sql.connect(**connection_params)

    def _execute_via_connector(self, sql: str) -> Optional[list[dict]]:
        """Execute SQL via databricks-sql-connector."""
        with self._get_sql_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql)
                if cursor.description:
                    columns = [desc[0] for desc in cursor.description]
                    rows = cursor.fetchall()
                    if rows:
                        return [dict(zip(columns, row)) for row in rows]
                return None

    def _execute_via_workspace_client(
        self,
        sql: str,
        timeout_seconds: int = 60,
    ) -> Optional[list[dict]]:
        """Execute SQL via WorkspaceClient statement execution."""
        from databricks.sdk.service.sql import StatementState

        response = self.client.statement_execution.execute_statement(
            warehouse_id=self._warehouse_id,
            statement=sql,
            wait_timeout="0s",
        )

        statement_id = response.statement_id

        import time
        start = time.time()
        while time.time() - start < timeout_seconds:
            status = self.client.statement_execution.get_statement(statement_id)
            state = status.status.state

            if state == StatementState.SUCCEEDED:
                if status.result and status.result.data_array:
                    columns = [c.name for c in status.manifest.schema.columns]
                    return [
                        dict(zip(columns, row))
                        for row in status.result.data_array
                    ]
                return None

            if state in (StatementState.FAILED, StatementState.CANCELED, StatementState.CLOSED):
                error = status.status.error
                raise RuntimeError(f"SQL failed: {error}")

            time.sleep(0.5)

        raise TimeoutError(f"SQL timed out after {timeout_seconds}s")

    def _ensure_tables(self) -> None:
        """Ensure all tables exist."""
        if not self._tables_initialized:
            if self._use_sql_connector:
                # With SQL connector, run DDL directly using format strings
                from src.persistence.airport_tables import ALL_TABLES
                # Create schema first
                try:
                    self._execute_via_connector(
                        f"CREATE SCHEMA IF NOT EXISTS {self._catalog}.{self._schema}"
                    )
                except Exception as e:
                    logger.debug(f"Schema creation via connector: {e}")
                for table_name, ddl in ALL_TABLES:
                    try:
                        sql = ddl.format(catalog=self._catalog, schema=self._schema)
                        self._execute_via_connector(sql)
                    except Exception as e:
                        logger.debug(f"Table creation via connector ({table_name}): {e}")
            else:
                create_tables(
                    self.client,
                    self._warehouse_id,
                    self._catalog,
                    self._schema,
                )
            self._tables_initialized = True

    def _table(self, name: str) -> str:
        """Get fully qualified table name."""
        return f"{self._catalog}.{self._schema}.{name}"

    def _execute(
        self,
        sql: str,
        timeout_seconds: int = 60,
    ) -> Optional[list[dict]]:
        """Execute SQL and return results.

        Tries SQL connector first (works in Databricks Apps with ambient OAuth),
        falls back to WorkspaceClient statement execution.
        """
        if self._use_sql_connector:
            try:
                return self._execute_via_connector(sql)
            except Exception as e:
                logger.warning(f"SQL connector execution failed, falling back to WorkspaceClient: {e}")

        return self._execute_via_workspace_client(sql, timeout_seconds)

    # =========================================================================
    # Airport Metadata Operations
    # =========================================================================

    def save_airport_config(self, icao_code: str, config: dict[str, Any]) -> bool:
        """
        Save complete airport configuration to all tables.

        Args:
            icao_code: ICAO airport code
            config: Airport configuration dictionary

        Returns:
            True if successful
        """
        self._ensure_tables()

        now = datetime.now(timezone.utc).isoformat()

        try:
            # Save metadata
            self._save_metadata(icao_code, config, now)

            # Save gates
            gates = config.get("gates", [])
            self._save_gates(icao_code, gates, now)

            # Save terminals
            terminals = config.get("terminals", [])
            self._save_terminals(icao_code, terminals, now)

            # Save runways
            runways = config.get("runways", [])
            self._save_runways(icao_code, runways, now)

            # Save taxiways
            taxiways = config.get("osmTaxiways", [])
            self._save_taxiways(icao_code, taxiways, now)

            # Save aprons
            aprons = config.get("osmAprons", [])
            self._save_aprons(icao_code, aprons, now)

            # Save buildings
            buildings = config.get("buildings", [])
            self._save_buildings(icao_code, buildings, now)

            # Save hangars
            hangars = config.get("osmHangars", [])
            self._save_hangars(icao_code, hangars, now)

            # Save helipads
            helipads = config.get("osmHelipads", [])
            self._save_helipads(icao_code, helipads, now)

            # Save parking positions
            parking_positions = config.get("osmParkingPositions", [])
            self._save_parking_positions(icao_code, parking_positions, now)

            # Save OSM runways (polyline geometry)
            osm_runways = config.get("osmRunways", [])
            self._save_osm_runways(icao_code, osm_runways, now)

            logger.info(f"Saved airport config for {icao_code}")
            return True

        except Exception as e:
            logger.error(f"Failed to save airport config for {icao_code}: {e}")
            raise

    def _save_metadata(self, icao_code: str, config: dict, now: str) -> None:
        """Save airport metadata."""
        # Format sources array for SQL
        sources = config.get('sources', ['OSM'])
        sources_sql = "ARRAY(" + ", ".join(f"'{s}'" for s in sources) + ")"

        sql = f"""
        MERGE INTO {self._table('airport_metadata')} t
        USING (SELECT
            '{icao_code}' as icao_code,
            {self._sql_str(config.get('iataCode'))} as iata_code,
            {self._sql_str(config.get('airportName'))} as name,
            {self._sql_str(config.get('airportOperator'))} as operator,
            {sources_sql} as data_sources,
            TIMESTAMP'{now}' as osm_timestamp,
            TIMESTAMP'{now}' as updated_at
        ) s
        ON t.icao_code = s.icao_code
        WHEN MATCHED THEN UPDATE SET
            iata_code = s.iata_code,
            name = s.name,
            operator = s.operator,
            data_sources = s.data_sources,
            osm_timestamp = s.osm_timestamp,
            updated_at = s.updated_at
        WHEN NOT MATCHED THEN INSERT (
            icao_code, iata_code, name, operator, data_sources,
            osm_timestamp, created_at, updated_at
        ) VALUES (
            s.icao_code, s.iata_code, s.name, s.operator, s.data_sources,
            s.osm_timestamp, TIMESTAMP'{now}', s.updated_at
        )
        """
        self._execute(sql)

    def _save_gates(self, icao_code: str, gates: list[dict], now: str) -> None:
        """Save gates using MERGE."""
        if not gates:
            return

        # Delete existing gates for this airport first (simpler than complex MERGE)
        self._execute(f"DELETE FROM {self._table('gates')} WHERE icao_code = '{icao_code}'")

        # Build INSERT VALUES
        values = []
        for g in gates:
            ref = g.get("ref") or g.get("id", "")
            gate_id = f"{icao_code}_{ref}"
            geo = g.get("geo", {})
            pos = g.get("position", {})

            values.append(f"""(
                '{gate_id}',
                '{icao_code}',
                {self._sql_str(ref)},
                {self._sql_str(g.get('name'))},
                {self._sql_str(g.get('terminal'))},
                {self._sql_str(g.get('level'))},
                {self._sql_str(g.get('operator'))},
                {geo.get('latitude', 0)},
                {geo.get('longitude', 0)},
                {g.get('elevation') or 'NULL'},
                {pos.get('x', 0)},
                {pos.get('y', 0)},
                {pos.get('z', 0)},
                {g.get('osmId') or 'NULL'},
                'OSM',
                TIMESTAMP'{now}',
                TIMESTAMP'{now}'
            )""")

        if values:
            sql = f"""
            INSERT INTO {self._table('gates')} (
                gate_id, icao_code, ref, name, terminal, level, operator,
                latitude, longitude, elevation,
                position_x, position_y, position_z,
                osm_id, source, created_at, updated_at
            ) VALUES {','.join(values)}
            """
            self._execute(sql)

    def _save_terminals(self, icao_code: str, terminals: list[dict], now: str) -> None:
        """Save terminals."""
        if not terminals:
            return

        self._execute(f"DELETE FROM {self._table('terminals')} WHERE icao_code = '{icao_code}'")

        values = []
        for t in terminals:
            terminal_id = f"{icao_code}_{t.get('osmId', t.get('id', ''))}"
            geo = t.get("geo", {})
            pos = t.get("position", {})
            dims = t.get("dimensions", {})

            values.append(f"""(
                '{terminal_id}',
                '{icao_code}',
                {self._sql_str(t.get('name'))},
                {self._sql_str(t.get('type', 'terminal'))},
                {self._sql_str(t.get('operator'))},
                {self._sql_str(t.get('level'))},
                {dims.get('height') or 'NULL'},
                {geo.get('latitude', 0)},
                {geo.get('longitude', 0)},
                {pos.get('x', 0)},
                {pos.get('y', 0)},
                {pos.get('z', 0)},
                {dims.get('width') or 'NULL'},
                {dims.get('depth') or 'NULL'},
                {self._sql_str(json.dumps(t.get('polygon', [])))},
                {self._sql_str(json.dumps(t.get('geoPolygon', [])))},
                {t.get('color') or 'NULL'},
                {t.get('osmId') or 'NULL'},
                'OSM',
                TIMESTAMP'{now}',
                TIMESTAMP'{now}'
            )""")

        if values:
            sql = f"""
            INSERT INTO {self._table('terminals')} (
                terminal_id, icao_code, name, terminal_type, operator, level,
                height, center_lat, center_lon,
                position_x, position_y, position_z,
                width, depth, polygon_json, geo_polygon_json,
                color, osm_id, source, created_at, updated_at
            ) VALUES {','.join(values)}
            """
            self._execute(sql)

    def _save_runways(self, icao_code: str, runways: list[dict], now: str) -> None:
        """Save runways."""
        if not runways:
            return

        self._execute(f"DELETE FROM {self._table('runways')} WHERE icao_code = '{icao_code}'")

        values = []
        for r in runways:
            designator = r.get("designator", r.get("id", ""))
            runway_id = f"{icao_code}_{designator}"

            values.append(f"""(
                '{runway_id}',
                '{icao_code}',
                {self._sql_str(designator)},
                {self._sql_str(r.get('designatorLow'))},
                {self._sql_str(r.get('designatorHigh'))},
                {r.get('lengthFt') or 'NULL'},
                {r.get('widthFt') or 'NULL'},
                {self._sql_str(r.get('surface'))},
                {r.get('thresholdLowLat') or 'NULL'},
                {r.get('thresholdLowLon') or 'NULL'},
                {r.get('thresholdHighLat') or 'NULL'},
                {r.get('thresholdHighLon') or 'NULL'},
                {r.get('heading') or 'NULL'},
                {r.get('elevationFt') or 'NULL'},
                {r.get('ilsAvailable', False)},
                {self._sql_str(r.get('source', 'FAA'))},
                TIMESTAMP'{now}',
                TIMESTAMP'{now}'
            )""")

        if values:
            sql = f"""
            INSERT INTO {self._table('runways')} (
                runway_id, icao_code, designator, designator_low, designator_high,
                length_ft, width_ft, surface,
                threshold_low_lat, threshold_low_lon,
                threshold_high_lat, threshold_high_lon,
                heading, elevation_ft, ils_available, source,
                created_at, updated_at
            ) VALUES {','.join(values)}
            """
            self._execute(sql)

    def _save_taxiways(self, icao_code: str, taxiways: list[dict], now: str) -> None:
        """Save taxiways."""
        if not taxiways:
            return

        self._execute(f"DELETE FROM {self._table('taxiways')} WHERE icao_code = '{icao_code}'")

        values = []
        for t in taxiways:
            ref = t.get("id", t.get("ref", ""))
            taxiway_id = f"{icao_code}_{ref}"

            values.append(f"""(
                '{taxiway_id}',
                '{icao_code}',
                {self._sql_str(t.get('ref') or t.get('id'))},
                {self._sql_str(t.get('name'))},
                {t.get('width') or 'NULL'},
                {self._sql_str(t.get('surface'))},
                {self._sql_str(json.dumps(t.get('points', [])))},
                {self._sql_str(json.dumps(t.get('geoPoints', [])))},
                {t.get('color') or 'NULL'},
                {t.get('osmId') or 'NULL'},
                'OSM',
                TIMESTAMP'{now}',
                TIMESTAMP'{now}'
            )""")

        if values:
            sql = f"""
            INSERT INTO {self._table('taxiways')} (
                taxiway_id, icao_code, ref, name, width, surface,
                points_json, geo_points_json, color, osm_id, source,
                created_at, updated_at
            ) VALUES {','.join(values)}
            """
            self._execute(sql)

    def _save_aprons(self, icao_code: str, aprons: list[dict], now: str) -> None:
        """Save aprons."""
        if not aprons:
            return

        self._execute(f"DELETE FROM {self._table('aprons')} WHERE icao_code = '{icao_code}'")

        values = []
        for a in aprons:
            ref = a.get("id", a.get("ref", ""))
            apron_id = f"{icao_code}_{ref}"
            geo = a.get("geo", {})
            pos = a.get("position", {})
            dims = a.get("dimensions", {})

            values.append(f"""(
                '{apron_id}',
                '{icao_code}',
                {self._sql_str(a.get('ref') or a.get('id'))},
                {self._sql_str(a.get('name'))},
                {self._sql_str(a.get('surface'))},
                {geo.get('latitude', 0)},
                {geo.get('longitude', 0)},
                {pos.get('x', 0)},
                {pos.get('y', 0)},
                {pos.get('z', 0)},
                {dims.get('width') or 'NULL'},
                {dims.get('depth') or 'NULL'},
                {self._sql_str(json.dumps(a.get('polygon', [])))},
                {self._sql_str(json.dumps(a.get('geoPolygon', [])))},
                {a.get('color') or 'NULL'},
                {a.get('osmId') or 'NULL'},
                'OSM',
                TIMESTAMP'{now}',
                TIMESTAMP'{now}'
            )""")

        if values:
            sql = f"""
            INSERT INTO {self._table('aprons')} (
                apron_id, icao_code, ref, name, surface,
                center_lat, center_lon,
                position_x, position_y, position_z,
                width, depth, polygon_json, geo_polygon_json,
                color, osm_id, source, created_at, updated_at
            ) VALUES {','.join(values)}
            """
            self._execute(sql)

    def _save_buildings(self, icao_code: str, buildings: list[dict], now: str) -> None:
        """Save buildings."""
        if not buildings:
            return

        self._execute(f"DELETE FROM {self._table('buildings')} WHERE icao_code = '{icao_code}'")

        values = []
        for b in buildings:
            building_id = f"{icao_code}_{b.get('id', b.get('osmId', ''))}"
            geo = b.get("geo", {})
            pos = b.get("position", {})
            dims = b.get("dimensions", {})

            values.append(f"""(
                '{building_id}',
                '{icao_code}',
                {self._sql_str(b.get('name'))},
                {self._sql_str(b.get('type', 'building'))},
                {self._sql_str(b.get('operator'))},
                {dims.get('height') or 'NULL'},
                {geo.get('latitude', 0)},
                {geo.get('longitude', 0)},
                {pos.get('x', 0)},
                {pos.get('y', 0)},
                {pos.get('z', 0)},
                {dims.get('width') or 'NULL'},
                {dims.get('depth') or 'NULL'},
                {self._sql_str(json.dumps(b.get('polygon', [])))},
                {self._sql_str(json.dumps(b.get('geoPolygon', [])))},
                {b.get('color') or 'NULL'},
                {self._sql_str(b.get('ifcGuid'))},
                {b.get('osmId') or 'NULL'},
                {self._sql_str(b.get('source', 'OSM'))},
                TIMESTAMP'{now}',
                TIMESTAMP'{now}'
            )""")

        if values:
            sql = f"""
            INSERT INTO {self._table('buildings')} (
                building_id, icao_code, name, building_type, operator,
                height, center_lat, center_lon,
                position_x, position_y, position_z,
                width, depth, polygon_json, geo_polygon_json,
                color, ifc_guid, osm_id, source,
                created_at, updated_at
            ) VALUES {','.join(values)}
            """
            self._execute(sql)

    def _save_hangars(self, icao_code: str, hangars: list[dict], now: str) -> None:
        """Save hangars."""
        if not hangars:
            return

        self._execute(f"DELETE FROM {self._table('hangars')} WHERE icao_code = '{icao_code}'")

        values = []
        for h in hangars:
            hangar_id = f"{icao_code}_{h.get('id', h.get('osmId', ''))}"
            geo = h.get("geo", {})
            pos = h.get("position", {})
            dims = h.get("dimensions", {})

            values.append(f"""(
                '{hangar_id}',
                '{icao_code}',
                {self._sql_str(h.get('name'))},
                {self._sql_str(h.get('operator'))},
                {dims.get('height') or 'NULL'},
                {geo.get('latitude', 0)},
                {geo.get('longitude', 0)},
                {pos.get('x', 0)},
                {pos.get('y', 0)},
                {pos.get('z', 0)},
                {dims.get('width') or 'NULL'},
                {dims.get('depth') or 'NULL'},
                {self._sql_str(json.dumps(h.get('polygon', [])))},
                {self._sql_str(json.dumps(h.get('geoPolygon', [])))},
                {h.get('color') or 'NULL'},
                {h.get('osmId') or 'NULL'},
                'OSM',
                TIMESTAMP'{now}',
                TIMESTAMP'{now}'
            )""")

        if values:
            sql = f"""
            INSERT INTO {self._table('hangars')} (
                hangar_id, icao_code, name, operator,
                height, center_lat, center_lon,
                position_x, position_y, position_z,
                width, depth, polygon_json, geo_polygon_json,
                color, osm_id, source, created_at, updated_at
            ) VALUES {','.join(values)}
            """
            self._execute(sql)

    def _save_helipads(self, icao_code: str, helipads: list[dict], now: str) -> None:
        """Save helipads."""
        if not helipads:
            return

        self._execute(f"DELETE FROM {self._table('helipads')} WHERE icao_code = '{icao_code}'")

        values = []
        for h in helipads:
            ref = h.get("ref") or h.get("id", "")
            helipad_id = f"{icao_code}_{ref}"
            geo = h.get("geo", {})
            pos = h.get("position", {})

            values.append(f"""(
                '{helipad_id}',
                '{icao_code}',
                {self._sql_str(h.get('ref'))},
                {self._sql_str(h.get('name'))},
                {geo.get('latitude', 0)},
                {geo.get('longitude', 0)},
                {h.get('elevation') or 'NULL'},
                {pos.get('x', 0)},
                {pos.get('y', 0)},
                {pos.get('z', 0)},
                {h.get('osmId') or 'NULL'},
                'OSM',
                TIMESTAMP'{now}',
                TIMESTAMP'{now}'
            )""")

        if values:
            sql = f"""
            INSERT INTO {self._table('helipads')} (
                helipad_id, icao_code, ref, name,
                latitude, longitude, elevation,
                position_x, position_y, position_z,
                osm_id, source, created_at, updated_at
            ) VALUES {','.join(values)}
            """
            self._execute(sql)

    def _save_parking_positions(self, icao_code: str, positions: list[dict], now: str) -> None:
        """Save parking positions."""
        if not positions:
            return

        self._execute(f"DELETE FROM {self._table('parking_positions')} WHERE icao_code = '{icao_code}'")

        values = []
        for p in positions:
            ref = p.get("ref") or p.get("id", "")
            pp_id = f"{icao_code}_{ref}"
            geo = p.get("geo", {})
            pos = p.get("position", {})

            values.append(f"""(
                '{pp_id}',
                '{icao_code}',
                {self._sql_str(p.get('ref'))},
                {self._sql_str(p.get('name'))},
                {geo.get('latitude', 0)},
                {geo.get('longitude', 0)},
                {p.get('elevation') or 'NULL'},
                {pos.get('x', 0)},
                {pos.get('y', 0)},
                {pos.get('z', 0)},
                {p.get('osmId') or 'NULL'},
                'OSM',
                TIMESTAMP'{now}',
                TIMESTAMP'{now}'
            )""")

        if values:
            sql = f"""
            INSERT INTO {self._table('parking_positions')} (
                parking_position_id, icao_code, ref, name,
                latitude, longitude, elevation,
                position_x, position_y, position_z,
                osm_id, source, created_at, updated_at
            ) VALUES {','.join(values)}
            """
            self._execute(sql)

    def _save_osm_runways(self, icao_code: str, runways: list[dict], now: str) -> None:
        """Save OSM runways (polyline geometry)."""
        if not runways:
            return

        self._execute(f"DELETE FROM {self._table('osm_runways')} WHERE icao_code = '{icao_code}'")

        values = []
        for r in runways:
            ref = r.get("id", r.get("ref", ""))
            runway_id = f"{icao_code}_{ref}"

            values.append(f"""(
                '{runway_id}',
                '{icao_code}',
                {self._sql_str(r.get('ref') or r.get('id'))},
                {self._sql_str(r.get('name'))},
                {r.get('width') or 'NULL'},
                {self._sql_str(r.get('surface'))},
                {self._sql_str(json.dumps(r.get('points', [])))},
                {self._sql_str(json.dumps(r.get('geoPoints', [])))},
                {r.get('color') or 'NULL'},
                {r.get('osmId') or 'NULL'},
                'OSM',
                TIMESTAMP'{now}',
                TIMESTAMP'{now}'
            )""")

        if values:
            sql = f"""
            INSERT INTO {self._table('osm_runways')} (
                osm_runway_id, icao_code, ref, name, width, surface,
                points_json, geo_points_json, color, osm_id, source,
                created_at, updated_at
            ) VALUES {','.join(values)}
            """
            self._execute(sql)

    # =========================================================================
    # Load Operations
    # =========================================================================

    def load_airport_config(self, icao_code: str) -> Optional[dict[str, Any]]:
        """
        Load complete airport configuration from tables.

        Args:
            icao_code: ICAO airport code

        Returns:
            Configuration dictionary or None if not found
        """
        self._ensure_tables()

        # Load metadata
        meta_rows = self._execute(
            f"SELECT * FROM {self._table('airport_metadata')} WHERE icao_code = '{icao_code}'"
        )
        if not meta_rows:
            return None

        meta = meta_rows[0]

        # Load all related data
        gates = self._load_gates(icao_code)
        terminals = self._load_terminals(icao_code)
        runways = self._load_runways(icao_code)
        taxiways = self._load_taxiways(icao_code)
        aprons = self._load_aprons(icao_code)
        buildings = self._load_buildings(icao_code)
        hangars = self._load_hangars(icao_code)
        helipads = self._load_helipads(icao_code)
        parking_positions = self._load_parking_positions(icao_code)
        osm_runways = self._load_osm_runways(icao_code)

        return {
            "source": "LAKEHOUSE",
            "icaoCode": meta.get("icao_code"),
            "iataCode": meta.get("iata_code"),
            "airportName": meta.get("name"),
            "airportOperator": meta.get("operator"),
            "sources": meta.get("data_sources", []),
            "osmTimestamp": meta.get("osm_timestamp"),
            "gates": gates,
            "terminals": terminals,
            "runways": runways,
            "osmTaxiways": taxiways,
            "osmAprons": aprons,
            "buildings": buildings,
            "osmHangars": hangars,
            "osmHelipads": helipads,
            "osmParkingPositions": parking_positions,
            "osmRunways": osm_runways,
        }

    def _load_gates(self, icao_code: str) -> list[dict]:
        """Load gates for airport."""
        rows = self._execute(
            f"SELECT * FROM {self._table('gates')} WHERE icao_code = '{icao_code}'"
        )
        if not rows:
            return []

        return [
            {
                "id": r.get("ref"),
                "osmId": r.get("osm_id"),
                "ref": r.get("ref"),
                "name": r.get("name"),
                "terminal": r.get("terminal"),
                "level": r.get("level"),
                "operator": r.get("operator"),
                "elevation": r.get("elevation"),
                "position": {
                    "x": r.get("position_x", 0),
                    "y": r.get("position_y", 0),
                    "z": r.get("position_z", 0),
                },
                "geo": {
                    "latitude": r.get("latitude"),
                    "longitude": r.get("longitude"),
                },
            }
            for r in rows
        ]

    def _load_terminals(self, icao_code: str) -> list[dict]:
        """Load terminals for airport."""
        rows = self._execute(
            f"SELECT * FROM {self._table('terminals')} WHERE icao_code = '{icao_code}'"
        )
        if not rows:
            return []

        result = []
        for r in rows:
            terminal = {
                "id": r.get("terminal_id"),
                "osmId": r.get("osm_id"),
                "name": r.get("name"),
                "type": r.get("terminal_type"),
                "operator": r.get("operator"),
                "level": r.get("level"),
                "position": {
                    "x": r.get("position_x", 0),
                    "y": r.get("position_y", 0),
                    "z": r.get("position_z", 0),
                },
                "dimensions": {
                    "width": r.get("width"),
                    "height": r.get("height"),
                    "depth": r.get("depth"),
                },
                "polygon": json.loads(r.get("polygon_json") or "[]"),
                "geoPolygon": json.loads(r.get("geo_polygon_json") or "[]"),
                "geo": {
                    "latitude": r.get("center_lat"),
                    "longitude": r.get("center_lon"),
                },
            }
            color = r.get("color")
            if color is not None:
                terminal["color"] = int(color)
            result.append(terminal)
        return result

    def _load_runways(self, icao_code: str) -> list[dict]:
        """Load runways for airport."""
        rows = self._execute(
            f"SELECT * FROM {self._table('runways')} WHERE icao_code = '{icao_code}'"
        )
        if not rows:
            return []

        return [
            {
                "id": r.get("runway_id"),
                "designator": r.get("designator"),
                "designatorLow": r.get("designator_low"),
                "designatorHigh": r.get("designator_high"),
                "lengthFt": r.get("length_ft"),
                "widthFt": r.get("width_ft"),
                "surface": r.get("surface"),
                "thresholdLowLat": r.get("threshold_low_lat"),
                "thresholdLowLon": r.get("threshold_low_lon"),
                "thresholdHighLat": r.get("threshold_high_lat"),
                "thresholdHighLon": r.get("threshold_high_lon"),
                "heading": r.get("heading"),
                "elevationFt": r.get("elevation_ft"),
                "ilsAvailable": r.get("ils_available"),
                "source": r.get("source"),
            }
            for r in rows
        ]

    def _load_taxiways(self, icao_code: str) -> list[dict]:
        """Load taxiways for airport."""
        rows = self._execute(
            f"SELECT * FROM {self._table('taxiways')} WHERE icao_code = '{icao_code}'"
        )
        if not rows:
            return []

        result = []
        for r in rows:
            taxiway = {
                "id": r.get("ref") or r.get("taxiway_id"),
                "osmId": r.get("osm_id"),
                "ref": r.get("ref"),
                "name": r.get("name"),
                "width": r.get("width"),
                "surface": r.get("surface"),
                "points": json.loads(r.get("points_json") or "[]"),
                "geoPoints": json.loads(r.get("geo_points_json") or "[]"),
            }
            color = r.get("color")
            if color is not None:
                taxiway["color"] = int(color)
            result.append(taxiway)
        return result

    def _load_aprons(self, icao_code: str) -> list[dict]:
        """Load aprons for airport."""
        rows = self._execute(
            f"SELECT * FROM {self._table('aprons')} WHERE icao_code = '{icao_code}'"
        )
        if not rows:
            return []

        result = []
        for r in rows:
            apron = {
                "id": r.get("ref") or r.get("apron_id"),
                "osmId": r.get("osm_id"),
                "ref": r.get("ref"),
                "name": r.get("name"),
                "surface": r.get("surface"),
                "position": {
                    "x": r.get("position_x", 0),
                    "y": r.get("position_y", 0),
                    "z": r.get("position_z", 0),
                },
                "dimensions": {
                    "width": r.get("width"),
                    "depth": r.get("depth"),
                },
                "polygon": json.loads(r.get("polygon_json") or "[]"),
                "geoPolygon": json.loads(r.get("geo_polygon_json") or "[]"),
                "geo": {
                    "latitude": r.get("center_lat"),
                    "longitude": r.get("center_lon"),
                },
            }
            color = r.get("color")
            if color is not None:
                apron["color"] = int(color)
            result.append(apron)
        return result

    def _load_buildings(self, icao_code: str) -> list[dict]:
        """Load buildings for airport."""
        rows = self._execute(
            f"SELECT * FROM {self._table('buildings')} WHERE icao_code = '{icao_code}'"
        )
        if not rows:
            return []

        result = []
        for r in rows:
            building = {
                "id": r.get("building_id"),
                "osmId": r.get("osm_id"),
                "ifcGuid": r.get("ifc_guid"),
                "name": r.get("name"),
                "type": r.get("building_type"),
                "operator": r.get("operator"),
                "position": {
                    "x": r.get("position_x", 0),
                    "y": r.get("position_y", 0),
                    "z": r.get("position_z", 0),
                },
                "dimensions": {
                    "width": r.get("width"),
                    "height": r.get("height"),
                    "depth": r.get("depth"),
                },
                "polygon": json.loads(r.get("polygon_json") or "[]"),
                "geoPolygon": json.loads(r.get("geo_polygon_json") or "[]"),
                "geo": {
                    "latitude": r.get("center_lat"),
                    "longitude": r.get("center_lon"),
                },
                "source": r.get("source"),
            }
            color = r.get("color")
            if color is not None:
                building["color"] = int(color)
            result.append(building)
        return result

    def _load_hangars(self, icao_code: str) -> list[dict]:
        """Load hangars for airport."""
        rows = self._execute(
            f"SELECT * FROM {self._table('hangars')} WHERE icao_code = '{icao_code}'"
        )
        if not rows:
            return []

        result = []
        for r in rows:
            hangar = {
                "id": r.get("hangar_id"),
                "osmId": r.get("osm_id"),
                "name": r.get("name"),
                "type": "hangar",
                "operator": r.get("operator"),
                "position": {
                    "x": r.get("position_x", 0),
                    "y": r.get("position_y", 0),
                    "z": r.get("position_z", 0),
                },
                "dimensions": {
                    "width": r.get("width"),
                    "height": r.get("height"),
                    "depth": r.get("depth"),
                },
                "polygon": json.loads(r.get("polygon_json") or "[]"),
                "geoPolygon": json.loads(r.get("geo_polygon_json") or "[]"),
                "geo": {
                    "latitude": r.get("center_lat"),
                    "longitude": r.get("center_lon"),
                },
            }
            color = r.get("color")
            if color is not None:
                hangar["color"] = int(color)
            result.append(hangar)
        return result

    def _load_helipads(self, icao_code: str) -> list[dict]:
        """Load helipads for airport."""
        rows = self._execute(
            f"SELECT * FROM {self._table('helipads')} WHERE icao_code = '{icao_code}'"
        )
        if not rows:
            return []

        return [
            {
                "id": r.get("ref") or r.get("helipad_id"),
                "osmId": r.get("osm_id"),
                "ref": r.get("ref"),
                "name": r.get("name"),
                "position": {
                    "x": r.get("position_x", 0),
                    "y": r.get("position_y", 0),
                    "z": r.get("position_z", 0),
                },
                "geo": {
                    "latitude": r.get("latitude"),
                    "longitude": r.get("longitude"),
                },
            }
            for r in rows
        ]

    def _load_parking_positions(self, icao_code: str) -> list[dict]:
        """Load parking positions for airport."""
        rows = self._execute(
            f"SELECT * FROM {self._table('parking_positions')} WHERE icao_code = '{icao_code}'"
        )
        if not rows:
            return []

        return [
            {
                "id": r.get("ref") or r.get("parking_position_id"),
                "osmId": r.get("osm_id"),
                "ref": r.get("ref"),
                "name": r.get("name"),
                "position": {
                    "x": r.get("position_x", 0),
                    "y": r.get("position_y", 0),
                    "z": r.get("position_z", 0),
                },
                "geo": {
                    "latitude": r.get("latitude"),
                    "longitude": r.get("longitude"),
                },
            }
            for r in rows
        ]

    def _load_osm_runways(self, icao_code: str) -> list[dict]:
        """Load OSM runways (polyline geometry) for airport."""
        rows = self._execute(
            f"SELECT * FROM {self._table('osm_runways')} WHERE icao_code = '{icao_code}'"
        )
        if not rows:
            return []

        result = []
        for r in rows:
            runway = {
                "id": r.get("ref") or r.get("osm_runway_id"),
                "osmId": r.get("osm_id"),
                "ref": r.get("ref"),
                "name": r.get("name"),
                "width": r.get("width"),
                "surface": r.get("surface"),
                "points": json.loads(r.get("points_json") or "[]"),
                "geoPoints": json.loads(r.get("geo_points_json") or "[]"),
            }
            color = r.get("color")
            if color is not None:
                runway["color"] = int(color)
            result.append(runway)
        return result

    # =========================================================================
    # List and Delete Operations
    # =========================================================================

    def list_airports(self) -> list[dict]:
        """
        List all persisted airports.

        Returns:
            List of airport metadata dictionaries
        """
        self._ensure_tables()

        rows = self._execute(
            f"SELECT icao_code, iata_code, name, data_sources, osm_timestamp, updated_at "
            f"FROM {self._table('airport_metadata')} ORDER BY icao_code"
        )
        return rows or []

    def delete_airport(self, icao_code: str) -> bool:
        """
        Delete all data for an airport.

        Args:
            icao_code: ICAO airport code

        Returns:
            True if successful
        """
        self._ensure_tables()

        tables = [
            "gates", "terminals", "runways", "taxiways", "aprons", "buildings",
            "hangars", "helipads", "parking_positions", "osm_runways",
            "airport_metadata",
        ]

        for table in tables:
            self._execute(f"DELETE FROM {self._table(table)} WHERE icao_code = '{icao_code}'")

        logger.info(f"Deleted airport data for {icao_code}")
        return True

    def airport_exists(self, icao_code: str) -> bool:
        """Check if airport exists in lakehouse."""
        self._ensure_tables()

        rows = self._execute(
            f"SELECT 1 FROM {self._table('airport_metadata')} WHERE icao_code = '{icao_code}' LIMIT 1"
        )
        return bool(rows)

    # =========================================================================
    # Helpers
    # =========================================================================

    @staticmethod
    def _sql_str(value: Optional[str]) -> str:
        """Convert value to SQL string literal or NULL."""
        if value is None:
            return "NULL"
        # Escape single quotes
        escaped = str(value).replace("'", "''")
        return f"'{escaped}'"


# Singleton instance
_repository: Optional[AirportRepository] = None


def get_airport_repository() -> AirportRepository:
    """Get or create AirportRepository singleton.

    Auto-detects environment:
    - If DATABRICKS_USE_OAUTH=true and host/http_path set → SQL connector mode
      (works in Databricks Apps with ambient M2M OAuth)
    - Otherwise → WorkspaceClient mode (notebooks, local dev with PAT)
    """
    global _repository
    if _repository is None:
        host = os.getenv("DATABRICKS_HOST") or os.getenv("DATABRICKS_SERVER_HOSTNAME")
        http_path = os.getenv("DATABRICKS_HTTP_PATH") or os.getenv("DATABRICKS_WAREHOUSE_HTTP_PATH")
        use_oauth = os.getenv("DATABRICKS_USE_OAUTH", "false").lower() == "true"
        token = os.getenv("DATABRICKS_TOKEN") or os.getenv("DATABRICKS_ACCESS_TOKEN")
        catalog = os.getenv("DATABRICKS_CATALOG", DEFAULT_CATALOG)
        schema = os.getenv("DATABRICKS_SCHEMA", DEFAULT_SCHEMA)
        warehouse_id = os.getenv("DATABRICKS_WAREHOUSE_ID", "b868e84cedeb4262")

        # Prefer SQL connector when host/http_path are available
        can_use_connector = DATABRICKS_SQL_AVAILABLE and bool(host and http_path)

        if can_use_connector:
            logger.info(
                f"AirportRepository using databricks-sql-connector "
                f"(oauth={use_oauth}, host={host})"
            )
            _repository = AirportRepository(
                catalog=catalog,
                schema=schema,
                warehouse_id=warehouse_id,
                use_sql_connector=True,
                host=host,
                http_path=http_path,
                use_oauth=use_oauth,
                token=token,
            )
        else:
            logger.info("AirportRepository using WorkspaceClient statement execution")
            _repository = AirportRepository(
                catalog=catalog,
                schema=schema,
                warehouse_id=warehouse_id,
            )
    return _repository
