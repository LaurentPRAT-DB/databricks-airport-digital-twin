# Plan: Realism Scorecard + Gap-Closing Improvements

## Context

The synthetic flight generator uses calibrated AirportProfile distributions (from BTS T-100, OpenSky, OurAirports) to drive airline mix, route frequencies, fleet mix, hourly patterns, and delay statistics. But there's no automated way to measure how close the simulation output actually is to these real-world profiles. We need a scorecard that runs the generator, collects output distributions, compares them against the ground truth, and identifies the biggest gaps — then fixes to close them.

## Part 1: Realism Scorecard Script

**File:** `scripts/realism_scorecard.py`

### What it measures

Run `generate_daily_schedule()` multiple times for each of the 33 profiled airports, collect the output, and score against the BTS/known profile across 7 dimensions:

| # | Dimension | Metric | Ground Truth Source |
|---|-----------|--------|---------------------|
| 1 | Airline mix | Jensen-Shannon divergence | `AirportProfile.airline_shares` |
| 2 | Route frequency | JS divergence of destination distribution | `domestic_route_shares` + `international_route_shares` |
| 3 | Domestic ratio | Absolute difference | `domestic_ratio` |
| 4 | Fleet mix | JS divergence per airline (averaged) | `fleet_mix` |
| 5 | Hourly pattern | Cosine similarity of 24h histogram | `hourly_profile` |
| 6 | Delay rate | Absolute difference | `delay_rate` |
| 7 | Delay code distribution | JS divergence | `delay_distribution` |

### Scoring

Each dimension gets a 0-100 score:
- JS divergence: `score = max(0, 100 * (1 - jsd / 0.2))` — 0.0 JSD → 100, ≥0.2 JSD → 0
- Absolute diff: `score = max(0, 100 * (1 - abs_diff / 0.10))` — 0% diff → 100, ≥10% diff → 0
- Cosine similarity: `score = max(0, sim * 100)`

Overall airport score = weighted average (airline 25%, route 20%, fleet 15%, hourly 15%, delay rate 10%, delay codes 10%, domestic ratio 5%).

### Implementation approach

Uses pure Python (no scipy dependency) — JSD via `math.log2` + manual computation, cosine via dot product.

```python
def js_divergence(p: dict, q: dict) -> float:
    """Jensen-Shannon divergence between two distributions (0=identical, 1=opposite)."""
    # Merge keys, normalize, compute M = (P+Q)/2, return (KL(P||M) + KL(Q||M)) / 2

def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors (1=identical, 0=orthogonal)."""

def score_airport(icao: str, n_schedules: int = 10) -> dict:
    """Generate n_schedules, aggregate distributions, compare to profile."""
    profile = loader.get_profile(iata)
    all_flights = []
    for _ in range(n_schedules):
        schedule = generate_daily_schedule(airport=iata, profile=profile)
        all_flights.extend(schedule)
    # Extract synthetic distributions, compute scores per dimension
```

### Output format

```
================================================================================
  REALISM SCORECARD — 33 airports, 10 schedules each
================================================================================
  Airport   Airline  Route  Fleet  Hourly  Delay%  DelayCd  DomRat  OVERALL
  ────────  ───────  ─────  ─────  ──────  ──────  ───────  ──────  ───────
  KSFO        92      85     78     88      95      82       97       88
  ...
  AVERAGE     85      78     65     80      90      75       92       81

  WEAKEST DIMENSIONS (across all airports):
  1. Fleet mix (avg 65) — unmapped BTS codes
  2. Route frequency (avg 78) — missing coordinates for profile routes
  3. Delay code distribution (avg 75) — bimodal duration model too crude
================================================================================
```

### Key code reuse

- `src/calibration/profile.py` → `AirportProfileLoader.get_profile()` — load ground truth
- `src/calibration/known_profiles.py` → `get_known_profile()` — hand-researched profiles
- `src/ingestion/schedule_generator.py` → `generate_daily_schedule()` — generate synthetic output
- `src/calibration/profile.py` → `_iata_to_icao()`, `_icao_to_iata()` — code conversion

## Part 2: Identified Realism Gaps + Fixes

Based on code analysis, these are the gaps ordered by impact:

### Gap 1: Fleet mix has unmapped BTS numeric codes (Impact: HIGH)

**Problem:** `KSFO.json` fleet_mix has codes like `0A875`, `06725`. The `_normalize_fleet_mix()` maps known codes via `BTS_AIRCRAFT_TYPE_MAP`, but unmapped codes pass through and never match aircraft type lists.

