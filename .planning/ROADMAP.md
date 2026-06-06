---
status: active
area: infrastructure
related: []
updated: 2026-06-06
---

# Airport Digital Twin — Roadmap

**Original 5 phases: COMPLETE** (data foundation → 2D → ML → 3D → platform integration, March 2026).

This roadmap covers the **46 remaining backlog items** organized by category.

*Last updated: 2026-06-06*

---

## 1. Simulation Realism & Accuracy (10 items)

High-impact items that make the simulation closer to reality.

| Priority | Item | Description |
|----------|------|-------------|
| P1 | [54-auto-calibration-non-us-airports](backlog/54-auto-calibration-non-us-airports.md) | Auto-calibrate traffic patterns for international airports |
| P1 | [61-fix-turnaround-taxi-gaps](backlog/61-fix-turnaround-taxi-gaps-bts-otp-validation.md) | Validate turnaround/taxi against BTS on-time data |
| P1 | [74-openflights-route-ingestion](backlog/74-openflights-route-ingestion.md) | Real route data for accurate FIDS origins/destinations |
| P2 | [59-unify-demo-simulation](backlog/59-unify-demo-simulation-single-path.md) | Eliminate demo/sim code duplication |
| P2 | [58-demo-24h-replay](backlog/58-demo-24h-simulation-replay.md) | Pre-computed 24h simulation for demo replay |
| P2 | [simulation-engine-refactor](backlog/simulation-engine-refactor.md) | Time injection, PhaseResolver, ScheduleBuilder |
| P2 | [long-simulation-persistence](backlog/long-simulation-persistence.md) | Persist sim state across restarts |
| P3 | [ground-event-explanations](backlog/ground-event-explanations.md) | Observable explanations for ground ops decisions |
| P3 | [live-gate-proximity-assignment](backlog/live-gate-proximity-assignment.md) | Real-time gate assignment from aircraft position |
| P3 | [calibration-based-delay-imputation](backlog/calibration-based-delay-imputation.md) | Use profile delay distributions for recorded data |

---

## 2. ML & Predictions (8 items)

| Priority | Item | Description |
|----------|------|-------------|
| P1 | [flifo-prediction-evaluation](backlog/flifo-prediction-evaluation.md) | Beat-FLIFO model: outperform airline delay predictions |
| P1 | [rename-turnaround-model-true-obt](backlog/rename-turnaround-model-design-true-obt.md) | Design true Off-Block Time prediction model |
| P2 | [38-kpi-prediction-calibration](backlog/38-kpi-prediction-calibration.md) | Calibrate KPI predictions against actuals |
| P2 | [56-ml-model-improvement](backlog/56-ml-model-improvement-sota-gaps.md) | Close gaps with SOTA aviation ML |
| P2 | [obt-eval-from-lakebase-eddf](backlog/obt-eval-from-lakebase-eddf.md) | OBT evaluation using real EDDF data |
| P2 | [obt-eval-notebook-databricks](backlog/obt-eval-notebook-databricks.md) | Databricks-native OBT evaluation notebook |
| P3 | [ml-model-endpoint-testing](backlog/ml-model-endpoint-testing-notebooks.md) | Test notebooks for ML serving endpoints |
| P3 | [opensky-sim-gap-analysis](backlog/opensky-sim-gap-analysis-obt-training.md) | Gap analysis: sim vs recorded for OBT training |

---

## 3. Data Integration & Pipelines (7 items)

| Priority | Item | Description |
|----------|------|-------------|
| P1 | [opensky-live-data](backlog/opensky-live-data-integration.md) | Real-time OpenSky ADS-B feed integration |
| P2 | [opensky-batch-enrichment](backlog/opensky-batch-event-enrichment-job.md) | Batch event enrichment from raw snapshots |
| P2 | [opensky-collector-defaults](backlog/opensky-collector-defaults-enrichment.md) | Improve collector defaults and enrichment |
| P2 | [gate-baggage-data-feed](backlog/gate-baggage-data-feed-prep.md) | Prepare gate + baggage real-time feeds |
| P3 | [calibration-delay-distributions](backlog/calibration-delay-distributions-for-recorded-data.md) | Apply calibration delays to recorded replay |
| P3 | [69-genie-lakebase-integration](backlog/69-genie-lakebase-integration.md) | Genie query federation with Lakebase |
| P3 | [lakebase-read-replica](backlog/lakebase-read-replica-auto-discovery.md) | Auto-discover and route to read replicas |

