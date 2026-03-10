# Airport Open Data Sources & Operational KPIs

A comprehensive reference cataloging free/open aviation data sources, mapping them to airport operational KPIs, and connecting those KPIs to the Digital Twin's ML models.

---

## Table of Contents

- [Part 1: Open Data Sources](#part-1-open-data-sources)
- [Part 2: Airport Operational KPIs](#part-2-airport-operational-kpis)
- [Part 3: Data Source → KPI → ML Model Mapping](#part-3-data-source--kpi--ml-model-mapping)

---

## Part 1: Open Data Sources

### 1. BTS On-Time Performance

| Field | Detail |
|-------|--------|
| **Provider** | Bureau of Transportation Statistics (US DOT) |
| **URL** | https://www.transtats.bts.gov/Tables.asp?QO_VQ=EFD |
| **Data Content** | Flight-level records: scheduled/actual departure and arrival times, taxi-out/taxi-in times, delay causes (carrier, weather, NAS, security, late aircraft), cancellations, diversions, distance, carrier, origin/destination airports |
| **Format** | CSV (downloadable), API (JSON) |
| **Update Frequency** | Monthly, ~2 months lag |
| **Coverage** | All US certificated carriers, domestic + international from US airports, 2003–present |
| **Access Method** | Bulk CSV download or `Transtats` lookup tables; no authentication required |
| **KPIs Enabled** | On-Time Performance, Average Delay, Delay Cause Distribution, Taxi Times, Cancellation Rate, Turnaround Time (derived) |

**Notes:** The single richest free source for US airport delay analytics. Each row represents one flight with 110+ columns. The `ONTIME` table is the most commonly used; the `T100` table provides market-level traffic volumes.

### 2. FAA OPSNET / ASPM

| Field | Detail |
|-------|--------|
| **Provider** | Federal Aviation Administration |
| **URL** | https://aspm.faa.gov/ |
| **Data Content** | Airport operations counts (arrivals, departures, overflights), hourly throughput rates, delay minutes, airport acceptance/departure rates, Ground Delay Programs (GDP), Ground Stops (GS) |
| **Format** | Web query interface → CSV/Excel export |
| **Update Frequency** | Daily (OPSNET), hourly granularity available (ASPM) |
| **Coverage** | 77 ASPM airports (major US), OPSNET covers all towered US airports (~500) |
| **Access Method** | Web interface at aspm.faa.gov; public access with registration (free) |
| **KPIs Enabled** | Runway Throughput, Airport Acceptance Rate, Hourly Operations Count, GDP/GS Frequency, NAS Delay Minutes |

**Notes:** ASPM (Aviation System Performance Metrics) provides the most granular operational data for US airports. OPSNET is the simpler operations-count database. Both are essential for capacity analysis.

### 3. Eurocontrol Performance Review

| Field | Detail |
|-------|--------|
| **Provider** | Eurocontrol Performance Review Commission |
| **URL** | https://ansperformance.eu/data/ |
| **Data Content** | Airport arrival/departure punctuality, ATFM (Air Traffic Flow Management) delays, taxi times, turnaround times, en-route charges, horizontal flight efficiency, airport capacity utilization |
| **Format** | CSV downloads, interactive dashboards, REST API |
| **Update Frequency** | Monthly summaries, annual reports |
| **Coverage** | 80+ European airports, ECAC member states, 2005–present |
| **Access Method** | Public download from ansperformance.eu; API access for bulk queries |
| **KPIs Enabled** | Arrival/Departure Punctuality, ATFM Delay per Flight, Additional Taxi-Out Time, Turnaround Time, Airport Throughput, Slot Adherence |

**Notes:** The European counterpart to BTS/ASPM. Provides standardized KPIs across European airports, making cross-continental benchmarking possible. The `Additional Taxi-Out Time` metric is particularly valuable as it isolates delay caused by congestion.

### 4. OpenSky Network

| Field | Detail |
|-------|--------|
| **Provider** | OpenSky Network (academic consortium) |
| **URL** | https://opensky-network.org/ |
| **Data Content** | ADS-B position reports (latitude, longitude, altitude, velocity, heading, vertical rate), aircraft metadata (ICAO24 address, callsign, origin country), flight tables (first/last seen, departure/arrival airports) |
| **Format** | REST API (JSON), Python API, Trino/Presto SQL interface, Parquet bulk downloads |
| **Update Frequency** | Real-time (1–5 second resolution for live data); historical archive from 2013 |
| **Coverage** | Global (receiver-dependent, best coverage in Europe and North America) |
| **Access Method** | Anonymous API (limited rate), registered users (higher rate), bulk historical via Trino |
| **KPIs Enabled** | Flight Trajectories, Actual Block Times, Taxi Path Analysis, Runway Utilization (derived), Airspace Congestion, Approach/Departure Path Efficiency |

**Notes:** The only free source of global ADS-B flight tracking data. Position resolution allows detailed trajectory analysis — taxi path reconstruction, runway occupancy timing, and holding pattern detection. Rate limits apply: anonymous users get 10 API calls/day for historical; registered users get more.

### 5. NOAA Aviation Weather

| Field | Detail |
|-------|--------|
| **Provider** | National Oceanic and Atmospheric Administration (NOAA) / Aviation Weather Center |
| **URL** | https://aviationweather.gov/ |
| **Data Content** | METAR observations (temperature, wind speed/direction/gusts, visibility, ceiling, precipitation, flight category), TAF forecasts (6–30 hour terminal forecasts), PIREPs (pilot reports), SIGMETs, AIRMETs |
| **Format** | Raw text (METAR/TAF coded), CSV, XML, JSON (TDS API) |
| **Update Frequency** | METAR: hourly (routine) + special observations; TAF: every 6 hours; PIREPs: as reported |
| **Coverage** | Global METARs (~10,000 stations); TAFs for ~900 US airports; historical archive via Iowa State (IEM) |
| **Access Method** | aviationweather.gov API (no auth), Iowa Environmental Mesonet for historical bulk (mesonet.agron.iastate.edu) |
| **KPIs Enabled** | Weather-Related Delay Correlation, Low Visibility Operations (LVO) Frequency, Wind Impact on Runway Configuration, Flight Category Distribution, Weather-Driven Cancellation Rate |

**Notes:** Critical for correlating weather conditions with operational performance. METAR data can be joined with BTS delay data by station (airport ICAO code) and timestamp. Iowa State's ASOS archive provides decades of historical METAR data in convenient CSV format.

### 6. FAA TFMS / ATCSCC Advisories

| Field | Detail |
|-------|--------|
| **Provider** | FAA Air Traffic Control System Command Center |
| **URL** | https://www.fly.faa.gov/adv/advAdvisoryAction.jsp |
| **Data Content** | Traffic Management Initiatives (TMIs): Ground Delay Programs (GDP parameters — average delay, max delay, scope), Ground Stops, Airspace Flow Programs (AFP), Miles-in-Trail restrictions, reroutes, airport configuration changes |
| **Format** | Text advisories (structured), XML feed |
| **Update Frequency** | Real-time (advisories issued as conditions change) |
| **Coverage** | All US NAS airports and airspace; most impactful for the ~35 OEP airports |
| **Access Method** | Public web interface; NASSTATUS XML feed |
| **KPIs Enabled** | GDP Frequency/Duration, Ground Stop Frequency, TMI Impact Hours, Demand-Capacity Imbalance, Strategic Delay Minutes |

**Notes:** Provides the "why" behind NAS delays. When a GDP is issued, this data source captures the program parameters (start/end time, average delay, scope). Essential for training ML models to predict system-wide delay propagation.

### 7. OurAirports

| Field | Detail |
|-------|--------|
| **Provider** | OurAirports community (David Megginson) |
| **URL** | https://ourairports.com/data/ |
| **Data Content** | Airport master records (name, ICAO/IATA codes, lat/lon, elevation, type), runway records (length, width, surface, ILS availability, threshold coordinates), frequency records, navigation aids, country/region reference |
| **Format** | CSV (direct download) |
| **Update Frequency** | Community-maintained, updated frequently |
| **Coverage** | 74,000+ airports/heliports/seaplane bases worldwide |
| **Access Method** | Direct CSV download from ourairports.com/data/ — no authentication |
| **KPIs Enabled** | Airport Reference Data (enrichment), Runway Configuration Analysis, Airport Classification, Infrastructure Capacity Baseline |

**Notes:** The go-to free source for global airport/runway reference data. Complements OSM by providing structured runway dimensions, surface types, and ILS capability. The `airports.csv` and `runways.csv` files are the most useful.

### 8. Eurostat Air Transport Statistics

| Field | Detail |
|-------|--------|
| **Provider** | European Commission (Eurostat) |
| **URL** | https://ec.europa.eu/eurostat/web/transport/overview |
| **Data Content** | Annual/quarterly passenger counts (by airport pair), freight/mail tonnage, aircraft movements, load factors, top routes, national/international breakdown |
| **Format** | TSV/CSV via bulk download, JSON via REST API |
| **Update Frequency** | Quarterly, ~6 months lag |
| **Coverage** | All EU/EEA/CH airports with >15,000 passengers/year |
| **Access Method** | Eurostat data browser (free), REST API with dataset codes (e.g., `avia_tf_apal` for passengers) |
| **KPIs Enabled** | Annual Passenger Volume, Freight Throughput, Aircraft Movement Trends, Load Factor, Route Demand, Seasonal Patterns |

**Notes:** Best source for European airport traffic volumes at the aggregate level. Less operationally granular than BTS/Eurocontrol but essential for demand forecasting, seasonal pattern analysis, and capacity planning.

---

## Part 2: Airport Operational KPIs

### Domain 1: Airside Operations

#### 1.1 Runway Throughput (Operations per Hour)

| Field | Detail |
|-------|--------|
| **Definition** | Number of aircraft arrivals and departures per runway per hour |
| **Formula** | `Ops/hr = (arrivals + departures) / hours_of_operation` |
| **Target Values** | Single runway: 30–40 ops/hr; Dual parallel: 60–75 ops/hr; Major hubs (e.g., ATL): 90+ ops/hr |
| **Operational Significance** | The fundamental capacity constraint. When demand exceeds throughput, delays cascade. Drives investment decisions for new runways. |
| **Data Source** | FAA OPSNET/ASPM (primary), OpenSky Network (derived from ADS-B) |
| **ML Model Benefit** | **Congestion Model** — peak throughput vs. demand ratio is the strongest predictor of congestion levels |

#### 1.2 Taxi-Out Time

| Field | Detail |
|-------|--------|
| **Definition** | Time from gate pushback to wheels-off (takeoff) |
| **Formula** | `Taxi_Out = Wheels_Off_Time - Gate_Departure_Time` |
| **Target Values** | Uncongested: 10–15 min; Moderate: 15–25 min; Congested (JFK/EWR): 25–40 min |
| **Operational Significance** | Excess taxi time = fuel burn + emissions + delay propagation. Airports track "additional taxi-out time" (above unimpeded) as a congestion proxy. |
| **Data Source** | BTS On-Time Performance (reported per flight), Eurocontrol (European airports) |
| **ML Model Benefit** | **Delay Model** — taxi-out time is a strong feature for predicting departure delays and identifying ground congestion |

#### 1.3 Taxi-In Time

| Field | Detail |
|-------|--------|
| **Definition** | Time from wheels-on (landing) to gate arrival |
| **Formula** | `Taxi_In = Gate_Arrival_Time - Wheels_On_Time` |
| **Target Values** | Typical: 5–10 min; Large airports: 10–20 min |
| **Operational Significance** | Reflects ramp/taxiway congestion and gate availability. Long taxi-in times often indicate gate conflicts. |
| **Data Source** | BTS On-Time Performance, Eurocontrol |
| **ML Model Benefit** | **Gate Model** — high taxi-in times correlate with gate unavailability, informing gate assignment optimization |

#### 1.4 Turnaround Time

| Field | Detail |
|-------|--------|
| **Definition** | Time an aircraft spends at the gate between arrival and next departure |
| **Formula** | `Turnaround = Next_Departure_Gate_Time - Arrival_Gate_Time` |
| **Target Values** | Narrow-body (domestic): 30–45 min; Wide-body (international): 90–180 min; LCC quick-turn: 25 min |
| **Operational Significance** | Determines gate capacity and airline scheduling efficiency. Shorter turnarounds = more flights per gate per day. |
| **Data Source** | BTS (derived from consecutive flights on same tail number), Eurocontrol |
| **ML Model Benefit** | **Gate Model** — turnaround time prediction is essential for optimizing gate assignments and predicting gate availability |

### Domain 2: Punctuality & Delays

#### 2.1 On-Time Performance (OTP)

| Field | Detail |
|-------|--------|
| **Definition** | Percentage of flights arriving/departing within 15 minutes of schedule (A15 standard) |
| **Formula** | `OTP = flights_within_15min / total_flights × 100` |
| **Target Values** | Excellent: >85%; Good: 75–85%; Poor: <70%; US average (2023): ~78% |
| **Operational Significance** | The single most-watched aviation KPI. Airlines are ranked by OTP; airports use it for benchmarking. Passenger satisfaction correlates strongly with OTP. |
| **Data Source** | BTS On-Time Performance (US), Eurocontrol (EU), airline reporting |
| **ML Model Benefit** | **Delay Model** — OTP prediction is the primary output; historical OTP patterns (by hour, day-of-week, season) are key features |

#### 2.2 Average Delay (Minutes)

| Field | Detail |
|-------|--------|
| **Definition** | Mean minutes of delay across all delayed flights (or all flights including on-time) |
| **Formula** | `Avg_Delay = Σ(actual - scheduled) / count` for delayed flights; or include zeros for all flights |
| **Target Values** | All flights: <10 min avg; Delayed flights only: <45 min avg |
| **Operational Significance** | More granular than OTP — captures severity. An airport can have 80% OTP but 90-minute average delays on the remaining 20%. |
| **Data Source** | BTS On-Time Performance, Eurocontrol |
| **ML Model Benefit** | **Delay Model** — average delay by time-of-day and airport is a primary prediction target |

#### 2.3 Delay Cause Distribution

| Field | Detail |
|-------|--------|
| **Definition** | Breakdown of total delay minutes by cause category |
| **Formula** | BTS categories: `Carrier Delay + Weather Delay + NAS Delay + Security Delay + Late Aircraft Delay = Total Delay` |
| **Target Values** | Varies by airport; weather-dominated airports (SFO fog, ORD winter) differ from capacity-constrained (EWR) |
| **Operational Significance** | Identifies actionable vs. uncontrollable delays. Carrier delays → airline ops improvements; NAS delays → ATM system improvements; weather → infrastructure investment (ILS upgrades). |
| **Data Source** | BTS On-Time Performance (5-category breakdown per flight) |
| **ML Model Benefit** | **Delay Model** — cause-specific delay predictions enable more targeted operational responses |

#### 2.4 Delay Propagation (Reactionary Delay)

| Field | Detail |
|-------|--------|
| **Definition** | Delays caused by the late arrival of a preceding flight (also called "knock-on" or "reactionary" delay) |
| **Formula** | `Propagated_Delay = Late_Aircraft_Delay / Total_Delay × 100` |
| **Target Values** | Typically 30–40% of all delays are propagated; airlines target <30% |
| **Operational Significance** | The cascading effect — one late flight causes downstream delays across the network. Understanding propagation paths is key to breaking delay chains. |
| **Data Source** | BTS (Late Aircraft Delay category), Eurocontrol (reactionary delay metrics) |
| **ML Model Benefit** | **Delay Model** — incorporating upstream flight delays (same tail number) dramatically improves prediction accuracy |

### Domain 3: Capacity & Congestion

#### 3.1 Peak Hour Utilization

| Field | Detail |
|-------|--------|
| **Definition** | Ratio of actual operations to declared capacity during the busiest hour |
| **Formula** | `Utilization = Peak_Hour_Ops / Declared_Capacity × 100` |
| **Target Values** | <80%: adequate reserve; 80–95%: efficient but fragile; >95%: over-scheduled, delays likely |
| **Operational Significance** | Airports operating near capacity have no buffer for disruptions. Even minor weather events cause cascading delays. |
| **Data Source** | FAA ASPM (hourly ops counts), Eurocontrol (declared capacity vs. actual) |
| **ML Model Benefit** | **Congestion Model** — utilization ratio is the primary feature for predicting congestion levels |

#### 3.2 Gate Occupancy Rate

| Field | Detail |
|-------|--------|
| **Definition** | Percentage of gate-hours occupied vs. available across a time period |
| **Formula** | `Gate_Occupancy = Σ(turnaround_hours) / (num_gates × operating_hours) × 100` |
| **Target Values** | Efficient: 65–75%; Congested: >80%; Under-utilized: <50% |
| **Operational Significance** | High gate occupancy forces aircraft to hold on taxiways (increasing taxi-in times) or use remote stands (degrading passenger experience). |
| **Data Source** | Derived from BTS (tail-number tracking), airport AODB (not public), OpenSky (gate time estimation) |
| **ML Model Benefit** | **Gate Model** — gate occupancy forecasts drive the gate recommendation engine; **Congestion Model** — gate saturation contributes to overall congestion |

#### 3.3 Demand-Capacity Balance

| Field | Detail |
|-------|--------|
| **Definition** | Comparison of scheduled flight demand to airport/airspace capacity at each hour |
| **Formula** | `DCB_Ratio = Scheduled_Demand / Available_Capacity` |
| **Target Values** | <1.0: under-demand; 1.0–1.1: balanced; >1.1: over-demand (TMIs likely) |
| **Operational Significance** | The root cause of most NAS delays. When DCB > 1.0, the FAA issues Ground Delay Programs or Ground Stops. Predictive DCB analysis enables proactive flow management. |
| **Data Source** | FAA ASPM (demand and capacity), FAA TFMS (TMI issuances when imbalanced) |
| **ML Model Benefit** | **Congestion Model** — DCB ratio is the theoretical foundation; **Delay Model** — GDP/GS predictions depend on DCB forecasting |

### Domain 4: Safety & Weather Impact

#### 4.1 Weather-Related Delay Rate

| Field | Detail |
|-------|--------|
| **Definition** | Percentage of total delay minutes attributable to weather |
| **Formula** | `Weather_Delay_Rate = Weather_Delay_Minutes / Total_Delay_Minutes × 100` |
| **Target Values** | National average: ~25–35% of delays are weather-related; varies significantly by season and airport |
| **Operational Significance** | Weather is the largest single cause of NAS delays. Tracking this KPI by airport reveals infrastructure needs (e.g., airports with high fog-delay rates benefit from CAT III ILS). |
| **Data Source** | BTS (Weather Delay category), NOAA Aviation Weather (METAR correlation), FAA TFMS (weather-related TMIs) |
| **ML Model Benefit** | **Delay Model** — weather features (ceiling, visibility, wind, precipitation) from METAR data are among the strongest delay predictors |

#### 4.2 Diversion Rate

| Field | Detail |
|-------|--------|
| **Definition** | Percentage of flights diverted to an alternate airport |
| **Formula** | `Diversion_Rate = Diverted_Flights / Total_Scheduled_Flights × 100` |
| **Target Values** | Normal: <0.5%; Severe weather event: 2–5%; Airport closure: up to 100% of arrivals |
| **Operational Significance** | Diversions are operationally expensive (fuel, crew disruption, passenger impact) and indicate severe conditions. Airports with high diversion rates may need infrastructure improvements. |
| **Data Source** | BTS On-Time Performance (DIVERTED flag), OpenSky Network (trajectory analysis) |
| **ML Model Benefit** | **Delay Model** — diversion prediction as an extreme delay outcome; historical diversion patterns improve severe-weather delay modeling |

#### 4.3 Low Visibility Operations (LVO) Frequency

| Field | Detail |
|-------|--------|
| **Definition** | Hours per year an airport operates under low-visibility conditions (CAT II/III) |
| **Formula** | `LVO_Hours = Σ hours where visibility < 550m OR ceiling < 200ft` |
| **Target Values** | Clear airports (PHX): <50 hrs/yr; Fog-prone (SFO): 200+ hrs/yr; Severe (LHR winter): 100+ hrs/yr |
| **Operational Significance** | LVO reduces runway throughput by 30–50%. Airports invest in CAT III ILS and SMGCS to maintain operations. LVO frequency directly impacts annual delay budgets. |
| **Data Source** | NOAA Aviation Weather (METAR visibility and ceiling data) |
| **ML Model Benefit** | **Congestion Model** — LVO conditions trigger reduced runway acceptance rates; **Delay Model** — visibility thresholds are key features |

### Domain 5: Passenger Experience

#### 5.1 Minimum Connection Time (MCT) Reliability

| Field | Detail |
|-------|--------|
| **Definition** | Percentage of connecting passengers who make their connection given scheduled MCT |
| **Formula** | `MCT_Reliability = Successful_Connections / Total_Connections × 100` |
| **Target Values** | Target: >95% connection success; Airlines track "misconnect rate" (inverse) |
| **Operational Significance** | Missed connections are the most passenger-visible failure. Airlines set MCT (typically 45–90 min for domestic, 90–180 min for international) based on airport layout and historical performance. |
| **Data Source** | Derived from BTS (connecting flight pairs by tail number or ticket coupon), airline internal data |
| **ML Model Benefit** | **Delay Model** — connection risk prediction enables proactive gate reassignment; **Gate Model** — proximity-based gate assignment for tight connections |

#### 5.2 Baggage Delivery Time

| Field | Detail |
|-------|--------|
| **Definition** | Time from aircraft arrival at gate to last bag delivered at baggage claim |
| **Formula** | `Bag_Delivery = Last_Bag_On_Carousel - Aircraft_Gate_Arrival` |
| **Target Values** | Domestic: <20 min; International: <30 min; IATA target: first bag within 15 min |
| **Operational Significance** | Directly impacts passenger satisfaction scores. Long baggage times indicate ramp staffing issues, belt system capacity problems, or terminal design constraints. |
| **Data Source** | Not available in public data (airport AODB/BHS systems); can be estimated from turnaround analytics |
| **ML Model Benefit** | **Gate Model** — terminal/gate assignment affects baggage routing distance; useful as a future model enhancement |

#### 5.3 Cancellation Rate

| Field | Detail |
|-------|--------|
| **Definition** | Percentage of scheduled flights cancelled |
| **Formula** | `Cancellation_Rate = Cancelled_Flights / Total_Scheduled_Flights × 100` |
| **Target Values** | Normal: <2%; Bad weather day: 5–15%; Major disruption (blizzard): 30–50% |
| **Operational Significance** | Cancellations are the worst outcome for passengers. They indicate either severe weather, airline operational failures, or ATC constraints. Patterns reveal systemic vulnerabilities. |
| **Data Source** | BTS On-Time Performance (CANCELLED flag + cancellation code: A=carrier, B=weather, C=NAS, D=security) |
| **ML Model Benefit** | **Delay Model** — cancellation prediction as a binary classification task; cancellation probability informs passenger rebooking recommendations |

---

## Part 3: Data Source → KPI → ML Model Mapping

### Cross-Reference Matrix

| Data Source | Airside Operations | Punctuality & Delays | Capacity & Congestion | Safety & Weather | Passenger Experience | ML Models |
|---|---|---|---|---|---|---|
| **BTS On-Time** | Taxi-Out/In, Turnaround (derived) | OTP, Avg Delay, Delay Causes, Propagation | Gate Occupancy (derived) | Weather Delay Rate, Diversions | MCT Reliability (derived), Cancellation Rate | Delay, Gate, Congestion |
| **FAA OPSNET/ASPM** | Runway Throughput | — | Peak Utilization, DCB | — | — | Congestion |
| **Eurocontrol** | Taxi Times, Turnaround, Throughput | OTP, ATFM Delay | Utilization, DCB | Weather Delay Rate | — | Delay, Congestion |
| **OpenSky Network** | Runway Utilization (derived) | Block Times (derived) | Airspace Congestion | — | — | Delay, Congestion |
| **NOAA Weather** | — | — | — | Weather Delay Correlation, LVO, Wind Impact | — | Delay, Congestion |
| **FAA TFMS** | — | — | DCB, TMI Impact | TMI Weather Triggers | — | Delay, Congestion |
| **OurAirports** | Runway Config Reference | — | Infrastructure Baseline | — | — | (enrichment) |
| **Eurostat** | — | — | Demand Trends | — | Seasonal Patterns | Congestion |

### ML Model Input Summary

#### Delay Prediction Model (`src/ml/delay_model.py`)

| Priority | Data Source | Features |
|----------|-------------|----------|
| **P0** | BTS On-Time | Historical OTP, delay causes, taxi times, late aircraft delay |
| **P0** | NOAA Weather | METAR conditions (ceiling, visibility, wind, precipitation) at origin/destination |
| **P1** | FAA TFMS | Active GDP/GS, TMI parameters (avg delay, scope) |
| **P1** | OpenSky | Real-time inbound flight positions, estimated arrival times |
| **P2** | Eurocontrol | European airport delay data for international flights |

#### Gate Recommendation Model (`src/ml/gate_model.py`)

| Priority | Data Source | Features |
|----------|-------------|----------|
| **P0** | BTS On-Time | Turnaround times by aircraft type, gate-level arrival/departure patterns |
| **P1** | OurAirports | Runway/gate reference data for airport topology |
| **P1** | OpenSky | Real-time taxi positions for gate availability estimation |
| **P2** | Eurocontrol | European turnaround time benchmarks |

#### Congestion Prediction Model (`src/ml/congestion_model.py`)

| Priority | Data Source | Features |
|----------|-------------|----------|
| **P0** | FAA ASPM | Hourly operations count, runway throughput, acceptance rate |
| **P0** | NOAA Weather | Weather conditions affecting capacity (LVO, wind, storms) |
| **P1** | BTS On-Time | Demand patterns (scheduled flights per hour), taxi time trends |
| **P1** | FAA TFMS | GDP/GS issuances as congestion indicators |
| **P2** | Eurostat | Seasonal demand trends for capacity planning |
| **P2** | OpenSky | Real-time airspace density, holding pattern detection |

### Recommended Ingestion Priority

Based on data richness, accessibility, and KPI coverage:

| Priority | Source | Rationale |
|----------|--------|-----------|
| 1 | **BTS On-Time Performance** | Richest single source — covers delays, taxi times, cancellations for all US flights |
| 2 | **NOAA Aviation Weather** | Weather is the #1 delay driver; METAR data enables the strongest ML features |
| 3 | **OurAirports** | Small static dataset that enriches all other sources with airport/runway metadata |
| 4 | **FAA OPSNET/ASPM** | Operational throughput data fills the capacity/congestion gap BTS doesn't cover |
| 5 | **OpenSky Network** | Real-time trajectory data enables live features but has rate limits |
| 6 | **FAA TFMS** | TMI data adds strategic delay context but requires parsing advisory text |
| 7 | **Eurocontrol** | Extends coverage to European airports; essential for international scope |
| 8 | **Eurostat** | Aggregate traffic statistics for long-term demand forecasting |
