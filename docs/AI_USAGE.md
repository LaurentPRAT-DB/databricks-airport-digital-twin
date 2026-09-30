# How I Used AI Tools to Build This — and the Trade-offs

This build was developed with **Claude Code** (Anthropic Opus) driving the Databricks CLI,
DABs, and workspace APIs through a set of **Databricks skills**, with **subagents** for parallel
exploration and a **file-based memory** for cross-session continuity. This document is an honest
account of how that worked and the engineering trade-offs I made.

## The workflow, in numbers

- **1,308 commits** over ~4 months (2026-03-05 → 2026-07-02), Conventional Commits throughout.
- Commit-type histogram: `fix` 658, `feat` 315, `docs` 159, `chore` 67, `refactor` 29, `test` 28,
  `perf` 19. The fix-heavy shape is the signature of a tight **iterate-and-verify loop** — features
  landed, then were hardened against real data and real deploys rather than assumed correct.
- **258 planning docs** (`.planning/`), **52 backlog items** — every non-trivial change started as
  a written plan before code, which kept scope explicit and reviewable.
- **~305 source files** (169 Python + 136 TS/TSX), **~173 test files** (123 Python + 50 frontend),
  ~3,000 Python tests at ~69% coverage.

## How AI tools were actually used

1. **Plan-first, then execute.** For any multi-step change I had Claude enter a planning phase,
   explore the codebase read-only, and write a concrete plan to `.planning/` before touching code.
   Plans captured verification steps, not just build steps.
2. **Subagents for fan-out.** Codebase audits, cross-file searches, and "does X already exist"
   questions were delegated to parallel read-only subagents so the main thread stayed focused. (The
   certification-readiness audit behind `docs/EXECUTION_EVIDENCE.md` was itself run this way.)
3. **Databricks skills for the platform surface.** CLI auth/profile selection, DABs deploy, Lakeflow
   pipelines, Genie Conversation API, and UC queries were all driven through skills that encode the
   correct command syntax — which avoided a large class of "wrong flag / wrong endpoint" errors.
4. **Memory across sessions.** A file-based memory index tracked non-obvious project state (deployed
   app URL, known test gaps, architecture decisions) so context survived between sessions instead of
   being re-derived each time.
5. **Verification before "done."** Changes were proven with real runs — pytest suites, a deployed
   app, live Genie queries, and governed-table row counts — not declared complete on inspection.

## Trade-offs I made

**1. Synthetic demo mode vs. live OpenSky ingestion.**
The app defaults to `DEMO_MODE=true` with deterministic synthetic flights, *and* ingests real
OpenSky ADS-B into `opensky_states_raw` (97k rows). I kept both: demos need to be reproducible and
network-independent, but the certification story needs real external data. Cost: two code paths and
a `data_source` tag on gold rows to keep them distinguishable.

**2. Lakebase (Postgres) cache vs. Lakehouse-first analytics.**
Live flight status serves from Lakebase for <10 ms reads; all analytics, ML, and history live in
Delta/Unity Catalog. The write path forks (sync job Delta→Lakebase). Trade-off: added a sync job and
a consistency window in exchange for low-latency serving without hammering the Lakehouse.

**3. OSM-derived geometry vs. hardcoded per-airport data.**
All runways/gates/taxiways come from OpenStreetMap via Overpass, computed per airport — no per-ICAO
dictionaries. This generalizes to any airport worldwide, but exposes OSM data gaps: O'Hare (KORD)
geometry is incomplete, so its tests are deselected and documented rather than faked. I chose
generality plus honest gaps over a hardcoded lookup that would demo well and scale to nothing.

**4. Depth on baggage DLT vs. breadth elsewhere.**
The baggage pipeline got a full bronze→silver→gold treatment (`baggage_status_gold`, 59k rows)
because it best showcases governed streaming state; the flight gold table is thinner. Deliberate:
one deep, verifiable pipeline beats many shallow ones for a certification.

**5. Genie (historical SQL) + MCP tools (real-time) routing vs. one model.**
The assistant routes trend/history questions to the Genie space and current-state questions to
real-time MCP tools (`app/backend/api/assistant.py`). This gives grounded SQL *and* live data, at
the cost of routing logic and a system prompt that has to teach the split.

**6. Ship with documented known gaps vs. block on 100% green.**
Three approach-quality tests (altitude/velocity smoothing) are left failing *and tracked in the
plan*, rather than silenced or allowed to block the build. I favored transparent, tracked debt over
either hidden skips or indefinite delay.

## What I'd do next (informed by this build)

- Feed the deviation/failure signals into a **registered MLflow model** that predicts delay or
  time-to-gate, rather than only driving the simulation.
- Widen the Genie Agent's curated schema to include the gold flight and prediction tables so an
  operator can ask what-if questions grounded entirely in governed data.
- Bring a real sample of **BTS delay** and **METAR** data through the same Lakeflow pipeline so the
  customer narrative and the running system are provably the same build end to end.
