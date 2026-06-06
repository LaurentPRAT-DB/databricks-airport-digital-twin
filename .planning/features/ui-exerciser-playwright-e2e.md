---
status: complete
area: frontend
related: []
---

# UI Exerciser Script — Playwright E2E against deployed Databricks App

## Context

Need a script that exercises the deployed app UI like a real user: navigate, switch airports, check flights render correctly, measure timings, capture console errors and incorrect behavior. Claude Code runs it after deploy, reads the results, and fixes issues automatically.

## Approach

Playwright (Python) — already installed on this machine. Runs headless Chrome against the deployed Databricks App URL with OAuth auth.

The script:
1. Authenticates via Databricks token (injected as cookie/header)
2. Walks through key user scenarios
3. Collects: timings, console errors, screenshot on failure, flight position data
4. Outputs structured JSON report that Claude Code can parse

**File:** `scripts/test_ui_e2e.py`

## Scenarios to exercise

| ID  | Scenario              | What to check                                  | Pass criteria                                        |
|-----|-----------------------|------------------------------------------------|------------------------------------------------------|
| S1  | Initial page load     | Page renders, map visible, flights appear       | < 10s load, no console errors, flight count > 0      |
| S2  | Flight list populates | Sidebar shows flight cards                      | At least 5 flights visible                           |
| S3  | Click a flight        | Flight detail panel opens, map centers          | Panel shows callsign, origin, destination            |
| S4  | Switch to 2D/3D       | Toggle view mode                                | No crash, flights still visible                      |
| S5  | Switch airport (MMMX) | Click airport selector, pick MMMX               | Progress overlay appears, completes < 30s, flights near MEX coords |
| S6  | Verify MMMX flights   | After switch, check flight positions            | Ground flights lat ~19.4, no flights at lat ~37.6    |
| S7  | Switch airport (LSGG) | Switch to Geneva                                | Completes, flights near GVA coords                   |
| S8  | Switch back to KSFO   | Return to default                               | Flights at SFO coords                                |
| S9  | Open simulation report| Click report button if present                  | Modal opens without error                            |
| S10 | Console error check   | Aggregate all console errors across scenarios   | Zero uncaught exceptions                             |

## Auth strategy

The Databricks App uses OAuth. Playwright can:
1. Get a token via `databricks auth token --profile FEVM_SERVERLESS_STABLE`
2. Set it as a cookie or Authorization header on all requests via `page.set_extra_http_headers()`

## Output format

```json
{
  "url": "https://...",
  "timestamp": "2026-04-14T...",
  "scenarios": [
    {
      "id": "S1",
      "name": "Initial page load",
      "status": "pass",
      "duration_ms": 4200,
      "details": "65 flights loaded, map rendered",
      "console_errors": [],
      "screenshot": null
    }
  ],
  "summary": { "pass": 9, "fail": 1, "total_duration_ms": 95000 },
  "console_errors_total": ["TypeError: Cannot read..."]
}
```

## Claude Code command

Create `.claude/commands/ui-test.md` that:
1. Runs `uv run python scripts/test_ui_e2e.py`
2. Reads the JSON report
3. For each FAIL: diagnoses root cause, implements fix
4. Re-deploys and re-runs

## Files Modified

| File | Change |
|------|--------|
| `scripts/test_ui_e2e.py` | New Playwright E2E test script |
| `.claude/commands/ui-test.md` | New slash command for automated test + fix loop |

## Verification

1. `uv run python scripts/test_ui_e2e.py` — all 10 scenarios pass against deployed app
2. JSON report is valid and parseable
3. Screenshots captured on any failure for debugging
4. `/ui-test` command runs end-to-end and produces actionable output
