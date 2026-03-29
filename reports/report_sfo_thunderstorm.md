# What-If Scenario Report: SFO Summer Thunderstorm + Cascading Disruptions

**Airport:** San Francisco International Airport (KSFO)
**Scenario:** Summer Thunderstorm + Cascading Disruptions
**Simulation Date:** 2026-03-15 (24-hour simulation)
**Total Scheduled Flights:** 1,030 (523 arrivals / 507 departures)
**Report Generated:** 2026-03-29

---

## Executive Summary

This simulation models a rare summer thunderstorm at SFO followed by severe evening fog — a cascading disruption pattern that tests the limits of airport resilience. SFO, already constrained by its closely-spaced parallel runways (28L/28R), is uniquely vulnerable to weather events that reduce approach minimums. The simulation produces the **worst on-time performance of all three scenarios at 18.1%**, with **122 flights unable to spawn** (11.8% effective cancellation rate), **101 proactive cancellations**, **4 diversions** to OAK/SJC, and a staggering **798 capacity hold events**.

**Key Finding:** The "cascading" nature of this scenario — thunderstorm at 14:00, FOD closure at 10:30, fuel shortage at 15:00, then severe fog at 18:00 — means the airport **never fully recovers** from each event before the next hits. This continuous degradation is far more damaging than a single severe event because crew duty times expire, gate occupancy remains at 100%, and the departure backlog compounds with each new disruption.

---

## Weather Timeline

| Time (UTC) | Condition | Visibility | Ceiling | Gusts | Flight Rules |
|---|---|---|---|---|---|
| 00:00-14:00 | Clear/Normal | 10+ nm | 5,000+ ft | Calm | VFR |
| **14:00-16:30** | **Moderate thunderstorm** | **1.5 nm** | **800 ft** | **35 kt** | **IFR** |
| 16:30-18:00 | Post-storm clearing | Improving | Improving | Decreasing | MVFR |
| **18:00-21:00** | **Severe fog** | **0.5 nm** | **200 ft** | — | **LIFR** |
| 21:00-24:00 | Clear | 10.0 nm | 5,000 ft | Calm | VFR |

---

## Operational Impact Summary

| Metric | Value | Assessment |
|---|---|---|
| On-time Performance | **18.1%** | Critical — worst of all scenarios |
| Avg Schedule Delay | 50.3 min | Severe — system-wide disruption |
| Avg Capacity Hold | 93.9 min | Extended holding patterns |
| Max Capacity Hold | 336.0 min | **5.6 hours** — extreme |
| Go-Arounds | 3 | One in VFR (unusual — indicates congestion) |
| Diversions | 4 (to OAK and SJC) | Bay Area alternates absorb overflow |
| Cancellations | 101 (9.8%) | Plus 122 not spawned = 21.7% total |
| Not Spawned | 122 (11.8%) | Flights never entered system |
| Avg Delay (Not Spawned) | 88.7 min | These would have been very late |
| Peak Simultaneous Flights | 216 | Highest of all three scenarios |
| Gate Utilization | 20 gates | Saturated throughout |

---

## Critical Events Timeline

### Phase 1: Normal Operations with Early Warning (00:00-09:00 UTC)

- Operations normal through early morning.
- **06:54** — First capacity events appear: UAL475, SWA2511, SWA323 held on departure. This is early — SFO's close runway spacing means departure capacity is constrained even in good weather.
- Departure holds continue through morning, accumulating 798 total capacity events.

**Operator Action Required:** Monitor afternoon thunderstorm forecast. SFO's IFR approach rate drops from 60/hr to ~30/hr — pre-plan afternoon schedule thinning.

### Phase 2: FOD Closure + Diversions (10:00-14:00 UTC)

The cascading disruption sequence begins:

- **10:30** — **Runway 28R closed for 45 minutes** due to Foreign Object Debris (FOD). This is the first non-weather disruption.
  - Simultaneously, **4 flights diverted:**
    - AAL1095 → OAK (Oakland)
    - AI2648 → SJC (San Jose)
    - UAL1416 → OAK
    - AAL2256 → OAK
  - With only 28L available, arrival rate drops to ~25/hr.
