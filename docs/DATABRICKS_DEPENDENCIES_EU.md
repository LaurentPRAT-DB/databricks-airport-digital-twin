# Airport Digital Twin — Databricks Dependencies & EU Region Availability

## Summary

All core Databricks services are available in EU regions. The project's `free` target already runs in eu-west-1 with Lakebase, Apps, and Unity Catalog confirmed working. Two optional features (Foundation Model LLM endpoints and Genie Space) may have limited availability depending on the specific EU region.

---

## Dependencies Matrix

### Databricks Platform Services

| Dependency | Service Type | Current Region | EU Available? | Notes |
|---|---|---|---|---|
| Databricks Workspace | Apps, UC, Jobs, Pipelines | us-east-1 (dev/prod), eu-west-1 (free) | ✅ Yes | All standard workspace features |
| SQL Warehouse | Serverless SQL | Same as workspace | ✅ Yes | Serverless SQL GA in all regions |
| Lakebase (Autoscale PostgreSQL) | Managed Postgres | us-east-1 (dev/prod), eu-west-1 (free) | ✅ Yes (GA) | Already running in eu-west-1 on free target |
| Unity Catalog | Delta tables, Volumes, ML models | Workspace region | ✅ Yes | Tables, Volumes, model registry |
| DLT Pipelines | Serverless pipelines | Workspace region | ✅ Yes | Bronze/Silver/Gold flight + baggage |
| Databricks Apps | App hosting (FastAPI) | Workspace region | ✅ Yes | Confirmed working in eu-west-1 |
| Secret Scope | Credentials store | Workspace region | ✅ Yes | Used for OpenSky API credentials |

### AI/ML Services

| Dependency | Service Type | Current Region | EU Available? | Notes |
|---|---|---|---|---|
| Model Serving — Foundation Models | `databricks-claude-sonnet-4-5` (primary), `databricks-meta-llama-3-3-70b-instruct` (fallback) | Workspace region | ⚠️ Region-dependent | Claude availability varies by EU region; Llama also varies |
| Model Serving — Custom Endpoint | `airport-dt-aircraft-inpainting-dev/prod` | Workspace region | ✅ Yes | Custom model serving endpoints work in all regions |
| Genie Space (AI/BI) | Natural language to SQL | Workspace region | ⚠️ Check availability | May still be preview/limited in some EU regions |
| Vector Search | (not currently used) | — | ✅ Yes | Not a blocker — reserved for future use |

### External APIs (Non-Databricks)

| Dependency | Service | Region | EU Available? | Notes |
|---|---|---|---|---|
| OpenSky Network API | Real-time flight tracking | Global (opensky-network.org) | ✅ Yes | EU-based organization (Switzerland) |
| Overpass API (OSM) | Airport geometry data | Global (overpass-api.de) | ✅ Yes | Germany-based, serves worldwide |

---

## Current Target Configuration

| Target | Workspace Region | Lakebase Host | Warehouse ID | Catalog |
|---|---|---|---|---|
| dev | us-east-1 | ep-polished-forest-d2hjnab6.database.us-east-1.cloud.databricks.com | b868e84cedeb4262 | serverless_stable_3n0ihb_catalog |
| prod | us-east-1 | ep-summer-scene-d2ew95fl.database.us-east-1.cloud.databricks.com | b868e84cedeb4262 | serverless_stable_3n0ihb_catalog |
| free | eu-west-1 | ep-patient-fire-d38b447d.database.eu-west-1.cloud.databricks.com | 58d41113cb262dce | main |

---

## Potential EU Blockers

1. **Foundation Model Endpoints** — The LLM assistant uses `databricks-claude-sonnet-4-5` for function-calling routing and report generation. If not available in the target EU region, configure `ASSISTANT_MODEL_ENDPOINT` env var to an available model. The app gracefully degrades without LLM (assistant tab disabled, reports use template-only mode).

2. **Genie Space** — Used for natural language flight queries. If not available in EU region, the Genie tab in the unified assistant won't function. The rest of the app is unaffected.

---

## Recommendation

For a full EU deployment:
- Use an EU workspace (eu-west-1 or eu-central-1)
- Lakebase, Apps, UC, DLT, SQL Warehouse — all confirmed working
- Verify foundation model availability in your specific EU region via Workspace → Serving → Foundation Models
- If Genie is unavailable, disable the Genie routing in the assistant config
