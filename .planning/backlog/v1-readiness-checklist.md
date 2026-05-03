---
title: "v1.0 Readiness Checklist"
status: backlog
area: deployment, infrastructure
priority: critical
related:
  - fix-god-object-decomposition.md
---

# What's Needed for v1.0

Based on the current state (94 API endpoints, 3695 Python tests, 830 frontend tests, 5 milestones complete, deployed on Databricks Apps), the app is already a working demo. v1.0 = "reliable, polished, shippable to external audiences" — not feature-complete, but everything that's there works confidently.

## Current State Assessment

| Area | Status | v1.0 Ready? |
|------|--------|-------------|
| Core sim + visualization (2D/3D) | Shipped | Yes |
| Multi-airport + OSM import | Shipped | Yes |
| ML predictions (delay, gate, congestion) | Shipped (rule-based) | Yes (demo-grade) |
| Calibration (1,183 profiles) | Shipped | Yes |
| FIDS + schedule generation | Shipped | Yes |
| Unified assistant (Genie + MCP) | Shipped | Yes |
| Simulation reports + event chat | Shipped | Yes |
| WebSocket real-time updates | Shipped | Yes |
| Deployment (DABs) | Shipped | Yes |
| Security (CORS, SQL injection) | Fixed | Yes (CORS scoped, SQLi fixed) |
| Auth on API endpoints | Databricks OAuth (Apps platform) | Yes (platform-level) |
| Test coverage | 3695 + 830 = 4525 tests | Yes |
| Documentation | 18 docs | Yes |

## Gaps to Close for v1.0

### MUST-HAVE (blocking v1.0)

| # | Item | Why | Effort | Status |
|---|------|-----|--------|--------|
| 1 | Validate 5 code-complete items on deployed app | Code is written but untested on Databricks — can't ship unvalidated features | 1-2 days | Code done |
| 2 | Fix 4 known test failures | DEN approach speed, taxi-out median, origin/dest generation, diversion after go-arounds | 1 day | Known |
| 3 | Deploy + run Lakebase sync job | Genie Space needs populated Delta tables — currently empty | 0.5 day | Code done |
| 4 | Run e2e smoke test on workspace | 11 endpoint tests — confirm they pass on live app | 0.5 day | Never run (0 runs) |
| 5 | Fix simulation drafts scenarios path | Users can't load built-in scenarios on Databricks | 0.5 day | Bug |

### SHOULD-HAVE (quality bar for v1.0)

| # | Item | Why | Effort | Status |
|---|------|-----|--------|--------|
| 6 | What-if simulation validated | Headline feature — must actually run sims, not stub | 1 day | Code done |
| 7 | Visual QA pass on deployed app | Header overflow, phase filter, 3D lighting, report scroll — verify everything | 0.5 day | Needs eyes |
| 8 | Update docs/SPECIFICATION.md | Reflects current state (report chat, drafts, 9 phases, phase filter) | 0.5 day | Stale |
| 9 | Retrain ML models with new features | Weather, congestion, inbound delay features are wired but models never retrained | 1 day | Code done |
| 10 | Security: remove /api/debug/paths | Exposes server filesystem structure — the one medium security issue worth fixing | 0.5 hr | Trivial |

### NICE-TO-HAVE (polish, not blocking)

| # | Item | Why | Effort |
|---|------|-----|--------|
| 11 | Aviation RAG pipeline | Grounded recommendations citing FAA/ICAO | 3-5 days |
| 12 | OpenFlights route ingestion | More realistic FIDS destinations | 2 days |
| 13 | Vite/esbuild update | HIGH-02 CVE (dev server only, not production risk) | 0.5 hr |

## v1.0 Checklist (ordered)

- [ ] 1. Fix 4 known test failures (backend)
- [ ] 2. Deploy Lakebase sync job + verify Delta tables populated
- [ ] 3. Run e2e smoke test on workspace — all 11 pass
- [ ] 4. Fix simulation drafts scenarios path bug
- [ ] 5. Validate report-chat what-if on deployed app (runs real sim)
- [ ] 6. Visual QA: header, phase filter, 3D, report scroll on deployed app
- [ ] 7. Retrain ML models (run OBT training job with new features)
- [ ] 8. Remove /api/debug/paths endpoint
- [ ] 9. Update SPECIFICATION.md with current features
- [ ] 10. Tag v1.0, update ROADMAP_V2.md