- **11:15** — 28R re-opens, but the backlog is established.
- **11:32** — UAL2824 go-around in VFR conditions. This is unusual and indicates severe sequencing congestion — the runway isn't available when the aircraft is on final.

**Operator Action Required:** Activate FOD inspection protocol immediately. With afternoon thunderstorm approaching, the runway closure timing is critical — every minute of 28R downtime adds to the pre-storm backlog.

### Phase 3: Thunderstorm + Fuel Shortage (14:00-18:00 UTC)

The main weather event arrives while the airport is still recovering from the FOD closure:

- **14:00** — Moderate thunderstorm: 1.5 nm visibility, 800 ft ceiling, 35 kt gusts. IFR conditions.
  - Approach rate drops to single-runway IFR (~25/hr).
  - **101 flights proactively cancelled.** Major carriers UAL, SWA, ASA make bulk cancellation decisions.
- **15:00** — **Fuel shortage begins.** 3-hour disruption to fuel supply.
  - Aircraft at gates cannot depart → gates blocked → arrivals hold on taxiway → cascade.
  - This is the worst-case compound: weather reducing arrivals + fuel reducing departures = total gridlock.
- **16:00** — **Runway configuration change:** 28L/28R wind shift requires runway change. This interrupts the flow during the most congested period, adding ~15 min of zero-capacity transition time.

**Operator Action Required:** Declare ground delay program at 13:00 (1 hour before storm). Prioritize fuel for connection-critical flights. Implement gate juggling — tow unfueled aircraft to remote stands. Coordinate with TRACON for miles-in-trail spacing adjustment.

### Phase 4: Severe Fog — The Second Wave (18:00-21:00 UTC)

Just as thunderstorm conditions clear, **severe fog** rolls in — the classic SFO evening marine layer, but exceptionally dense:

- **18:00** — Severe fog: 0.5 nm visibility, 200 ft ceiling. **LIFR conditions.**
  - This is the knockout blow. The airport was beginning to recover, and now approaches are restricted to CAT III ILS only.
  - With 216 peak simultaneous flights and gates fully saturated, there's nowhere to put arriving aircraft.
- **20:41** — UAL1045 go-around in LIFR conditions. High-risk approach failure.
- **21:00** — Fog begins to lift. VFR conditions by 21:00.
- **21:09** — ASA291 go-around even as conditions improve — residual congestion.

**Operator Action Required:** This is the point where mass cancellations for remaining evening flights should be considered. With 93.9 min average hold and fog reducing arrival rate to <15/hr, many flights will exceed crew duty limits. Cancelling 30-40 more flights at 18:00 would reduce passenger misery vs. making them wait 3+ more hours.

### Phase 5: Late Recovery (21:00-24:00 UTC)

- Conditions clear but damage is done.
- Many late-evening flights cancelled or delayed beyond useful arrival time.
- Gate turnover remains slow due to depleted ground crews working overtime.
- System doesn't fully recover by midnight.

---

## Risk Assessment

### Critical Risk — Cascading Multi-Event Disruption

SFO's scenario is uniquely dangerous because **four separate events** compound over 12 hours:
1. FOD closure (10:30) — creates initial backlog
2. Thunderstorm (14:00) — degrades arrival capacity
3. Fuel shortage (15:00) — blocks departures
4. Severe fog (18:00) — destroys remaining capacity

No single event is catastrophic, but the sequence prevents recovery between events. This is the most realistic scenario — airports rarely face isolated disruptions.

**Mitigation:** Implement a "cumulative disruption score" that triggers escalating response levels. When two events overlap, automatically activate Level 2 (enhanced staffing + proactive cancellations). Three events: Level 3 (mass cancellations + diversion coordination).

### High Risk — 11.8% Not-Spawned Rate

122 flights (11.8%) were so delayed they never entered the simulation. In reality, these would be flights cancelled so late that passengers are already at the airport. Average delay for these flights was 88.7 min — meaning passengers waited 1.5 hours before being told their flight doesn't exist.

**Mitigation:** Move cancellation decisions earlier. If a flight will be delayed >90 min with high uncertainty, cancel it at T-60 min rather than T-15 min. This gives passengers time to rebook or go home.

### High Risk — Fuel Supply Chain

