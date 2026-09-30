---
title: Certification resubmission — aviation path
area: certification
status: active
created: 2026-09-30
---

# Cert Resubmission — Aviation Path

## Context

A Databricks skill-certification submission (airport digital twin, SITA aviation deck) did **not pass**. Reviewer feedback: repo was "a generic industrial factory simulator," had "no Lakeflow ingestion pipeline and no Genie Agent," showed no execution evidence, and did not match the aviation deck.

**Root cause (proven): the grader graded the WRONG repo.** The submission resolved to the sibling `databricks_industrial_digital_twin` (README: "configurable state-machine simulation engine that models any industrial plant") — not `databricks-airport-digital-twin`. Repo names differ only by `_industrial_` vs `-airport-`. Proof: the industrial repo contains `cycle_time`/`rework`/`quality_defect`/`failure_duration`/`assembly` (the exact terms the reviewer praised); the airport repo has **zero** of them.

The airport repo **already satisfies all three "missing" layers**:
- **Lakeflow/DLT:** `resources/pipeline.yml` + `src/pipelines/{bronze,silver,gold}.py` (+ baggage), real OpenSky ADS-B / METAR / BTS → governed UC tables in `serverless_stable_3n0ihb_catalog.airport_digital_twin`.
- **Genie space:** `01f12612fa6314ae943d0526f5ae3a00`, proxy `app/backend/api/genie.py`, unified assistant router `app/backend/api/assistant.py`.
- **Deployed app (live):** `https://airport-digital-twin-dev-7474645572615955.aws.databricksapps.com` → HTTP 302 OAuth (serving).

Confirmed path: **aviation** (airport repo + existing SITA deck).

## Genuine remaining gaps

1. Submission points at wrong repo → resubmit with `github.com/LaurentPRAT-DB/databricks-airport-digital-twin`.
2. Concrete execution evidence (run log / query result / endpoint response).
3. AI-tools usage + trade-offs writeup — absent.
4. Deck — confirm aviation, fix repo link, add evidence + AI-usage slides.

## Steps

### 1. Execution evidence (profile `FEVM_SERVERLESS_STABLE`) → `docs/EXECUTION_EVIDENCE.md`
- `databricks bundle run e2e_smoke_test --target dev` — 11 live endpoints. verify: SUCCESS, ≥11 × 200.
- SQL count + schema + 5-row sample from `…airport_digital_twin.flight_status_gold` + `flight_positions_history`. verify: non-zero rows.
- Lakeflow pipeline update status/events (or `baggage_pipeline_integration_test`) with bronze→silver→gold counts. verify: COMPLETED.
- Genie space `01f1…3a00` — one NL question via Conversation API, capture SQL + rows. verify: grounded result.

### 2. AI usage → `docs/AI_USAGE.md`
How AI tools built it (Claude Code, Databricks skills, subagents), grounded in `git log` / `.planning/` / CLAUDE.md, + 4–6 real trade-offs (synthetic demo vs live OpenSky; Lakebase cache vs Lakehouse-first; OSM geometry vs hardcode; DLT baggage vs flight gold; Genie+MCP routing). No invented metrics.

### 3. Deck (gated on google-mcp auth)
Fix repo link (hyphens), confirm claims map to airport reality (`src/ml/{delay,gate,congestion}_model.py`, Genie, DLT), add Execution Evidence + AI/Trade-offs slides, keep SITA framing.

### 4. Resubmit
Airport repo public + `main` current; deliver correct repo URL + updated deck + 3-line rebuttal ("previous grade evaluated the wrong repo").

## Verification
- `docs/EXECUTION_EVIDENCE.md`: ≥4 real artifacts with URLs + timestamps.
- `docs/AI_USAGE.md`: concrete first-person account + real trade-offs.
- Deck: aviation intact, link fixed, 2 new slides.
- Correct public repo URL + deck delivered.
