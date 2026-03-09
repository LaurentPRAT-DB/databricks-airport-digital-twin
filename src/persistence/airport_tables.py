"""Airport persistence table schemas.

Defines DDL for Unity Catalog tables storing airport configuration data.
"""

import logging
from typing import Optional

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState

logger = logging.getLogger(__name__)

# Default catalog and schema
DEFAULT_CATALOG = "serverless_stable_3n0ihb_catalog"
DEFAULT_SCHEMA = "airport_digital_twin"

# Table DDL statements
AIRPORT_METADATA_DDL = """
CREATE TABLE IF NOT EXISTS {catalog}.{schema}.airport_metadata (
  icao_code STRING NOT NULL COMMENT 'ICAO airport code (e.g., KSFO)',
  iata_code STRING COMMENT 'IATA airport code (e.g., SFO)',
  name STRING COMMENT 'Official airport name',
  city STRING,
  country STRING,
  timezone STRING,
  reference_lat DOUBLE COMMENT 'Center point latitude',
  reference_lon DOUBLE COMMENT 'Center point longitude',
  reference_alt DOUBLE COMMENT 'Elevation in meters',
  operator STRING COMMENT 'Airport operator',
  data_sources ARRAY<STRING> COMMENT 'Data sources used (OSM, FAA, AIXM)',
  osm_timestamp TIMESTAMP COMMENT 'Last OSM fetch time',
  faa_timestamp TIMESTAMP COMMENT 'Last FAA fetch time',
  created_at TIMESTAMP,
  updated_at TIMESTAMP,
  CONSTRAINT airport_metadata_pk PRIMARY KEY (icao_code)
) USING DELTA
TBLPROPERTIES (
  'delta.enableChangeDataFeed' = 'true',
  'delta.columnMapping.mode' = 'name'
)
COMMENT 'Airport metadata and configuration'
"""

GATES_DDL = """
CREATE TABLE IF NOT EXISTS {catalog}.{schema}.gates (
  gate_id STRING NOT NULL COMMENT 'Composite key: icao_code_ref',
  icao_code STRING NOT NULL COMMENT 'FK to airport_metadata',
  ref STRING NOT NULL COMMENT 'Gate reference (e.g., A1, G23)',
  name STRING COMMENT 'Full gate name',
  terminal STRING COMMENT 'Terminal assignment',
  level STRING COMMENT 'Floor level for multi-story terminals',
  operator STRING COMMENT 'Airline operator',
  latitude DOUBLE NOT NULL,
  longitude DOUBLE NOT NULL,
  elevation DOUBLE COMMENT 'Elevation in meters',
  position_x DOUBLE COMMENT 'Local 3D X coordinate',
  position_y DOUBLE COMMENT 'Local 3D Y coordinate',
  position_z DOUBLE COMMENT 'Local 3D Z coordinate',
  osm_id BIGINT COMMENT 'Original OSM node ID',
  source STRING,
  created_at TIMESTAMP,
  updated_at TIMESTAMP,
  CONSTRAINT gates_pk PRIMARY KEY (gate_id)
) USING DELTA
TBLPROPERTIES (
  'delta.enableChangeDataFeed' = 'true',
  'delta.columnMapping.mode' = 'name'
)
COMMENT 'Airport gates from OSM data'
"""

