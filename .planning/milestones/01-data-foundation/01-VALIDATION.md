---
phase: 1
slug: data-foundation
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-05
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x (Python) |
| **Config file** | none — Wave 0 installs |
| **Quick run command** | `pytest tests/ -x -q --tb=short` |
| **Full suite command** | `pytest tests/ -v` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/ -x -q --tb=short`
- **After every plan wave:** Run `pytest tests/ -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 01-01-01 | 01 | 1 | DATA-01 | integration | `pytest tests/test_ingestion.py -k opensky` | ❌ W0 | ⬜ pending |
| 01-01-02 | 01 | 1 | DATA-02 | integration | `pytest tests/test_ingestion.py -k fallback` | ❌ W0 | ⬜ pending |
| 01-02-01 | 02 | 1 | DATA-03 | integration | `pytest tests/test_dlt.py -k medallion` | ❌ W0 | ⬜ pending |
| 01-02-02 | 02 | 1 | DATA-04 | integration | `pytest tests/test_unity_catalog.py` | ❌ W0 | ⬜ pending |
| 01-02-03 | 02 | 1 | DATA-05 | integration | `pytest tests/test_unity_catalog.py -k lineage` | ❌ W0 | ⬜ pending |
| 01-03-01 | 03 | 2 | STRM-01 | integration | `pytest tests/test_streaming.py -k realtime` | ❌ W0 | ⬜ pending |
| 01-03-02 | 03 | 2 | STRM-02 | integration | `pytest tests/test_streaming.py -k late_data` | ❌ W0 | ⬜ pending |
| 01-03-03 | 03 | 2 | STRM-03 | integration | `pytest tests/test_streaming.py -k checkpoint` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/conftest.py` — shared fixtures for Databricks mocking
- [ ] `tests/test_ingestion.py` — stubs for DATA-01, DATA-02
- [ ] `tests/test_dlt.py` — stubs for DATA-03 medallion tests
- [ ] `tests/test_unity_catalog.py` — stubs for DATA-04, DATA-05
- [ ] `tests/test_streaming.py` — stubs for STRM-01, STRM-02, STRM-03
- [ ] `pytest` installation in pyproject.toml

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Unity Catalog lineage graph visual | DATA-05 | Requires UI inspection | Navigate to Unity Catalog > table > Lineage tab, verify Bronze→Silver→Gold chain |
| Streaming checkpoint recovery | STRM-03 | Requires job restart | Stop streaming job, restart, verify no data loss in Gold table |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