A 3-hour fuel shortage during a thunderstorm is a realistic scenario — fuel truck operations may halt during lightning, and pipeline delivery may be interrupted. At SFO, fuel comes via pipeline from the East Bay — a single point of failure.

**Mitigation:** Maintain 24-hour on-site fuel reserve. Establish emergency fuel barge delivery from Richmond refinery. During thunderstorm warnings, pre-stage additional fuel trucks at active gates.

### Medium Risk — VFR Go-Arounds

UAL2824's go-around in VFR conditions at 11:32 indicates the runway is congested beyond safe sequencing. This means the spacing between arrivals is too tight, and ATC is pushing throughput at the expense of safety margins.

**Mitigation:** When delay backlog exceeds 60 min average, accept reduced throughput (increase spacing to 6nm) rather than risk runway incursions or go-arounds.

---

## Diversion Analysis

| Flight | Airline | Diverted To | Time | Notes |
|---|---|---|---|---|
| AAL1095 | American | OAK | 10:30 | During FOD closure |
| AI2648 | Air India | SJC | 10:30 | International — passenger rebooking complex |
| UAL1416 | United | OAK | 10:30 | United hub — easier rebooking |
| AAL2256 | American | OAK | 10:30 | During FOD closure |

All diversions occurred during the FOD closure, not the thunderstorm — suggesting the FOD event was the initial trigger for capacity collapse. OAK and SJC are natural Bay Area alternates (15-30 min ground transfer), but cross-ticketing agreements must be in place.

---

## Comparison: SFO vs JFK vs DXB

| Metric | JFK (Storm) | DXB (Sand) | SFO (Thunder+Fog) |
|---|---|---|---|
| On-time % | 23.0% | 57.4% | **18.1%** |
| Cancellations | 125 | 68 | **223** (101+122) |
| Diversions | 0 | 7 | 4 |
| Go-Arounds | 5 | 3 | 3 |
| Max Hold (min) | 354 | 238 | 336 |
| Peak Flights | 208 | 164 | **216** |
| Scenario Type | Single severe | Single severe | **Cascading** |

SFO's cascading scenario produces the worst overall impact despite no single event being as severe as JFK's blizzard or DXB's sandstorm. The lesson: **multiple moderate events > one severe event** in terms of operational damage.

---

## Recommendations for Airport Preparedness

1. **Cascading disruption protocol:** Develop a formal "Compound Event Response Plan" that escalates automatically when 2+ disruptions overlap. Current single-event playbooks are insufficient.

2. **FOD prevention investment:** The 45-min FOD closure was the initial domino. Invest in continuous FOD detection systems (radar-based) for both runways. The ROI from preventing one FOD-triggered cascade pays for the system.

3. **Fuel supply redundancy:** SFO's single-pipeline fuel delivery is a critical vulnerability. Establish secondary supply via barge or truck convoy from Richmond. Pre-stage 12 additional fuel trucks during weather advisories.

4. **Earlier cancellation decisions:** Move from reactive to predictive cancellation. Use simulation-based decision support (this tool) to model afternoon disruptions at 06:00 and make cancellation decisions before passengers leave home.

5. **Bay Area diversion coordination:** Formalize SFO-OAK-SJC mutual aid agreement with guaranteed diversion slots and cross-ticketing. Pre-position ground transport (buses) at OAK for SFO diversions.

6. **Marine fog playbook:** SFO fog is predictable (satellite monitoring, marine buoy data). Implement automated fog alert at T-2 hours that triggers additional cancellations for the 18:00-22:00 window.

7. **Crew duty time management:** In cascading scenarios, crew duty limits become the binding constraint by hour 10. Pre-position reserve crews during weather advisories. Consider crew swaps at gates rather than waiting for next-day crew.

---

## Conclusion

The SFO thunderstorm + cascading disruptions simulation produces the most severe operational impact of all three scenarios tested, with only 18.1% on-time performance and an effective 21.7% cancellation rate. The key insight is that **cascading moderate events are more damaging than single severe events** because recovery never begins. Airports must develop compound-event response plans, invest in preventing initial triggering events (FOD detection), and accept earlier cancellation decisions to protect overall system performance. SFO's unique vulnerability to evening marine fog after afternoon weather events should be a standard planning consideration for Bay Area aviation stakeholders.