TERMINALS_DDL = """
CREATE TABLE IF NOT EXISTS {catalog}.{schema}.terminals (
  terminal_id STRING NOT NULL COMMENT 'Composite key: icao_code_osm_id',
  icao_code STRING NOT NULL,
  name STRING NOT NULL,
  terminal_type STRING,
  operator STRING COMMENT 'Airport authority or airline',
  level STRING COMMENT 'Number of floors',
  height DOUBLE COMMENT 'Building height in meters',
  center_lat DOUBLE,
  center_lon DOUBLE,
  position_x DOUBLE,
  position_y DOUBLE,
  position_z DOUBLE,
  width DOUBLE,
  depth DOUBLE,
  polygon_json STRING COMMENT 'JSON array of 3D points',
  geo_polygon_json STRING COMMENT 'JSON array of lat/lon points',
  color INT COMMENT 'Display color as hex integer',
  osm_id BIGINT,
  source STRING,
  created_at TIMESTAMP,
  updated_at TIMESTAMP,
  CONSTRAINT terminals_pk PRIMARY KEY (terminal_id)
) USING DELTA
TBLPROPERTIES (
  'delta.enableChangeDataFeed' = 'true',
  'delta.columnMapping.mode' = 'name'
)
COMMENT 'Terminal buildings from OSM data'
"""

RUNWAYS_DDL = """
CREATE TABLE IF NOT EXISTS {catalog}.{schema}.runways (
  runway_id STRING NOT NULL COMMENT 'Composite key: icao_code_designator',
  icao_code STRING NOT NULL,
  designator STRING NOT NULL COMMENT 'e.g., 28L/10R',
  designator_low STRING COMMENT 'e.g., 10R',
  designator_high STRING COMMENT 'e.g., 28L',
  length_ft DOUBLE,
  width_ft DOUBLE,
  surface STRING COMMENT 'Runway surface type',
  threshold_low_lat DOUBLE,
  threshold_low_lon DOUBLE,
  threshold_high_lat DOUBLE,
  threshold_high_lon DOUBLE,
  heading DOUBLE,
  elevation_ft DOUBLE,
  ils_available BOOLEAN,
  source STRING COMMENT 'FAA or AIXM',
  created_at TIMESTAMP,
  updated_at TIMESTAMP,
  CONSTRAINT runways_pk PRIMARY KEY (runway_id)
) USING DELTA
TBLPROPERTIES (
  'delta.enableChangeDataFeed' = 'true',
  'delta.columnMapping.mode' = 'name'
)
COMMENT 'Runway data from FAA/AIXM'
"""

TAXIWAYS_DDL = """
CREATE TABLE IF NOT EXISTS {catalog}.{schema}.taxiways (
  taxiway_id STRING NOT NULL COMMENT 'Composite key: icao_code_ref_or_osm_id',
  icao_code STRING NOT NULL,
  ref STRING COMMENT 'Taxiway name (e.g., A, B1)',
  name STRING,
  width DOUBLE,
  surface STRING COMMENT 'Pavement material',
  points_json STRING COMMENT 'JSON array of 3D waypoints',
  geo_points_json STRING COMMENT 'JSON array of lat/lon points',
  color INT COMMENT 'Display color as hex integer',
  osm_id BIGINT,
  source STRING,
  created_at TIMESTAMP,
  updated_at TIMESTAMP,
  CONSTRAINT taxiways_pk PRIMARY KEY (taxiway_id)
) USING DELTA
TBLPROPERTIES (
  'delta.enableChangeDataFeed' = 'true',
  'delta.columnMapping.mode' = 'name'
)
COMMENT 'Taxiway data from OSM'
"""

APRONS_DDL = """
CREATE TABLE IF NOT EXISTS {catalog}.{schema}.aprons (
  apron_id STRING NOT NULL,
  icao_code STRING NOT NULL,
  ref STRING,
  name STRING,
  surface STRING COMMENT 'Pavement material',
  center_lat DOUBLE,
  center_lon DOUBLE,
  position_x DOUBLE,
  position_y DOUBLE,
  position_z DOUBLE,
  width DOUBLE,
  depth DOUBLE,
  polygon_json STRING,
  geo_polygon_json STRING,
  color INT COMMENT 'Display color as hex integer',
  osm_id BIGINT,
  source STRING,
  created_at TIMESTAMP,
  updated_at TIMESTAMP,
  CONSTRAINT aprons_pk PRIMARY KEY (apron_id)
) USING DELTA
TBLPROPERTIES (
  'delta.enableChangeDataFeed' = 'true',
  'delta.columnMapping.mode' = 'name'
)
COMMENT 'Apron/ramp areas from OSM'
"""

