---
status: backlog
area: data
related: []
---

# Calibration-Based Delay Imputation for Recorded Data

**Status:** Backlog
**Date added:** 2026-04-06
**Related:** OpenSky Sim Gap Analysis for OBT Training
**Scope:** Use existing calibration profiles to fill delay/schedule gaps in recorded data

---

## What Calibration Profiles Give Us Per Airport

- **`delay_rate`** — fraction of flights that are delayed (e.g., ATL: 22%, JFK: 28%, SIN: 8%)
- **`mean_delay_minutes`** — average delay when delayed (e.g., ATL: 28min, JFK: 32min)
- **`delay_distribution`** — BTS delay cause codes with weights (carrier, weather, NAS, security, late aircraft)

## How to Use It for Recorded Data

Instead of `arrival_delay_min = 0`, we can:

1. **Load the airport's calibration profile** (we have 43 known-stats + ~1183 auto-calibrated profiles)
2. **Sample stochastically:** with probability `delay_rate`, draw from an exponential/gamma distribution centered on `mean_delay_minutes`; otherwise set to 0
3. **For `scheduled_buffer_min`:** derive from the sampled delay — if we sampled a 20min delay, the scheduled buffer would be ~(turnaround_nominal - delay), giving a plausible value
4. **For `scheduled_departure_hour`:** offset actual departure hour backward by the sampled delay (e.g., if actual dep was 14:35 and sampled delay is 35min, scheduled hour = 14:00 → hour 14)

## Key Insight

This isn't ground truth, but it's **statistically representative**. The model trained on simulation data already uses these same distributions to generate delays. By sampling from the same distributions for recorded data, the feature distributions match what the model learned — much better than all-zeros, which the model never saw during training.

## Tradeoffs

- **(+)** Feature distributions match training data → better predictions
- **(+)** No external data source needed
- **(-)** Per-flight delay is fictional — but the distribution is real (BTS-sourced)
- **(-)** Adds noise vs. zeros, but it's calibrated noise