**Fix:**
- Expand `BTS_AIRCRAFT_TYPE_MAP` with remaining unmapped codes (inspect all 33 profile JSONs for unknown codes)
- Add catch-all in `_normalize_fleet_mix()`: if a code isn't in the map and doesn't look like an ICAO type (4 chars, alpha), log a warning and map it to `A320` (narrowbody default)

**Files:** `src/calibration/profile.py`

### Gap 2: Delay duration distribution is bimodal, not realistic (Impact: MEDIUM)

**Problem:** `_generate_delay()` uses 80% short (5..mean) / 20% long (mean..2×mean). For KSFO (mean=71min), 80% of delays are 5-71 min uniform. Real delays follow a log-normal distribution — most are 15-30 min with a long tail.

**Fix:** Replace the bimodal split with `random.lognormvariate(mu, sigma)` where `mu = ln(mean_delay) - sigma²/2` and `sigma = 0.8`. This produces realistic right-skewed delays. Cap at 180 min.

**File:** `src/ingestion/schedule_generator.py` → `_generate_delay()`

### Gap 3: Hourly pattern scaling loses shape fidelity (Impact: MEDIUM)

**Problem:** `_get_flights_per_hour()` scales calibrated `hourly_profile` weights to max ~25 and adds ±2 integer jitter. A weight of 0.02 and 0.05 both round to 0-1 flights — the profile's fine shape gets flattened.

**Fix:** In `generate_daily_schedule()`, compute total daily flights first (sum of all hourly slots from `TRAFFIC_PROFILES` base), then distribute them across hours using profile weights as multinomial probabilities. This preserves the exact hourly shape.

**File:** `src/ingestion/schedule_generator.py` → `generate_daily_schedule()` + `_get_flights_per_hour()`

### Gap 4: Missing airport coordinates for profile routes (Impact: LOW)

**Problem:** BTS profiles include routes (SLC, HNL, IAD, AUS, BOI, MSY, etc.) not in `AIRPORT_COORDINATES`. Trajectory bearing computation falls back to random when coordinates are missing.

**Fix:** Auto-load coordinates from `data/calibration/raw/airports.csv` (OurAirports data, already downloaded). Fall back to static dict.

**File:** `src/ingestion/schedule_generator.py` → new `_load_airport_coordinates()`

### Gap 5: 50/50 arrival/departure split (Impact: LOW)

**Problem:** Every hour is 50% arrivals / 50% departures. Real hub airports have wave patterns — arrivals cluster before departures (connect banks).

**Fix:** Future work — add `arrival_ratio_by_hour` to `AirportProfile`. Not in this PR.

### Gap 6: Turnaround times not benchmarked against published data (Impact: INFORMATIONAL)

Current values: narrow 45 min, wide 90 min. Industry benchmarks: IATA SGHA narrow 30-45 min, wide 60-90 min. Eurocontrol CODA average 44 min. Our values are at the upper end but within range. No code change needed — document in scorecard output.

## Part 3: Implementation Plan

### Phase A — Scorecard + tests (this PR)

1. Create `scripts/realism_scorecard.py` — pure Python, no new dependencies
2. Create `tests/test_realism_scorecard.py` — verify scoring math with known inputs
3. Run scorecard, capture baseline results

### Phase B — Quick wins to improve scores (same PR)

4. Scan all 33 profile JSONs for unmapped BTS fleet codes, expand `BTS_AIRCRAFT_TYPE_MAP`
5. Add unknown-code fallback in `_normalize_fleet_mix()`
6. Replace bimodal delay duration with log-normal distribution
7. Re-run scorecard, verify improvement

### Phase C — Structural improvements (future PR)

8. Total-then-distribute hourly pattern approach
9. Dynamic airport coordinates from OurAirports CSV
10. Arrival/departure wave patterns

## Files to Create/Modify

| Action | File | Purpose |
|--------|------|---------|
| Create | `scripts/realism_scorecard.py` | Scorecard: generate schedules, compare to profiles, score & report |
| Create | `tests/test_realism_scorecard.py` | Unit tests for JS divergence, cosine similarity, scoring functions |
| Modify | `src/calibration/profile.py` | Expand `BTS_AIRCRAFT_TYPE_MAP`, add fallback for unknown fleet codes |
| Modify | `src/ingestion/schedule_generator.py` | Log-normal delay duration |

## Verification

1. `python scripts/realism_scorecard.py` — produces table for all 33 airports
2. `python scripts/realism_scorecard.py --airports SFO JFK LAX` — subset mode
3. `uv run pytest tests/test_realism_scorecard.py -v` — scoring math tests pass
4. `uv run pytest tests/ -v -x --ignore=tests/test_airport_persistence.py` — no regressions
