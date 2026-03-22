# Turnaround & Taxi Calibration — Results Summary

## Problem Fixed

| Metric | Before | After | Real (BTS) |
|--------|--------|-------|------------|
| Turnaround | avg 26.8 min | avg 67.1 min | median 72 min |
| Taxi-out cap | 10 min max | P95-calibrated (35 min SFO) | mean 20.4 min |
| Taxi-in cap | 10 min max | P95-calibrated (17 min SFO) | mean 8.5 min |

## Files Modified

- `src/calibration/bts_ingest.py` — Extract TaxiOut/TaxiIn/turnaround proxy from OTP
- `src/calibration/profile.py` — 7 new fields on AirportProfile dataclass
- `src/calibration/profile_builder.py` — Wire taxi/turnaround stats into profile enrichment
- `src/simulation/engine.py` — `_calibrated_turnaround()` + profile-based taxi caps
- `src/ingestion/fallback.py` — `set_calibration_gate_minutes()` physics override
- `scripts/download_calibration_data.py` — `--otp` flag for OTP PREZIP downloads
- `scripts/refresh_calibration_data.py` — New orchestrator: download + rebuild + diff
- `resources/calibration_refresh_job.yml` — Weekly Databricks job (Monday 06:00 UTC)
- `tests/test_calibration_taxi_turnaround.py` — 9 new validation tests
- `tests/test_flight_realism.py` — Fixed turnaround test for calibration override
- 32 rebuilt profile JSONs

## Non-US Airports

The 12 international airports (LHR, CDG, FRA, AMS, HKG, NRT, SIN, SYD, DXB, ICN, GRU, JNB) currently use openflights+known_stats and have 0.0 for taxi/turnaround — the simulation falls back to the GSE model for them. To calibrate these:

1. **Eurocontrol CODA** — European airports publish average taxi/turnaround times in annual reports. Add these as manual overrides in `src/calibration/known_profiles.py`
2. **OpenSky ADS-B** — Compute taxi times from ADS-B traces (runway → gate timestamps). The `src/calibration/opensky_ingest.py` module already exists, but doesn't extract taxi times yet
3. **Airport CDM/A-CDM data** — Some airports publish CDM data with TOBT/TSAT/ASAT timestamps that give precise turnaround data
4. **IATA Ground Handling Manual** — Published standard turnaround times by aircraft type for major airports

**Simplest path:** Add a `taxi_turnaround_overrides` dict in `known_profiles.py` with published stats from Eurocontrol/IATA reports for the 12 international airports.