---

## 4. UX & Frontend (7 items)

| Priority | Item | Description |
|----------|------|-------------|
| P1 | [55-ux-silhouettes](backlog/55-ux-silhouettes-turnaround-loading-airline-terminal-baggage.md) | Aircraft silhouettes, turnaround speed, loading UX |
| P2 | [63-mobile-friendly](backlog/63-mobile-friendly-airport-digital-twin.md) | Full mobile-responsive layout |
| P2 | [72-ml-predictions-dashboard](backlog/72-ml-predictions-kpi-dashboard.md) | ML prediction accuracy dashboard |
| P2 | [satellite-tile-cache](backlog/satellite-tile-cache-eviction-smart-loading.md) | Smart cache-first tile loading + staleness UI |
| P3 | [77-maintenance-overlay](backlog/77-maintenance-mode-overlay.md) | Graceful maintenance overlay during deploys |
| P3 | [viewer-vs-controller-roles](backlog/viewer-vs-controller-roles.md) | Read-only viewer vs admin roles |
| P3 | [simulation-report-chat-rag](backlog/simulation-report-chat-aviation-rag.md) | RAG-powered report chat with aviation knowledge |

---

## 5. Dashboards & Analytics (3 items)

| Priority | Item | Description |
|----------|------|-------------|
| P1 | [airport-kpi-metric-views-dashboard](backlog/airport-kpi-metric-views-dashboard.md) | Metric Views + Lakeview dashboard |
| P2 | [airport-kpis-metric-views](backlog/airport-kpis-metric-views.md) | Define metric views (delay, throughput, utilization) |
| P2 | [70-ops-review-gap-analysis](backlog/70-ops-review-gap-analysis-improvement-plan.md) | Simulation vs reality gap analysis |

---

## 6. Code Quality & Testing (7 items)

| Priority | Item | Description |
|----------|------|-------------|
| P2 | [consolidate-calibration-globals](backlog/consolidate-calibration-globals.md) | Replace lifecycle global state with dataclass |
| P2 | [expand-validation-test-suite](backlog/expand-validation-test-suite.md) | 10 missing validation tests |
| P2 | [fix-codebase-structural-gaps](backlog/fix-codebase-structural-gaps-regression-tests.md) | Structural fixes + regression tests |
| P3 | [test-single-flight-tracking](backlog/test-single-flight-tracking-features.md) | Test coverage for flight tracker |
| P3 | [complexity-baseline](backlog/complexity-baseline.md) | Cyclomatic complexity baseline |
| P3 | [crap-ratio-refactor](backlog/crap-ratio-refactor-prompt.md) | Test-guarded refactoring of high-CRAP functions |
| P3 | [coverage-gaps-self-diagnosis](backlog/coverage-gaps-claude-self-diagnosis.md) | Self-diagnosis infrastructure |

---

## 7. Infrastructure & Operations (3 items)

| Priority | Item | Description |
|----------|------|-------------|
| P2 | [57-infrastructure-scaling](backlog/57-infrastructure-inventory-scaling.md) | Infrastructure inventory + scaling estimate |
| P2 | [60-validation-external-data](backlog/60-validation-free-external-data-sources.md) | Validate against FAA/Eurocontrol data |
| P1 | [v1-readiness-checklist](backlog/v1-readiness-checklist.md) | Production v1.0 release checklist |

---

## 8. Computer Vision (1 item)

| Priority | Item | Description |
|----------|------|-------------|
| P3 | [yolo-fine-tuning](backlog/yolo-fine-tuning-on-databricks.md) | Fine-tune YOLO for satellite aircraft detection |

---

## Summary

| Category | Count | P1 | P2 | P3 |
|----------|-------|----|----|-----|
| Simulation Realism | 10 | 3 | 4 | 3 |
| ML & Predictions | 8 | 2 | 4 | 2 |
| Data Integration | 7 | 1 | 3 | 3 |
| UX & Frontend | 7 | 1 | 3 | 3 |
| Dashboards | 3 | 1 | 2 | 0 |
| Code Quality | 7 | 0 | 3 | 4 |
| Infrastructure | 3 | 1 | 2 | 0 |
| Computer Vision | 1 | 0 | 0 | 1 |
| **Total** | **46** | **9** | **21** | **16** |
