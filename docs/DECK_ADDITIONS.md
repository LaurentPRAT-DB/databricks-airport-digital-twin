# Deck additions — paste-ready slides for the SITA pitch

Two new slides to add to the deck plus two small metric corrections. These close the reviewer's
two explicit gaps: (1) concrete execution evidence that the build runs, and (2) an account of how
AI tools built it and the trade-offs made. All numbers are pulled live from the workspace — see
`docs/EXECUTION_EVIDENCE.md`.

---

## NEW SLIDE — insert after the KPI/Predictions demo slide

**Title:** The build actually runs — execution evidence

**Four stat cards (mirror the deck's 4-card layout):**

| 01 · INGESTION | 02 · GOVERNED GOLD | 03 · GENIE AGENT | 04 · DEPLOYED |
|---|---|---|---|
| **97,061** | **59,767** | **NL → SQL → rows** | **HTTP 200** |
| raw ADS-B rows in `opensky_states_raw` (real OpenSky: live Lufthansa over Frankfurt) | rows in `baggage_status_gold`, DLT bronze→silver→gold | Genie space answers a plain-English question, emits governed SQL, returns a result (`SUCCEEDED`) | health endpoint live; E2E smoke job `SUCCESS`; app gated by workspace OAuth |

**Footer line:** `serverless_stable_3n0ihb_catalog.airport_digital_twin` — 33 governed UC tables ·
Lakeflow DLT pipeline (`dev` + `prod`) · Genie space `01f1…3a00` · reproducible via Databricks CLI
(see `docs/EXECUTION_EVIDENCE.md`).

**Speaker note:** "This isn't a mockup. 97k real ADS-B rows land in a governed table, a DLT
pipeline carries baggage through to a 59k-row gold layer, and the Genie Agent answers natural
language over that governed data with SQL it generates itself. The app is deployed and serving."

---

## NEW SLIDE — insert near the end, before the closing SITA quote

**Title:** How I built this with AI — and the trade-offs

**Left column — Built with AI:**
- Claude Code (Opus) driving Databricks CLI, DABs, Genie & pipeline APIs through Databricks skills
- Plan-first workflow: every non-trivial change written to `.planning/` before code (52 backlog items)
- Parallel subagents for codebase audits and fan-out search
- 1,308 commits over ~4 months; fix-heavy (658) = tight iterate-and-verify loop
- Verified with real runs: ~3,000 tests, deployed app, live Genie queries, governed-table counts

**Right column — Trade-offs made:**
- **Synthetic demo mode + live OpenSky** — reproducible demos *and* real ADS-B; cost = two paths, `data_source` tag
- **Lakebase cache vs Lakehouse-first** — <10 ms serving via Postgres, analytics/ML on Delta; cost = a sync job
- **OSM-derived geometry, never hardcoded** — any airport worldwide; cost = honest OSM gaps (KORD deselected)
- **Genie (history) + MCP (real-time) routing** — grounded SQL *and* live data; cost = routing logic
- **Shipped with documented known gaps** — 3 approach-quality tests tracked, not silenced

**Footer:** Full account in `docs/AI_USAGE.md`.

---

## Metric corrections (accuracy — repo backs the higher numbers)

On **"The Databricks Airport Digital Twin"** slide (the four-quadrant infographic):
- "12+ pre-loaded global hubs" → **29 preset airports** (any ICAO worldwide)
- "43 real-world calibration profiles" → **1,183 calibration profiles (43 hand-researched known-stats)**

These are conservative today; the repo backs the larger figures (README "At a Glance").

---

## Optional — repo reference

Add a small footer or backup slide noting the build's repo, so code and deck are explicitly the
same system: **`github.com/LaurentPRAT-DB/databricks-airport-digital-twin`** (the aviation build —
not the industrial-twin sibling).
