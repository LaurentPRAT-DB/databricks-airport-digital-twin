# What-If Scenario Report: JFK Nor'easter Winter Storm

**Airport:** John F. Kennedy International Airport (KJFK)
**Scenario:** Nor'easter Winter Storm — US Northeast
**Simulation Date:** 2026-03-15 (24-hour simulation)
**Total Scheduled Flights:** 1,020 (516 arrivals / 504 departures)
**Report Generated:** 2026-03-29

---

## Executive Summary

This simulation models a severe Nor'easter winter storm impacting JFK Airport over a 24-hour period. The storm produces heavy snowfall, near-zero visibility, and sustained gusts up to 52 knots, causing **massive operational disruption** with only **23% on-time performance** and **125 flight cancellations**. The scenario reveals critical vulnerabilities in winter operations planning, runway snow removal capacity, and ground handling during extended de-icing requirements.

**Key Finding:** The 3-hour period between 08:00-11:00 UTC where both runways are simultaneously closed creates a cascading backlog that takes over 6 hours to clear, even after weather improves. Pre-emptive ground stops and strategic cancellations before the peak storm window are essential to prevent uncontrollable congestion.

---

## Weather Timeline

| Time (UTC) | Condition | Visibility | Ceiling | Gusts | Flight Rules |
|---|---|---|---|---|---|
| 00:00-05:00 | Clear/Pre-storm | Normal | Normal | Calm | VFR |
| 05:00-08:00 | Light snow | 3.0 nm | 1,500 ft | 28 kt | IFR |
| **08:00-12:00** | **Severe snow** | **0.25 nm** | **200 ft** | **52 kt** | **LIFR** |
| 12:00-15:00 | Moderate snow | 0.75 nm | 500 ft | 42 kt | LIFR |
| 15:00-17:00 | Light snow | 2.0 nm | 1,200 ft | 32 kt | IFR |
| 17:00-24:00 | Clearing | 8.0 nm | 4,000 ft | Calm | VFR |

---

## Operational Impact Summary

| Metric | Value | Assessment |
|---|---|---|
| On-time Performance | **23.0%** | Critical — well below 70% threshold |
| Avg Schedule Delay | 54.9 min | Severe — passengers miss connections |
| Avg Capacity Hold | 124.1 min | Extreme — 2+ hour avg holding time |
| Max Capacity Hold | 354.3 min | Nearly 6 hours — unacceptable |
| Go-Arounds | 5 | Elevated risk due to LIFR conditions |
| Cancellations | 125 (12.3%) | Significant but necessary |
| Peak Simultaneous Flights | 208 | Congestion well above normal capacity |
| Gate Utilization | 20 gates | Maximum gate utilization reached |

---

## Critical Events Timeline

### Phase 1: Pre-Storm Preparation (05:00-08:00 UTC)

- **05:00** — Light snow begins. De-icing operations activated for **12 hours** (through 17:00). All departing aircraft require de-icing, adding 15-30 min per turnaround.
- **06:00** — Runway 28R closed for 60 min for preventive snow removal. Airlines begin **proactive cancellations** — 125 flights cancelled by end of storm. Early morning departures experience growing delays.
- **07:15** — First capacity holding events begin. JBU2568 enters arrival hold. Within minutes, multiple arrivals stacking up.

**Operator Action Required:** Activate winter operations plan. Pre-position de-icing equipment. Begin proactive cancellation decisions for afternoon flights. Notify airlines of anticipated 4-6 hour disruption window.

### Phase 2: Peak Storm — Total Gridlock (08:00-12:00 UTC)

This is the **most critical window**. Multiple simultaneous failures compound:

- **08:00** — Severe snow hits: 0.25 nm visibility, 200 ft ceiling, 52 kt gusts. LIFR conditions.
  - Runway 28L closed for **210 min** (3.5 hours) due to heavy snow accumulation.
  - Gate B8 (Terminal 4) fails — inaccessible for 6 hours.
  - Taxiway M closed due to sand drift for 6 hours (note: in winter scenario this would be snow/ice).
- **09:00** — Runway 28R also closed for **180 min** (3 hours). **Both runways now closed simultaneously.**
  - No arrivals or departures possible.
  - All airborne arrivals must hold or divert.
  - Taxiway A closed (snow/ice) for 5 hours — ground movement severely restricted.
- **09:54** — DAL1742 executes go-around in LIFR conditions. Dangerous situation.
- **10:00** — Gate A3 (Terminal 1) fails — inaccessible for 4 hours. Now 2 gates out of service.
- **10:41** — AFR1642 go-around. International long-haul forced to re-attempt approach.
- **11:00** — **Ground stop declared.** No departures cleared. Arrival flow completely halted.
- **11:41** — JBU1673 go-around.

