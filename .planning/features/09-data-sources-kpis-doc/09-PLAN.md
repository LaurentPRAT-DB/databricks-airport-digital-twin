# Plan: Airport Open Data Sources & KPI Reference Document

**Phase:** 09 — Post-v1
**Date:** 2026-03-09
**Status:** Implemented

---

## Context

Before building the BTS ingestion pipeline, we need a comprehensive reference document that catalogs all available free/open aviation data sources and maps them to airport operational KPIs. This document will:
1. Serve as a data catalog for deciding which sources to ingest
2. Explain each KPI's value for airport operational excellence
3. Guide the ML model training strategy

---

## Deliverable

Create `docs/AIRPORT_DATA_SOURCES_AND_KPIS.md` — a comprehensive reference document.

---

## Document Structure

### Part 1: Open Data Sources (8 sources)

For each source, document: provider, URL, data content, format, update frequency, coverage, access method, and which KPIs it enables.

1. **BTS On-Time Performance** (transtats.bts.gov) — US flight delays, taxi times, cancellations
2. **FAA OPSNET / ASPM** (aspm.faa.gov) — Airport operations, throughput, delays
3. **Eurocontrol Performance Review** (ansperformance.eu) — European airport KPIs
4. **OpenSky Network** (opensky-network.org) — Global ADS-B flight tracking
5. **NOAA Aviation Weather** (aviationweather.gov) — METAR/TAF historical archives
6. **FAA TFMS / ATCSCC** — Traffic Flow Management System advisories
7. **OurAirports** (ourairports.com) — Global airport/runway database (CSV)
8. **Eurostat Air Transport** (ec.europa.eu/eurostat) — EU passenger/freight statistics

### Part 2: Airport Operational KPIs (organized by domain)

For each KPI: definition, formula, target values, operational significance, which data source provides it, and which ML model benefits.

**Domains:**
- Airside Operations (runway throughput, taxi times, turnaround)
- Punctuality & Delays (OTP, delay causes, propagation)
- Capacity & Congestion (peak utilization, gate occupancy)
- Safety & Weather Impact (weather-related delays, diversions)
- Passenger Experience (connection reliability, baggage handling)

### Part 3: Data Source → KPI → ML Model Mapping Matrix

A cross-reference table showing how each data source feeds into specific KPIs and how those map to the existing ML models.

---

## Files

| File | Action |
|------|--------|
| `docs/AIRPORT_DATA_SOURCES_AND_KPIS.md` | Create (~400 lines) |
| `README.md` | Modify — add to docs index |

---

## Verification

1. Document renders correctly in GitHub markdown
2. All URLs are valid
3. KPIs cover the 5 operational domains
4. Cross-reference matrix links sources → KPIs → ML models
