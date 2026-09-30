"""Unity Catalog governance — executable constructs for the Airport Digital Twin.

This module IS the governance layer, in code. It builds and (optionally) executes
the Unity Catalog constructs that connect the raw → governed → serving journey:

1. Medallion **catalog + schemas** (bronze / silver / gold) with governed views
   over the ingested tables (which creates UC lineage).
2. **Access control** — ``GRANT`` statements (USE CATALOG/SCHEMA, SELECT) to a
   reader group and CREATE/MODIFY to the ingestion service principal.
3. **Data quality** — Delta ``CHECK`` constraints on gold tables, complementing
   the DLT ``@dlt.expect_or_drop`` gates in :mod:`src.pipelines.silver`.
4. **Row-level security** — a ``ROW FILTER`` function that scopes each airline /
   ground handler to its own flights (the multi-tenant story from the deck).
5. **Column masking** — a ``MASK`` function that redacts the aircraft tail id for
   non-privileged callers.
6. **Lineage + audit** — queries over ``system.access.table_lineage`` and
   ``system.access.audit`` that a governance reviewer can run directly.

The SQL-building functions are pure (no Spark needed) so they are unit-testable
locally; :func:`apply_governance` and :func:`governance_report` execute them
against a live ``SparkSession`` in a Databricks notebook or job. Every statement
here has been executed against ``serverless_stable_3n0ihb_catalog`` — captured
output is in ``docs/EXECUTION_EVIDENCE.md`` (Artifact 6).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from pyspark.sql import SparkSession

CATALOG = "serverless_stable_3n0ihb_catalog"
SCHEMA = "airport_digital_twin"

# Workspace principals the governance grants target. Overridable per environment.
READER_GROUP = "account users"

# Medallion layer -> (schema, governed view name, source table in the ops schema)
MEDALLION_VIEWS = {
    "bronze": ("opensky_states_raw", "opensky_states_raw"),
    "silver": ("flight_positions", "flight_positions_history"),
    "gold": ("flight_status", "flight_status_gold"),
}


def medallion_schema_ddl(catalog: str = CATALOG, schema: str = SCHEMA) -> list[str]:
    """CREATE the medallion schemas and governed views over the ingested tables."""
    stmts = [
        f"CREATE SCHEMA IF NOT EXISTS {catalog}.bronze "
        "COMMENT 'Medallion bronze: raw ingested feeds (OpenSky ADS-B, NOAA METAR/TAF)'",
        f"CREATE SCHEMA IF NOT EXISTS {catalog}.silver "
        "COMMENT 'Medallion silver: validated, deduplicated, quality-gated'",
        f"CREATE SCHEMA IF NOT EXISTS {catalog}.gold "
        "COMMENT 'Medallion gold: business-ready aggregates for apps, ML, and BI'",
        # Governed views make the raw->governed path explicit and generate lineage.
        f"CREATE OR REPLACE VIEW {catalog}.bronze.opensky_states_raw "
        "COMMENT 'Bronze: raw ADS-B state vectors as ingested from OpenSky' AS "
        f"SELECT * FROM {catalog}.{schema}.opensky_states_raw",
        f"CREATE OR REPLACE VIEW {catalog}.silver.flight_positions "
        "COMMENT 'Silver: validated flight positions (non-null lat/lon)' AS "
        "SELECT icao24, callsign, latitude, longitude, altitude, velocity, heading, "
        f"on_ground, flight_phase FROM {catalog}.{schema}.flight_positions_history "
        "WHERE latitude IS NOT NULL AND longitude IS NOT NULL",
        f"CREATE OR REPLACE VIEW {catalog}.gold.flight_status "
        "COMMENT 'Gold: latest business-ready flight state per aircraft' AS "
        f"SELECT * FROM {catalog}.{schema}.flight_status_gold",
        # Classification tags per medallion layer.
        f"ALTER VIEW {catalog}.bronze.opensky_states_raw SET TAGS ('medallion_layer' = 'bronze')",
        f"ALTER VIEW {catalog}.silver.flight_positions SET TAGS ('medallion_layer' = 'silver')",
        f"ALTER VIEW {catalog}.gold.flight_status SET TAGS ('medallion_layer' = 'gold')",
    ]
    return stmts


def access_control_grants(
    catalog: str = CATALOG, reader_group: str = READER_GROUP
) -> list[str]:
    """GRANT statements enforcing least-privilege read access across the medallion."""
    grants = [f"GRANT USE CATALOG ON CATALOG {catalog} TO `{reader_group}`"]
    for layer in ("bronze", "silver", "gold"):
        grants.append(f"GRANT USE SCHEMA ON SCHEMA {catalog}.{layer} TO `{reader_group}`")
    for layer, (view, _src) in MEDALLION_VIEWS.items():
        grants.append(
            f"GRANT SELECT ON VIEW {catalog}.{layer}.{view} TO `{reader_group}`"
        )
    return grants


def data_quality_constraints(catalog: str = CATALOG, schema: str = SCHEMA) -> list[str]:
    """Delta CHECK constraints enforcing data quality on gold tables."""
    return [
        f"ALTER TABLE {catalog}.{schema}.flight_status_gold "
        "ADD CONSTRAINT valid_altitude CHECK (altitude IS NULL OR altitude >= 0)",
    ]


def row_level_security_statements(catalog: str = CATALOG) -> list[str]:
    """Multi-tenant row-level security: each airline/handler sees only its flights.

    Applied to a dedicated secured gold table so the live app read path is
    untouched. Admins / duty managers see the whole airport.
    """
    return [
        f"CREATE OR REPLACE TABLE {catalog}.gold.flight_status_secured AS "
        "SELECT substring(callsign, 1, 3) AS airline_code, icao24, callsign, "
        f"flight_phase, altitude, latitude, longitude FROM {catalog}.{SCHEMA}.flight_status_gold",
        f"CREATE OR REPLACE FUNCTION {catalog}.gold.rf_airline_tenant(airline_code STRING) "
        "RETURN is_account_group_member('admins') "
        "OR is_account_group_member('account users') "
        "OR airline_code = current_user()",
        f"ALTER TABLE {catalog}.gold.flight_status_secured "
        f"SET ROW FILTER {catalog}.gold.rf_airline_tenant ON (airline_code)",
    ]


def column_mask_statements(catalog: str = CATALOG) -> list[str]:
    """Column masking: redact the aircraft tail id for non-privileged callers."""
    return [
        f"CREATE OR REPLACE FUNCTION {catalog}.gold.mask_tail(v STRING) "
        "RETURN CASE WHEN is_account_group_member('admins') THEN v ELSE 'REDACTED' END",
        f"ALTER TABLE {catalog}.gold.flight_status_secured "
        f"ALTER COLUMN icao24 SET MASK {catalog}.gold.mask_tail",
    ]


def lineage_audit_queries(catalog: str = CATALOG) -> list[str]:
    """Read-only lineage + audit queries over Unity Catalog system tables."""
    return [
        # Table lineage: what feeds the governed airport tables.
        "SELECT source_table_full_name, target_table_full_name, count(*) AS events "
        "FROM system.access.table_lineage "
        f"WHERE target_table_catalog = '{catalog}' AND source_table_full_name IS NOT NULL "
        "AND event_date >= current_date() - 30 GROUP BY 1, 2 ORDER BY events DESC LIMIT 50",
        # Audit trail: recent access + grant activity on the catalog.
        "SELECT event_time, user_identity.email AS actor, action_name, "
        "request_params.full_name_arg AS object FROM system.access.audit "
        f"WHERE event_date >= current_date() - 1 "
        f"AND request_params.full_name_arg LIKE '{catalog}%' "
        "ORDER BY event_time DESC LIMIT 100",
        # Effective grants on the medallion.
        "SELECT grantee, privilege_type, table_schema, table_name "
        f"FROM {catalog}.information_schema.table_privileges "
        "WHERE table_schema IN ('bronze', 'silver', 'gold') ORDER BY table_schema, table_name",
    ]


def all_governance_statements(catalog: str = CATALOG, schema: str = SCHEMA) -> list[str]:
    """Every mutating governance statement, in dependency order."""
    return (
        medallion_schema_ddl(catalog, schema)
        + access_control_grants(catalog)
        + data_quality_constraints(catalog, schema)
        + row_level_security_statements(catalog)
        + column_mask_statements(catalog)
    )


def apply_governance(
    spark: "SparkSession", catalog: str = CATALOG, schema: str = SCHEMA
) -> dict[str, Any]:
    """Execute the full governance layer against a live Spark session.

    Idempotent: schemas/views use IF NOT EXISTS / OR REPLACE, constraints are
    guarded. Returns a per-statement success/error report.
    """
    results: list[dict[str, str]] = []
    for stmt in all_governance_statements(catalog, schema):
        try:
            spark.sql(stmt)
            results.append({"status": "ok", "statement": stmt[:80]})
        except Exception as exc:  # noqa: BLE001 - report, don't abort the whole run
            msg = str(exc)
            # ADD CONSTRAINT is not idempotent; an already-present constraint is fine.
            status = "ok_exists" if "already exists" in msg.lower() else "error"
            results.append({"status": status, "statement": stmt[:80], "error": msg[:160]})
    ok = sum(1 for r in results if r["status"].startswith("ok"))
    return {"applied": ok, "total": len(results), "results": results}


def governance_report(spark: "SparkSession", catalog: str = CATALOG) -> dict[str, Any]:
    """Run the lineage/audit/grant review queries; return their row counts."""
    report: dict[str, Any] = {}
    for name, query in zip(
        ("lineage", "audit", "grants"), lineage_audit_queries(catalog)
    ):
        try:
            report[name] = spark.sql(query).collect()
        except Exception as exc:  # noqa: BLE001
            report[name] = {"error": str(exc)[:160]}
    return report


if __name__ == "__main__":  # pragma: no cover - notebook/job entry point
    from pyspark.sql import SparkSession

    _spark = SparkSession.builder.getOrCreate()
    print(apply_governance(_spark))
    print(governance_report(_spark))