BUILDINGS_DDL = """
CREATE TABLE IF NOT EXISTS {catalog}.{schema}.buildings (
  building_id STRING NOT NULL,
  icao_code STRING NOT NULL,
  name STRING,
  building_type STRING COMMENT 'terminal, hangar, control_tower, etc.',
  operator STRING,
  height DOUBLE,
  center_lat DOUBLE,
  center_lon DOUBLE,
  position_x DOUBLE,
  position_y DOUBLE,
  position_z DOUBLE,
  width DOUBLE,
  depth DOUBLE,
  polygon_json STRING,
  geo_polygon_json STRING,
  color INT COMMENT 'Display color as hex integer',
  ifc_guid STRING COMMENT 'IFC GlobalId if from IFC',
  osm_id BIGINT COMMENT 'OSM way ID if from OSM',
  source STRING,
  created_at TIMESTAMP,
  updated_at TIMESTAMP,
  CONSTRAINT buildings_pk PRIMARY KEY (building_id)
) USING DELTA
TBLPROPERTIES (
  'delta.enableChangeDataFeed' = 'true',
  'delta.columnMapping.mode' = 'name'
)
COMMENT 'Buildings from IFC and OSM'
"""

HANGARS_DDL = """
CREATE TABLE IF NOT EXISTS {catalog}.{schema}.hangars (
  hangar_id STRING NOT NULL,
  icao_code STRING NOT NULL,
  name STRING,
  operator STRING,
  height DOUBLE COMMENT 'Building height in meters',
  center_lat DOUBLE,
  center_lon DOUBLE,
  position_x DOUBLE,
  position_y DOUBLE,
  position_z DOUBLE,
  width DOUBLE,
  depth DOUBLE,
  polygon_json STRING COMMENT 'JSON array of 3D points',
  geo_polygon_json STRING COMMENT 'JSON array of lat/lon points',
  color INT COMMENT 'Display color as hex integer',
  osm_id BIGINT,
  source STRING,
  created_at TIMESTAMP,
  updated_at TIMESTAMP,
  CONSTRAINT hangars_pk PRIMARY KEY (hangar_id)
) USING DELTA
TBLPROPERTIES (
  'delta.enableChangeDataFeed' = 'true',
  'delta.columnMapping.mode' = 'name'
)
COMMENT 'Hangar buildings from OSM'
"""

HELIPADS_DDL = """
CREATE TABLE IF NOT EXISTS {catalog}.{schema}.helipads (
  helipad_id STRING NOT NULL,
  icao_code STRING NOT NULL,
  ref STRING COMMENT 'Helipad reference',
  name STRING,
  latitude DOUBLE NOT NULL,
  longitude DOUBLE NOT NULL,
  elevation DOUBLE,
  position_x DOUBLE,
  position_y DOUBLE,
  position_z DOUBLE,
  osm_id BIGINT,
  source STRING,
  created_at TIMESTAMP,
  updated_at TIMESTAMP,
  CONSTRAINT helipads_pk PRIMARY KEY (helipad_id)
) USING DELTA
TBLPROPERTIES (
  'delta.enableChangeDataFeed' = 'true',
  'delta.columnMapping.mode' = 'name'
)
COMMENT 'Helipads from OSM'
"""

PARKING_POSITIONS_DDL = """
CREATE TABLE IF NOT EXISTS {catalog}.{schema}.parking_positions (
  parking_position_id STRING NOT NULL,
  icao_code STRING NOT NULL,
  ref STRING COMMENT 'Parking position reference',
  name STRING,
  latitude DOUBLE NOT NULL,
  longitude DOUBLE NOT NULL,
  elevation DOUBLE,
  position_x DOUBLE,
  position_y DOUBLE,
  position_z DOUBLE,
  osm_id BIGINT,
  source STRING,
  created_at TIMESTAMP,
  updated_at TIMESTAMP,
  CONSTRAINT parking_positions_pk PRIMARY KEY (parking_position_id)
) USING DELTA
TBLPROPERTIES (
  'delta.enableChangeDataFeed' = 'true',
  'delta.columnMapping.mode' = 'name'
)
COMMENT 'Aircraft parking positions from OSM'
"""

