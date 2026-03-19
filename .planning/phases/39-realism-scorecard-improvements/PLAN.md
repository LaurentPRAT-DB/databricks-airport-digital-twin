# Plan: Improve Realism Scorecard — Top 3 Weak Dimensions

## Context

The realism scorecard scores 93/100 avg across 33 airports. Three dimensions drag the score down:
1. Domestic ratio (avg 73) — 4 airports score 0 (FRA, CDG, NRT, ICN)
2. Delay rate (avg 88) — 5 airports score ≤77 (DXB 70, CLT 72, EWR 73, GRU 73, FRA 77)
3. Hourly pattern (avg 89) — DXB worst at 81

All three have clear root causes in how the scorecard measures and how the generator produces flights.

---

## Fix 1: Domestic Ratio (0-score airports: FRA, CDG, NRT, ICN)

### Root Cause

For FRA/CDG/NRT/ICN, `domestic_route_shares` is `{}` — all routes are in `international_route_shares`. In `_select_destination()` (schedule_generator.py:171), when `is_domestic=True` but `domestic_route_shares` is empty, it falls through to `international_route_shares`. All generated destinations end up international.

The scorecard (realism_scorecard.py:156) classifies flights using `profile.international_route_shares.keys()` as the international set. Since every destination is in that set, `syn_domestic_ratio = 0.0`. But `profile.domestic_ratio = 0.10-0.15`. The `diff ÷ threshold(0.10)` = score 0.

### Fix

Add country-based domestic airport lookup to `schedule_generator.py`:

```python
COUNTRY_DOMESTIC_AIRPORTS = {
    "DE": ["MUC", "DUS", "HAM", "BER", "STR", "CGN"],
    "FR": ["ORY", "NCE", "LYS", "MRS", "TLS", "BOD"],
    "JP": ["HND", "KIX", "FUK", "CTS", "OKA", "NGO"],
    "KR": ["GMP", "PUS", "CJU", "TAE", "KWJ"],
    "GB": ["LGW", "MAN", "EDI", "BHX", "GLA", "BRS"],
    "NL": ["EIN", "RTM", "MST"],
    "AE": ["AUH", "SHJ", "DWC"],
    "SG": [],  "HK": [],
    "AU": ["MEL", "BNE", "PER", "ADL", "CBR", "OOL"],
    "BR": ["CGH", "GIG", "BSB", "CNF", "SSA", "CWB"],
    "ZA": ["CPT", "DUR", "PLZ", "BFN"],
}
AIRPORT_COUNTRY = {
    "FRA": "DE", "CDG": "FR", "NRT": "JP", "ICN": "KR",
    "LHR": "GB", "AMS": "NL", "DXB": "AE", "SIN": "SG",
    "HKG": "HK", "SYD": "AU", "GRU": "BR", "JNB": "ZA",
}
```

Update `_select_destination()`: When `is_domestic=True` and `domestic_route_shares` is empty, look up the airport's country and pick uniformly from `COUNTRY_DOMESTIC_AIRPORTS`. If no domestic airports exist (SG, HK), fall through to international.

Update scorecard (realism_scorecard.py:154-162): Use country-based classification — a flight to a same-country airport is domestic. Build a set of all known domestic IATA codes per country from both `COUNTRY_DOMESTIC_AIRPORTS` and the US `DOMESTIC_AIRPORTS` list.

### Files

- `src/ingestion/schedule_generator.py` — add dicts, update `_select_destination()`
- `scripts/realism_scorecard.py` — country-based domestic classification

### Expected Impact

FRA/CDG/NRT/ICN: 0 → ~85-100. Overall domestic_ratio avg: 73 → ~90+.

---

## Fix 2: Delay Rate (worst: DXB 70, CLT 72, EWR 73, GRU 73, FRA 77)

### Root Cause

`_generate_delay()` (schedule_generator.py:212-244) correctly reads `profile.delay_rate` as the per-flight Bernoulli probability. But with ~250 flights per schedule and only 3-5 schedules, the realized rate fluctuates ±3-5%. `score_abs_diff(diff, threshold=0.10)` is linear: 3% deviation costs 30 points.

### Fix

Two-pass delay assignment in `generate_daily_schedule()`:

1. Generate all flights with `delay_minutes=0` initially (remove the per-flight `_generate_delay()` call in the loop)
2. After the hour loop, compute `n_delayed = round(len(schedule) * profile.delay_rate)` (or 0.15 default)
3. Randomly select `n_delayed` flights, apply delay to each (call `_generate_delay_details()` for code/reason/minutes)
4. Update status/estimated_time for the delayed flights

Split `_generate_delay()` into: the existing function keeps doing the Bernoulli flip for non-profile callers, and a new `_generate_delay_details()` returns just (minutes, code, reason) without the rate check.

### Files

- `src/ingestion/schedule_generator.py` — refactor delay assignment to two-pass

### Expected Impact

All airports delay_rate → 95-100. Overall avg: 88 → ~98.

---

## Fix 3: Hourly Pattern (worst: DXB 81, NRT/FRA/ICN 86-87)

### Root Cause

`_get_flights_per_hour()` (schedule_generator.py:348-354) converts calibrated weights to counts:
```python
scaled = weight / max_weight * 25
base = max(0, int(scaled + random.uniform(-2, 2)))
```

Fixed ±2 noise on a 0-25 scale: at low-traffic hours (scaled=0.8), noise of ±2 means 0-3 flights — blurring the profile shape. DXB's 3-bank hub pattern with significant early-morning activity gets washed out.

### Fix

Proportional noise instead of fixed ±2:

```python
noise_range = max(0.5, scaled * 0.15)  # 15% proportional noise
base = max(0, int(scaled + random.uniform(-noise_range, noise_range)))
```

Low-traffic hours get minimal noise; peak hours get proportionally more. Shape is preserved.

### Files

- `src/ingestion/schedule_generator.py` — update noise calculation in `_get_flights_per_hour()`

### Expected Impact

DXB: 81 → ~90. Overall hourly avg: 89 → ~94.

---

## Summary

| File | Changes | Dimensions |
|------|---------|------------|
| `src/ingestion/schedule_generator.py` | Country domestic dicts, `_select_destination()` fallback, two-pass delay, proportional hourly noise | All 3 |
| `scripts/realism_scorecard.py` | Country-based domestic classification | Domestic ratio |

## Verification

1. Baseline: `uv run python scripts/realism_scorecard.py --schedules 5` (record scores)
2. Apply all three fixes
3. Re-run scorecard, check:
   - FRA/CDG/NRT/ICN domestic_ratio > 80 (was 0)
   - DXB/CLT/EWR/GRU/FRA delay_rate > 90 (was 70-77)
   - DXB hourly > 88 (was 81)
   - Overall avg > 95 (was 93)
4. Run tests: `uv run pytest tests/test_realism_scorecard.py tests/test_schedule_generator.py -v`
