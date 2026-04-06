# Simulation Data vs OpenSky Recorded Data — Gap Analysis for OBT Training

**Status:** Backlog
**Date added:** 2026-04-06
**Scope:** Analysis + actionable recommendations for closing data gaps

---

## Data Shape Comparison

| Field | Simulation | Recorded (OpenSky) | Gap |
|-------|-----------|-------------------|-----|
| **Schedule** | | | |
| `flight_number` | Generated (e.g. UAL1234) | From callsign (e.g. UAL397) | OK — real callsigns |
| `airline_code` | From callsign prefix | From callsign prefix | OK |
| `origin` / `destination` | Generated from profiles | Cascading: OpenSky API → heading heuristic → hash | Partial — Level 2/3 are approximate |
| `aircraft_type` | Selected from fleet mix | From Delta table (if ingested) | Often empty/missing |
| `scheduled_time` | Generated with calendar | Derived from first observation | Not real schedule — it's actual time, not scheduled |
| `delay_minutes` | Generated from BTS stats | Always 0 | Missing — no delay data |
| `delay_code` / `delay_reason` | Generated | Missing entirely | Missing |
| **Phase Transitions** | | | |
| `time`, `icao24`, `from_phase`, `to_phase` | From simulation engine | Inferred by OpenSkyEventInferrer | OK — phases are inferred from alt/vrate |
| `callsign`, `aircraft_type` | Populated | Populated | OK |
| **Gate Events** | | | |
| `time`, `icao24`, `gate`, `event_type` | From simulation gate assignment | Inferred from proximity to OSM gates | OK — but can miss distant/obscured gates |
| **Weather** | | | |
| `weather_snapshots` | Recorded every minute (wind, visibility, etc.) | Completely missing | Critical gap |
| **Scenario Events** | | | |
| `scenario_events` | Ground stops, capacity changes, weather events | Always `[]` (empty) | Missing — no ops events |
| **Config** | | | |
| `scenario_file` | Path to scenario file | `None` | Used for `is_weather_scenario` feature |

## OBT Feature Requirements vs Recorded Data Availability

The OBT model (`obt_features.py:extract_training_data`) needs these features:

| OBT Feature | Source | Sim | Recorded | Status |
|-------------|--------|-----|----------|--------|
| `aircraft_category` | aircraft_type → classify | Available | Sparse — often empty | Fixable via icao24→type lookup |
| `airline_code` | Schedule or callsign[:3] | Available | Available | OK |
| `hour_of_day` | parked transition time | Available | Available (inferred) | OK |
| `is_international` | origin/dest country comparison | Available | Partial — origin accuracy ~60-70% | Weak for Level 2/3 origins |
| `arrival_delay_min` | Schedule delay_minutes | Available | Always 0 | Critical gap |
| `gate_id_prefix` | Gate assignment | Available | Available (inferred) | OK — proximity-based |
| `is_remote_stand` | Gate ID pattern | Available | Available | OK |
| `concurrent_gate_ops` | Gate events count | Available | Available | OK |
| `wind_speed_kt` | weather_snapshots | Available | Missing | Critical gap |
| `visibility_sm` | weather_snapshots | Available | Missing | Critical gap |
| `has_active_ground_stop` | scenario_events | Available | Missing | Gap (defaults to false) |
| `scheduled_departure_hour` | Schedule | Available | Derived (actual, not scheduled) | Biased |
| `day_of_week` | Timestamp | Available | Available | OK |
| `hour_sin`/`hour_cos` | Hour cyclical | Available | Available | OK |
| `is_weather_scenario` | Config | Available | Always false | OK (correct) |
| `scheduled_buffer_min` | scheduled_dep - actual_arr | Available | Missing (no real schedule) | Critical gap |
| `is_hub_connecting` | Airline + airport | Available | Available | OK |
| **Target: `turnaround_min`** | parked→pushback duration | Available | Available (inferred) | OK — key metric is derivable |

## Critical Gaps (5 Blockers for OBT Training)

1. **No weather data** — `wind_speed_kt` and `visibility_sm` are critical features. Recorded data has zero weather context.
2. **No delay data** — `arrival_delay_min` is always 0 and `scheduled_buffer_min` can't be computed because there's no real schedule (only observed times).
3. **No real schedule** — `scheduled_time` is set to actual observed time, not the published schedule. Without SOBT/SIBT, you can't compute delay or buffer.
4. **Sparse aircraft type** — `aircraft_type` is often empty in the recorded Delta table, making `aircraft_category` unreliable.
5. **No scenario events** — ground stops, flow control directives are invisible in ADS-B data.

## Recommendations

### Quick Wins (can do now)

1. **Add METAR weather injection** — Fetch historical METAR data for the airport+date when loading a recording. The `/api/weather` endpoint already fetches live METAR. Store weather snapshots alongside recorded data. This fills the `wind_speed_kt` and `visibility_sm` gaps.

2. **Aircraft type enrichment** — Use the OpenSky aircraft database (or a local CSV mapping icao24→aircraft type) to populate `aircraft_type` when it's missing from the recording. Many open databases map icao24 transponder codes to airframe types.

3. **Add `weather_snapshots` to recorded output** — Modify `get_recording_data()` to fetch historical METAR for the recording date and include it in the response, matching the simulation format.

### Medium Effort (high impact)

4. **Real schedule integration** — Source published flight schedules from FlightAware, OAG, or Cirium. Map callsigns to scheduled times. This unlocks `delay_minutes`, `scheduled_buffer_min`, and `scheduled_departure_hour` (real, not actual).

5. **Hybrid training pipeline** — Train OBT model on simulation data (complete features) but fine-tune/validate on recorded data (partial features). Use a two-stage approach:
   - Stage 1: Train base model on sim data with all features
   - Stage 2: Fine-tune on recorded data using only the features that are available (drop weather/delay features, or impute from METAR)

6. **Feature-aware training mode** — Add an `extract_training_data_from_recording()` function in `obt_features.py` that:
   - Accepts the recorded JSON format (with enrichment)
   - Fetches historical METAR to fill weather
   - Sets `arrival_delay_min = 0` and `is_weather_scenario = False` (known defaults)
   - Marks samples as `source=recorded` for domain adaptation

### Longer Term

7. **Ground stop detection from ADS-B** — Infer ground stops by detecting patterns: many aircraft holding on taxiways simultaneously, no departures for extended periods while arrivals continue.

8. **Schedule estimation** — When no published schedule is available, estimate `scheduled_time` from historical patterns: for a given airline+route, the typical scheduled time is the median observed time minus the typical delay for that hour.

## Bottom Line

The recorded data can be used for OBT training today, but with degraded feature quality. The turnaround duration target (parked→pushback) is correctly derivable from inferred phase transitions. The quickest path to usable training data is:

1. Add historical METAR weather (fills 2 critical features)
2. Add icao24→aircraft type lookup (fills `aircraft_category`)
3. Accept that delay/schedule features will be zero/missing and train a reduced-feature model variant for recorded data