**Operator Action Required:** Declare ground stop pre-emptively at 08:00 (before both runways close). Coordinate with TRACON for holding patterns with fuel-aware sequencing. Activate mutual aid with EWR/LGA for diversions. Deploy all available snow removal equipment on priority runway.

### Phase 3: Recovery Begins (12:00-15:00 UTC)

- **12:00** — Weather moderates to moderate snow (0.75 nm vis, 500 ft ceiling). Still LIFR. At least one runway re-opens.
- **13:59** — OTH189 go-around. Conditions still marginal.
- **14:00** — Ground stop lifted. Departure queue begins to clear but backlog is enormous.

**Operator Action Required:** Prioritize international long-haul connections for early departure slots. Sequence arrivals by fuel remaining. Monitor gate availability — with 2 gates OOS, turnarounds are constrained.

### Phase 4: Extended Recovery (15:00-24:00 UTC)

- **15:00** — Light snow, improving visibility. IFR conditions.
- **17:00** — Weather clears to VFR. Full operations resume.
- **21:13** — DAL859 go-around, even in VFR — likely pilot fatigue or residual turbulence.
- Capacity holds continue through evening as **712 total capacity events** occurred. Average hold time of 124 min means many flights land 2+ hours late.

---

## Risk Assessment

### High Risk — Simultaneous Dual Runway Closure (09:00-12:00)

The 3-hour window where both 28L and 28R are closed is the single most dangerous period. With zero runway capacity:
- Airborne aircraft must divert (fuel critical after extended holding)
- Ground-stopped aircraft block gates, preventing new arrivals from parking
- De-icing fluid supply may run low after 7+ hours of continuous use

**Mitigation:** Stagger snow removal to **never close both runways simultaneously**. Accept reduced capacity on one runway during clearing of the other.

### High Risk — Extended De-Icing Requirement

12 hours of mandatory de-icing (05:00-17:00) means:
- Turnaround times increase by ~20 min per aircraft
- De-icing fluid consumption: ~150,000 gallons estimated for 895 departures
- De-icing pad congestion creates secondary delays

**Mitigation:** Pre-stage 200,000+ gallons of Type I/IV fluid. Deploy mobile de-icing units to gates for widebody aircraft. Implement holdover time monitoring.

### Medium Risk — Gate Failures During Peak

Two gates out of service (T4-B8 for 6h, T1-A3 for 4h) during the storm peak when turnarounds are already extended creates a gate shortage cascade. With 20 gates at max utilization, losing 10% of capacity is critical.

**Mitigation:** Pre-assign hardstand positions as overflow. Keep tow tractors available for remote parking. Prioritize gate allocation for connecting pax.

### Medium Risk — Taxiway Closure

Taxiway A closure for 5 hours forces all ground traffic onto secondary taxiways, increasing taxi times by 10-15 min and creating ground congestion near active runways.

**Mitigation:** Publish revised taxi routes pre-storm. Station ground controllers at key intersections. Implement departure queue management from gates.

---

## Recommendations for Airport Preparedness

1. **Pre-storm cancellation trigger:** When forecast shows >4h of LIFR + snow, cancel 15-20% of flights 12h in advance. The simulation's 12.3% cancellation rate was reactive — proactive cancellation would reduce passenger impact.

2. **Staggered snow removal protocol:** Never close both runways simultaneously. Accept 50% capacity on one runway while clearing the other. The 3h dual closure caused the worst cascading delays.

3. **Ground stop timing:** Declare ground stop **before** both runways close, not after. The 11:00 ground stop was 2 hours too late — flights were already holding with critical fuel.

4. **De-icing supply chain:** Maintain 48-hour supply of de-icing fluid for worst-case scenarios. Current simulation shows 12h continuous de-icing requirement.

5. **Gate contingency:** Identify 4-6 hardstand positions pre-storm that can serve as overflow gates with bus service. Two gate failures during peak is a realistic scenario.

6. **Communication plan:** Establish 30-min ops briefing cadence during storm. Keep airlines informed of expected re-opening times to help rebooking decisions.

---

## Conclusion

The JFK Nor'easter simulation demonstrates that a severe winter storm can reduce on-time performance to 23% and create cascading delays lasting well beyond the weather event. The most critical finding is that **simultaneous dual runway closure** must be prevented through staggered snow removal. Pre-emptive cancellations and early ground stops — before conditions deteriorate — are far more effective than reactive measures. Airports in the US Northeast corridor should conduct this type of what-if analysis annually before winter season to validate their snow removal capacity and de-icing supply chain.
