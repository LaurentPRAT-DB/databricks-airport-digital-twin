# Databricks notebook source
# MAGIC %md
# MAGIC # Unity Catalog Governance — Airport Digital Twin
# MAGIC
# MAGIC Enforces the governance layer that connects raw → governed → serving:
# MAGIC medallion catalog/schemas, access-control grants, Delta data-quality
# MAGIC constraints, multi-tenant row-level security, column masking, and a
# MAGIC lineage/audit review over Unity Catalog system tables.
# MAGIC
# MAGIC Logic lives in `src.governance.unity_catalog`; this notebook runs it.

# COMMAND ----------

from src.governance.unity_catalog import apply_governance, governance_report

# COMMAND ----------

# MAGIC %md ## Apply governance (idempotent)

# COMMAND ----------

result = apply_governance(spark)  # noqa: F821 - spark provided by Databricks
print(f"Applied {result['applied']}/{result['total']} governance statements")
for row in result["results"]:
    print(row["status"], "::", row["statement"])

# COMMAND ----------

# MAGIC %md ## Governance review: lineage, audit, effective grants

# COMMAND ----------

report = governance_report(spark)  # noqa: F821
for name, rows in report.items():
    count = len(rows) if isinstance(rows, list) else rows
    print(f"{name}: {count}")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Verifying enforcement
# MAGIC ```
# MAGIC base gold.flight_status_gold                          -> 5 rows
# MAGIC gold.flight_status_secured (tenant filter, non-tenant) -> 0 rows   [RLS ENFORCED]
# MAGIC SELECT icao24 ...                                      -> 'REDACTED' [MASK ENFORCED]
# MAGIC ```
# MAGIC Full captured output in `docs/EXECUTION_EVIDENCE.md` (Artifact 6).