OSM_RUNWAYS_DDL = """
CREATE TABLE IF NOT EXISTS {catalog}.{schema}.osm_runways (
  osm_runway_id STRING NOT NULL COMMENT 'Composite key: icao_code_ref_or_osm_id',
  icao_code STRING NOT NULL,
  ref STRING COMMENT 'Runway designator (e.g., 28L/10R)',
  name STRING,
  width DOUBLE,
  surface STRING COMMENT 'Pavement material',
  points_json STRING COMMENT 'JSON array of 3D waypoints',
  geo_points_json STRING COMMENT 'JSON array of lat/lon points',
  color INT COMMENT 'Display color as hex integer',
  osm_id BIGINT,
  source STRING,
  created_at TIMESTAMP,
  updated_at TIMESTAMP,
  CONSTRAINT osm_runways_pk PRIMARY KEY (osm_runway_id)
) USING DELTA
TBLPROPERTIES (
  'delta.enableChangeDataFeed' = 'true',
  'delta.columnMapping.mode' = 'name'
)
COMMENT 'Runway geometry from OSM (polylines)'
"""

ALL_TABLES = [
    ("airport_metadata", AIRPORT_METADATA_DDL),
    ("gates", GATES_DDL),
    ("terminals", TERMINALS_DDL),
    ("runways", RUNWAYS_DDL),
    ("taxiways", TAXIWAYS_DDL),
    ("aprons", APRONS_DDL),
    ("buildings", BUILDINGS_DDL),
    ("hangars", HANGARS_DDL),
    ("helipads", HELIPADS_DDL),
    ("parking_positions", PARKING_POSITIONS_DDL),
    ("osm_runways", OSM_RUNWAYS_DDL),
]


def create_tables(
    client: WorkspaceClient,
    warehouse_id: str,
    catalog: str = DEFAULT_CATALOG,
    schema: str = DEFAULT_SCHEMA,
) -> list[str]:
    """
    Create all airport persistence tables.

    Args:
        client: Databricks workspace client
        warehouse_id: SQL warehouse ID for execution
        catalog: Unity Catalog name
        schema: Schema name

    Returns:
        List of created table names
    """
    created = []

    # Create schema if not exists
    schema_sql = f"CREATE SCHEMA IF NOT EXISTS {catalog}.{schema}"
    _execute_sql(client, warehouse_id, schema_sql)
    logger.info(f"Ensured schema exists: {catalog}.{schema}")

    for table_name, ddl in ALL_TABLES:
        sql = ddl.format(catalog=catalog, schema=schema)
        try:
            _execute_sql(client, warehouse_id, sql)
            created.append(table_name)
            logger.info(f"Created/verified table: {catalog}.{schema}.{table_name}")
        except Exception as e:
            logger.error(f"Failed to create table {table_name}: {e}")
            raise

    return created


def _execute_sql(
    client: WorkspaceClient,
    warehouse_id: str,
    sql: str,
    timeout_seconds: int = 60,
) -> Optional[list[dict]]:
    """Execute SQL statement and return results."""
    response = client.statement_execution.execute_statement(
        warehouse_id=warehouse_id,
        statement=sql,
        wait_timeout="0s",  # Async execution
    )

    statement_id = response.statement_id

    # Poll for completion
    import time
    start = time.time()
    while time.time() - start < timeout_seconds:
        status = client.statement_execution.get_statement(statement_id)
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
            raise RuntimeError(f"SQL execution failed: {error}")

        time.sleep(0.5)

    raise TimeoutError(f"SQL execution timed out after {timeout_seconds}s")
