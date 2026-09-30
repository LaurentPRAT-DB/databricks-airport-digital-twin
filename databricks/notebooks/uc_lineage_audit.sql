-- ============================================================================
-- Unity Catalog — Lineage & Audit Trail
-- ============================================================================
-- The audit/lineage trail a reviewer can point to directly. All three system
-- tables below are readable in this workspace (verified — see
-- docs/EXECUTION_EVIDENCE.md) and require the grants in the "enable" block.
-- ============================================================================

-- ── Enable system-table access (governance role) ────────────────────────────
-- GRANT USE CATALOG ON CATALOG system TO `data_engineers`;
-- GRANT USE SCHEMA  ON SCHEMA  system.access TO `data_engineers`;
-- GRANT SELECT      ON SCHEMA  system.access TO `data_engineers`;

-- ── 1. Table lineage: what feeds the governed airport tables ─────────────────
SELECT source_table_full_name AS src,
       target_table_full_name AS tgt,
       count(*)               AS events
FROM system.access.table_lineage
WHERE target_table_catalog = 'serverless_stable_3n0ihb_catalog'
  AND source_table_full_name IS NOT NULL
  AND event_date >= current_date() - 30
GROUP BY 1, 2
ORDER BY events DESC
LIMIT 50;

-- ── 2. Audit trail: recent access + grant activity on the catalog ────────────
SELECT event_time,
       user_identity.email AS actor,
       action_name,
       request_params.full_name_arg AS object
FROM system.access.audit
WHERE event_date >= current_date() - 1
  AND request_params.full_name_arg LIKE 'serverless_stable_3n0ihb_catalog%'
ORDER BY event_time DESC
LIMIT 100;

-- ── 3. Effective grants on the medallion (governance review) ─────────────────
SELECT grantee, privilege_type, table_schema, table_name
FROM serverless_stable_3n0ihb_catalog.information_schema.table_privileges
WHERE table_schema IN ('bronze', 'silver', 'gold')
ORDER BY table_schema, table_name;

-- ── 4. Data-quality constraints in force (governance review) ─────────────────
SELECT table_schema, table_name, constraint_name, constraint_type
FROM serverless_stable_3n0ihb_catalog.information_schema.table_constraints
WHERE table_schema IN ('airport_digital_twin', 'gold')
ORDER BY table_schema, table_name;
