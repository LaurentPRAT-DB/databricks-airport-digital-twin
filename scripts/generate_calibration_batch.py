"""Generate 132 calibration batch configs (33 airports x 4 runs each).

Creates:
- 99 normal-day configs (3 per airport, seeds 100/200/300)
- 33 weather configs (1 per airport, seed 42, with scenario file)
- 23 new weather scenario YAMLs (for airports without existing scenarios)
- 1 Databricks job YAML (resources/calibration_batch_job.yml)

Usage:
    uv run python scripts/generate_calibration_batch.py
"""

from __future__ import annotations

import os
from pathlib import Path

# ── All 33 calibrated airports ──────────────────────────────────────────────
AIRPORTS = [
    "SFO", "JFK", "ATL", "ORD", "LAX", "DFW", "DEN", "SEA", "MIA", "EWR",
    "BOS", "PHX", "LAS", "MCO", "CLT", "MSP", "DTW", "PHL", "IAH", "SAN",
    "PDX", "LHR", "DXB", "NRT", "SIN", "HKG", "CDG", "FRA", "AMS", "SYD",
    "ICN", "GRU", "JNB",
]

# ── Existing weather scenarios (already in scenarios/) ──────────────────────
EXISTING_SCENARIOS: dict[str, str] = {
    "SFO": "scenarios/sfo_summer_thunderstorm.yaml",
    "JFK": "scenarios/jfk_winter_storm.yaml",
    "LHR": "scenarios/lhr_winter_fog.yaml",
    "GRU": "scenarios/gru_tropical_storm.yaml",
    "DXB": "scenarios/dxb_sandstorm.yaml",
    "SYD": "scenarios/syd_bushfire_smoke.yaml",
    "NRT": "scenarios/nrt_typhoon.yaml",
    "SIN": "scenarios/sin_monsoon.yaml",
    "FRA": "scenarios/fra_winter_crosswind.yaml",
    "JNB": "scenarios/jnb_summer_thunderstorm.yaml",
}

# ── New weather scenarios to generate ───────────────────────────────────────
# Each tuple: (filename_suffix, full YAML content)
NEW_SCENARIOS: dict[str, tuple[str, str]] = {
    "ATL": ("atl_summer_thunderstorm", """\
name: ATL Summer Severe Thunderstorm — US Southeast
description: >
  Intense summer afternoon convection rolls through Atlanta. A line of severe
  thunderstorms produces wind shear, flash flooding on the ramp, and frequent
  lightning forcing ramp closures. Hartsfield-Jackson's massive hub operation
  cascades delays across the US network. Realistic for Jun-Aug afternoon storms.

weather_events:
  - time: "13:00"
    type: thunderstorm
    severity: moderate
    duration_hours: 1.5
    visibility_nm: 3.0
    ceiling_ft: 2500
    wind_speed_kt: 20
    wind_gusts_kt: 35
    wind_direction: 240

  - time: "14:30"
    type: thunderstorm
    severity: severe
    duration_hours: 2.5
    visibility_nm: 0.5
    ceiling_ft: 500
    wind_speed_kt: 40
    wind_gusts_kt: 62
    wind_direction: 260

  - time: "17:00"
    type: thunderstorm
    severity: moderate
    duration_hours: 1.5
    visibility_nm: 2.0
    ceiling_ft: 1500
    wind_speed_kt: 25
    wind_gusts_kt: 40
    wind_direction: 270

  - time: "18:30"
    type: rain
    severity: light
    duration_hours: 2.0
    visibility_nm: 5.0
    ceiling_ft: 3000
    wind_speed_kt: 15
    wind_direction: 280

  - time: "20:30"
    type: clear
    severity: light
    duration_hours: 3.5
    visibility_nm: 10.0
    ceiling_ft: 5000
    wind_speed_kt: 8
    wind_direction: 290

runway_events:
  - time: "14:30"
    type: closure
    runway: "26L"
    duration_minutes: 120
    reason: Severe thunderstorm — wind shear alerts on approach

  - time: "15:00"
    type: closure
    runway: "27R"
    duration_minutes: 90
    reason: Lightning within 3nm — all ops suspended

ground_events:
  - time: "14:00"
    type: gate_failure
    target: "T-N-A12"
    duration_hours: 3.0

  - time: "14:30"
    type: taxiway_closure
    target: "Taxiway L (flash flooding)"
    duration_hours: 4.0
    impact:
      turnaround_multiplier: 1.5

  - time: "15:00"
    type: gate_failure
    target: "Concourse D-22"
    duration_hours: 2.5

traffic_modifiers:
  - time: "13:00"
    type: surge
    extra_arrivals: 8
    extra_departures: 6

  - time: "15:00"
    type: ground_stop
    duration_hours: 2.0

  - time: "17:30"
    type: diversion
    extra_arrivals: 12
    diversion_origin: CLT
"""),
    "BOS": ("bos_noreaster", """\
name: BOS Winter Nor'easter — US Northeast
description: >
  Classic New England nor'easter slams Boston Logan. Heavy snow begins
  overnight with freezing rain mixing in. Sustained northeast winds
  exceed 40kt with gusts to 55kt. The airport faces prolonged de-icing
  and periodic runway closures. Realistic for Dec-Mar.

weather_events:
  - time: "02:00"
    type: snow
    severity: moderate
    duration_hours: 3.0
    visibility_nm: 1.5
    ceiling_ft: 800
    wind_speed_kt: 25
    wind_gusts_kt: 38
    wind_direction: 040

  - time: "05:00"
    type: snow
    severity: severe
    duration_hours: 5.0
    visibility_nm: 0.25
    ceiling_ft: 200
    wind_speed_kt: 40
    wind_gusts_kt: 55
    wind_direction: 030

  - time: "10:00"
    type: freezing_rain
    severity: moderate
    duration_hours: 2.0
    visibility_nm: 1.0
    ceiling_ft: 400
    wind_speed_kt: 30
    wind_gusts_kt: 45
    wind_direction: 020

  - time: "12:00"
    type: snow
    severity: light
    duration_hours: 3.0
    visibility_nm: 2.0
    ceiling_ft: 1200
    wind_speed_kt: 22
    wind_gusts_kt: 35
    wind_direction: 010

  - time: "15:00"
    type: clear
    severity: light
    duration_hours: 9.0
    visibility_nm: 8.0
    ceiling_ft: 4000
    wind_speed_kt: 15
    wind_direction: 350

runway_events:
  - time: "05:00"
    type: closure
    runway: "27"
    duration_minutes: 180
    reason: Heavy snow accumulation — plowing operations

  - time: "06:00"
    type: closure
    runway: "22L"
    duration_minutes: 240
    reason: Snow and ice — single runway ops

ground_events:
  - time: "03:00"
    type: deicing_required
    duration_hours: 12.0
    impact:
      turnaround_multiplier: 1.8

  - time: "06:00"
    type: gate_failure
    target: "Terminal B-24"
    duration_hours: 4.0

  - time: "08:00"
    type: taxiway_closure
    target: "Taxiway N (snow drifts)"
    duration_hours: 6.0
    impact:
      turnaround_multiplier: 1.4

traffic_modifiers:
  - time: "06:00"
    type: ground_stop
    duration_hours: 3.0

  - time: "10:00"
    type: diversion
    extra_arrivals: 8
    diversion_origin: EWR
"""),
    "CLT": ("clt_derecho", """\
name: CLT Summer Derecho — US Southeast
description: >
  A fast-moving derecho (widespread windstorm) sweeps across the
  Carolinas. Sustained winds exceed 50kt with gusts to 75kt.
  Power outages affect terminal systems. Quick onset and passage
  but devastating ground impact. Realistic for Jun-Aug.

weather_events:
  - time: "14:00"
    type: thunderstorm
    severity: moderate
    duration_hours: 1.0
    visibility_nm: 3.0
    ceiling_ft: 2000
    wind_speed_kt: 25
    wind_gusts_kt: 40
    wind_direction: 270

  - time: "15:00"
    type: thunderstorm
    severity: severe
    duration_hours: 2.0
    visibility_nm: 0.25
    ceiling_ft: 300
    wind_speed_kt: 55
    wind_gusts_kt: 75
    wind_direction: 280

  - time: "17:00"
    type: rain
    severity: moderate
    duration_hours: 2.0
    visibility_nm: 2.0
    ceiling_ft: 1500
    wind_speed_kt: 30
    wind_gusts_kt: 45
    wind_direction: 290

  - time: "19:00"
    type: clear
    severity: light
    duration_hours: 5.0
    visibility_nm: 10.0
    ceiling_ft: 5000
    wind_speed_kt: 12
    wind_direction: 300

runway_events:
  - time: "15:00"
    type: closure
    runway: "18C"
    duration_minutes: 150
    reason: Derecho wind damage — debris on runway

  - time: "15:30"
    type: closure
    runway: "18L"
    duration_minutes: 120
    reason: Wind shear exceeds limits

ground_events:
  - time: "15:00"
    type: gate_failure
    target: "Concourse B-12"
    duration_hours: 5.0

  - time: "15:00"
    type: gate_failure
    target: "Concourse E-8"
    duration_hours: 4.0

  - time: "16:00"
    type: taxiway_closure
    target: "Taxiway D (debris)"
    duration_hours: 3.0
    impact:
      turnaround_multiplier: 1.6

traffic_modifiers:
  - time: "15:00"
    type: ground_stop
    duration_hours: 2.5

  - time: "17:30"
    type: diversion
    extra_arrivals: 8
    diversion_origin: RDU
"""),
    "DEN": ("den_spring_blizzard", """\
name: DEN Spring Blizzard — Colorado Front Range
description: >
  Late-season upslope blizzard hits the Front Range. Heavy wet snow
  accumulates rapidly with near-whiteout conditions. Wind gusts to
  50kt create zero-visibility in blowing snow. Denver's high altitude
  compounds de-icing challenges. Realistic for Mar-Apr.

weather_events:
  - time: "04:00"
    type: snow
    severity: moderate
    duration_hours: 3.0
    visibility_nm: 1.0
    ceiling_ft: 600
    wind_speed_kt: 25
    wind_gusts_kt: 40
    wind_direction: 020

  - time: "07:00"
    type: snow
    severity: severe
    duration_hours: 6.0
    visibility_nm: 0.12
    ceiling_ft: 100
    wind_speed_kt: 40
    wind_gusts_kt: 55
    wind_direction: 030

  - time: "13:00"
    type: snow
    severity: moderate
    duration_hours: 3.0
    visibility_nm: 0.5
    ceiling_ft: 400
    wind_speed_kt: 30
    wind_gusts_kt: 45
    wind_direction: 040

  - time: "16:00"
    type: snow
    severity: light
    duration_hours: 2.0
    visibility_nm: 2.0
    ceiling_ft: 1500
    wind_speed_kt: 18
    wind_direction: 350

  - time: "18:00"
    type: clear
    severity: light
    duration_hours: 6.0
    visibility_nm: 10.0
    ceiling_ft: 6000
    wind_speed_kt: 10
    wind_direction: 330

runway_events:
  - time: "07:00"
    type: closure
    runway: "16R"
    duration_minutes: 300
    reason: Blizzard conditions — whiteout

  - time: "08:00"
    type: closure
    runway: "16L"
    duration_minutes: 240
    reason: Snow accumulation exceeds plowing capacity

ground_events:
  - time: "05:00"
    type: deicing_required
    duration_hours: 14.0
    impact:
      turnaround_multiplier: 2.0

  - time: "07:00"
    type: gate_failure
    target: "Concourse B-45"
    duration_hours: 6.0

  - time: "09:00"
    type: taxiway_closure
    target: "Taxiway EE (snow drifts 3ft+)"
    duration_hours: 8.0
    impact:
      turnaround_multiplier: 1.5

traffic_modifiers:
  - time: "07:00"
    type: ground_stop
    duration_hours: 5.0

  - time: "14:00"
    type: diversion
    extra_arrivals: 10
    diversion_origin: COS
"""),
    "DFW": ("dfw_tornado_outbreak", """\
name: DFW Spring Tornado Outbreak — North Texas
description: >
  A supercell cluster moves through the DFW metroplex. Large hail,
  tornado warnings, and severe wind gusts hammer the airport.
  FAA issues ground stop. Tornado sirens force terminal evacuations.
  Realistic for Mar-Jun tornado season in Tornado Alley.

weather_events:
  - time: "15:00"
    type: thunderstorm
    severity: moderate
    duration_hours: 1.0
    visibility_nm: 3.0
    ceiling_ft: 2000
    wind_speed_kt: 25
    wind_gusts_kt: 40
    wind_direction: 230

  - time: "16:00"
    type: thunderstorm
    severity: severe
    duration_hours: 3.0
    visibility_nm: 0.25
    ceiling_ft: 200
    wind_speed_kt: 50
    wind_gusts_kt: 72
    wind_direction: 250

  - time: "19:00"
    type: thunderstorm
    severity: moderate
    duration_hours: 2.0
    visibility_nm: 1.5
    ceiling_ft: 1000
    wind_speed_kt: 30
    wind_gusts_kt: 48
    wind_direction: 270

  - time: "21:00"
    type: clear
    severity: light
    duration_hours: 3.0
    visibility_nm: 10.0
    ceiling_ft: 5000
    wind_speed_kt: 12
    wind_direction: 290

runway_events:
  - time: "16:00"
    type: closure
    runway: "17L"
    duration_minutes: 180
    reason: Tornado warning — all ops suspended

  - time: "16:30"
    type: closure
    runway: "17R"
    duration_minutes: 150
    reason: Hail damage inspection required

ground_events:
  - time: "16:00"
    type: gate_failure
    target: "Terminal D-28"
    duration_hours: 4.0

  - time: "16:00"
    type: taxiway_closure
    target: "Taxiway P (hail accumulation)"
    duration_hours: 3.0
    impact:
      turnaround_multiplier: 1.5

  - time: "17:00"
    type: gate_failure
    target: "Terminal A-14"
    duration_hours: 3.0

traffic_modifiers:
  - time: "15:30"
    type: ground_stop
    duration_hours: 3.5

  - time: "19:30"
    type: diversion
    extra_arrivals: 10
    diversion_origin: DAL
"""),
    "DTW": ("dtw_lake_effect_blizzard", """\
name: DTW Lake-Effect Blizzard — Great Lakes
description: >
  Arctic air mass crosses Lake Erie, dumping lake-effect snow bands
  on metro Detroit. Narrow intense bands produce localized whiteout.
  Temperatures plunge to -15F with wind chill -35F. Equipment
  freezes and de-icing fluid runs short. Realistic for Dec-Feb.

weather_events:
  - time: "06:00"
    type: snow
    severity: moderate
    duration_hours: 3.0
    visibility_nm: 1.0
    ceiling_ft: 600
    wind_speed_kt: 22
    wind_gusts_kt: 35
    wind_direction: 350

  - time: "09:00"
    type: snow
    severity: severe
    duration_hours: 5.0
    visibility_nm: 0.12
    ceiling_ft: 100
    wind_speed_kt: 30
    wind_gusts_kt: 45
    wind_direction: 340

  - time: "14:00"
    type: snow
    severity: moderate
    duration_hours: 4.0
    visibility_nm: 0.5
    ceiling_ft: 400
    wind_speed_kt: 25
    wind_gusts_kt: 38
    wind_direction: 330

  - time: "18:00"
    type: snow
    severity: light
    duration_hours: 3.0
    visibility_nm: 2.0
    ceiling_ft: 1500
    wind_speed_kt: 18
    wind_direction: 320

  - time: "21:00"
    type: clear
    severity: light
    duration_hours: 3.0
    visibility_nm: 8.0
    ceiling_ft: 4000
    wind_speed_kt: 12
    wind_direction: 310

runway_events:
  - time: "09:00"
    type: closure
    runway: "21L"
    duration_minutes: 240
    reason: Lake-effect whiteout band stalled over field

  - time: "10:00"
    type: closure
    runway: "21R"
    duration_minutes: 180
    reason: Snow accumulation rate exceeds plowing

ground_events:
  - time: "07:00"
    type: deicing_required
    duration_hours: 14.0
    impact:
      turnaround_multiplier: 1.9

  - time: "09:00"
    type: gate_failure
    target: "McNamara A-42"
    duration_hours: 5.0

  - time: "11:00"
    type: fuel_shortage
    duration_hours: 4.0
    impact:
      turnaround_multiplier: 1.3

traffic_modifiers:
  - time: "09:00"
    type: ground_stop
    duration_hours: 4.0

  - time: "14:00"
    type: diversion
    extra_arrivals: 6
    diversion_origin: CLE
"""),
    "EWR": ("ewr_ice_storm", """\
name: EWR Winter Ice Storm — US Mid-Atlantic
description: >
  Warm front overruns arctic air producing freezing rain across
  northern New Jersey. Ice accumulation up to 0.75 inches on
  surfaces. EWR's notoriously tight taxi geometry compounds delays.
  De-icing fluid consumption surges. Realistic for Dec-Feb.

weather_events:
  - time: "03:00"
    type: freezing_rain
    severity: moderate
    duration_hours: 3.0
    visibility_nm: 2.0
    ceiling_ft: 800
    wind_speed_kt: 15
    wind_direction: 060

  - time: "06:00"
    type: freezing_rain
    severity: severe
    duration_hours: 4.0
    visibility_nm: 0.5
    ceiling_ft: 300
    wind_speed_kt: 20
    wind_gusts_kt: 32
    wind_direction: 050

  - time: "10:00"
    type: rain
    severity: moderate
    duration_hours: 3.0
    visibility_nm: 2.0
    ceiling_ft: 1000
    wind_speed_kt: 18
    wind_direction: 080

  - time: "13:00"
    type: rain
    severity: light
    duration_hours: 2.0
    visibility_nm: 4.0
    ceiling_ft: 2000
    wind_speed_kt: 12
    wind_direction: 100

  - time: "15:00"
    type: clear
    severity: light
    duration_hours: 9.0
    visibility_nm: 10.0
    ceiling_ft: 5000
    wind_speed_kt: 8
    wind_direction: 120

runway_events:
  - time: "06:00"
    type: closure
    runway: "22L"
    duration_minutes: 240
    reason: Ice accumulation — chemical treatment required

  - time: "07:00"
    type: closure
    runway: "22R"
    duration_minutes: 180
    reason: Freezing rain — braking action nil

ground_events:
  - time: "04:00"
    type: deicing_required
    duration_hours: 10.0
    impact:
      turnaround_multiplier: 1.9

  - time: "06:00"
    type: gate_failure
    target: "Terminal C-124"
    duration_hours: 5.0

  - time: "07:00"
    type: taxiway_closure
    target: "Taxiway Z (ice)"
    duration_hours: 6.0
    impact:
      turnaround_multiplier: 1.6

traffic_modifiers:
  - time: "06:00"
    type: ground_stop
    duration_hours: 3.0

  - time: "10:00"
    type: diversion
    extra_arrivals: 8
    diversion_origin: LGA
"""),
    "IAH": ("iah_hurricane_approach", """\
name: IAH Gulf Hurricane Approach — Texas Gulf Coast
description: >
  Category 2 hurricane approaches the Texas coast. Outer bands bring
  heavy rain and gusty winds hours before landfall. Flooding shuts
  down ground access roads. Airlines preemptively cancel flights.
  Realistic for Jun-Nov hurricane season.

weather_events:
  - time: "06:00"
    type: rain
    severity: moderate
    duration_hours: 3.0
    visibility_nm: 3.0
    ceiling_ft: 1500
    wind_speed_kt: 25
    wind_gusts_kt: 38
    wind_direction: 120

  - time: "09:00"
    type: rain
    severity: severe
    duration_hours: 4.0
    visibility_nm: 0.5
    ceiling_ft: 300
    wind_speed_kt: 45
    wind_gusts_kt: 65
    wind_direction: 140

  - time: "13:00"
    type: thunderstorm
    severity: severe
    duration_hours: 4.0
    visibility_nm: 0.25
    ceiling_ft: 200
    wind_speed_kt: 55
    wind_gusts_kt: 78
    wind_direction: 160

  - time: "17:00"
    type: rain
    severity: moderate
    duration_hours: 4.0
    visibility_nm: 1.0
    ceiling_ft: 500
    wind_speed_kt: 35
    wind_gusts_kt: 50
    wind_direction: 180

  - time: "21:00"
    type: rain
    severity: light
    duration_hours: 3.0
    visibility_nm: 3.0
    ceiling_ft: 1500
    wind_speed_kt: 20
    wind_direction: 200

runway_events:
  - time: "09:00"
    type: closure
    runway: "26L"
    duration_minutes: 360
    reason: Hurricane approach — runway flooding

  - time: "10:00"
    type: closure
    runway: "26R"
    duration_minutes: 300
    reason: Wind exceeds crosswind limits

ground_events:
  - time: "08:00"
    type: taxiway_closure
    target: "Taxiway WA (flooding)"
    duration_hours: 10.0
    impact:
      turnaround_multiplier: 1.8

  - time: "10:00"
    type: gate_failure
    target: "Terminal C-34"
    duration_hours: 8.0

  - time: "12:00"
    type: fuel_shortage
    duration_hours: 6.0
    impact:
      turnaround_multiplier: 1.5

traffic_modifiers:
  - time: "08:00"
    type: ground_stop
    duration_hours: 8.0

  - time: "10:00"
    type: diversion
    extra_arrivals: 15
    diversion_origin: HOU
"""),
    "LAS": ("las_haboob", """\
name: LAS Summer Haboob — Mojave Desert
description: >
  Monsoon outflow boundary generates a massive haboob (dust wall)
  across the Las Vegas valley. Visibility drops to near zero.
  Extreme heat (115F) causes density altitude issues. Microburst
  wind shear on approach. Realistic for Jul-Sep monsoon season.

weather_events:
  - time: "16:00"
    type: dust
    severity: moderate
    duration_hours: 1.0
    visibility_nm: 2.0
    ceiling_ft: 2000
    wind_speed_kt: 20
    wind_direction: 200

  - time: "17:00"
    type: sandstorm
    severity: severe
    duration_hours: 2.0
    visibility_nm: 0.12
    ceiling_ft: 100
    wind_speed_kt: 45
    wind_gusts_kt: 65
    wind_direction: 210

  - time: "19:00"
    type: dust
    severity: moderate
    duration_hours: 2.0
    visibility_nm: 1.0
    ceiling_ft: 800
    wind_speed_kt: 25
    wind_gusts_kt: 40
    wind_direction: 220

  - time: "21:00"
    type: haze
    severity: light
    duration_hours: 2.0
    visibility_nm: 4.0
    ceiling_ft: 3000
    wind_speed_kt: 15
    wind_direction: 230

  - time: "23:00"
    type: clear
    severity: light
    duration_hours: 7.0
    visibility_nm: 10.0
    ceiling_ft: 8000
    wind_speed_kt: 8
    wind_direction: 240

runway_events:
  - time: "17:00"
    type: closure
    runway: "26L"
    duration_minutes: 120
    reason: Haboob — zero visibility

  - time: "17:30"
    type: closure
    runway: "26R"
    duration_minutes: 90
    reason: Dust and wind shear

ground_events:
  - time: "17:00"
    type: gate_failure
    target: "Terminal 1-D8"
    duration_hours: 3.0

  - time: "17:00"
    type: taxiway_closure
    target: "Taxiway A (dust accumulation)"
    duration_hours: 4.0
    impact:
      turnaround_multiplier: 1.5

traffic_modifiers:
  - time: "16:30"
    type: ground_stop
    duration_hours: 2.5

  - time: "19:30"
    type: diversion
    extra_arrivals: 6
    diversion_origin: PHX
"""),
    "LAX": ("lax_santa_ana_winds", """\
name: LAX Santa Ana Wind Event — Southern California
description: >
  Strong Santa Ana winds blast through the LA basin with gusts
  exceeding 60kt. Extreme turbulence on approach over the mountains.
  Offshore flow clears marine layer but creates severe mechanical
  turbulence. Wildfire smoke may reduce visibility. Realistic for Oct-Mar.

weather_events:
  - time: "02:00"
    type: wind_shift
    severity: moderate
    duration_hours: 4.0
    visibility_nm: 6.0
    ceiling_ft: 8000
    wind_speed_kt: 30
    wind_gusts_kt: 48
    wind_direction: 060

  - time: "06:00"
    type: wind_shift
    severity: severe
    duration_hours: 6.0
    visibility_nm: 4.0
    ceiling_ft: 6000
    wind_speed_kt: 45
    wind_gusts_kt: 65
    wind_direction: 050

  - time: "12:00"
    type: haze
    severity: moderate
    duration_hours: 4.0
    visibility_nm: 3.0
    ceiling_ft: 5000
    wind_speed_kt: 35
    wind_gusts_kt: 55
    wind_direction: 060

  - time: "16:00"
    type: wind_shift
    severity: moderate
    duration_hours: 4.0
    visibility_nm: 5.0
    ceiling_ft: 6000
    wind_speed_kt: 25
    wind_gusts_kt: 42
    wind_direction: 070

  - time: "20:00"
    type: clear
    severity: light
    duration_hours: 4.0
    visibility_nm: 10.0
    ceiling_ft: 8000
    wind_speed_kt: 15
    wind_direction: 080

runway_events:
  - time: "06:00"
    type: config_change
    runway_config: "24L_24R_westerly"
    duration_minutes: 480
    reason: Santa Ana easterly flow forces westbound operations

  - time: "08:00"
    type: closure
    runway: "24L"
    duration_minutes: 120
    reason: Wind shear reports exceed approach limits

ground_events:
  - time: "06:00"
    type: gate_failure
    target: "TBIT-148"
    duration_hours: 4.0

  - time: "10:00"
    type: taxiway_closure
    target: "Taxiway AA (debris)"
    duration_hours: 3.0
    impact:
      turnaround_multiplier: 1.3

traffic_modifiers:
  - time: "06:00"
    type: surge
    extra_arrivals: 6
    extra_departures: 4

  - time: "09:00"
    type: diversion
    extra_arrivals: 8
    diversion_origin: BUR
"""),
    "MCO": ("mco_thunderstorm_complex", """\
name: MCO Afternoon Thunderstorm Complex — Central Florida
description: >
  Classic Florida summer afternoon convection. Sea breeze convergence
  spawns a complex of thunderstorms with frequent lightning, heavy rain,
  and wind shear. Storms build rapidly and stall over the airport.
  Ramp closures impact the busy tourist traffic. Realistic for Jun-Sep.

weather_events:
  - time: "14:00"
    type: thunderstorm
    severity: moderate
    duration_hours: 1.0
    visibility_nm: 3.0
    ceiling_ft: 2500
    wind_speed_kt: 18
    wind_gusts_kt: 30
    wind_direction: 180

  - time: "15:00"
    type: thunderstorm
    severity: severe
    duration_hours: 2.5
    visibility_nm: 0.5
    ceiling_ft: 400
    wind_speed_kt: 35
    wind_gusts_kt: 55
    wind_direction: 200

  - time: "17:30"
    type: thunderstorm
    severity: moderate
    duration_hours: 2.0
    visibility_nm: 1.5
    ceiling_ft: 1200
    wind_speed_kt: 22
    wind_gusts_kt: 38
    wind_direction: 220

  - time: "19:30"
    type: rain
    severity: light
    duration_hours: 1.5
    visibility_nm: 4.0
    ceiling_ft: 2500
    wind_speed_kt: 12
    wind_direction: 240

  - time: "21:00"
    type: clear
    severity: light
    duration_hours: 3.0
    visibility_nm: 10.0
    ceiling_ft: 5000
    wind_speed_kt: 6
    wind_direction: 260

runway_events:
  - time: "15:00"
    type: closure
    runway: "17R"
    duration_minutes: 120
    reason: Lightning within 3nm — ramp closure

  - time: "15:30"
    type: closure
    runway: "17L"
    duration_minutes: 90
    reason: Wind shear alerts on approach

ground_events:
  - time: "15:00"
    type: gate_failure
    target: "Terminal B-62"
    duration_hours: 3.0

  - time: "16:00"
    type: taxiway_closure
    target: "Taxiway E (flooding)"
    duration_hours: 2.5
    impact:
      turnaround_multiplier: 1.4

traffic_modifiers:
  - time: "14:30"
    type: ground_stop
    duration_hours: 2.0

  - time: "17:00"
    type: diversion
    extra_arrivals: 6
    diversion_origin: TPA
"""),
    "MIA": ("mia_tropical_storm", """\
name: MIA Tropical Storm Passage — South Florida
description: >
  Tropical storm tracks across South Florida with sustained winds
  45-55kt and heavy rain bands. Storm surge floods low-lying access
  roads. Extended ramp closures and cancellations. Airlines activate
  hurricane contingency plans. Realistic for Jun-Nov.

weather_events:
  - time: "04:00"
    type: rain
    severity: moderate
    duration_hours: 3.0
    visibility_nm: 2.0
    ceiling_ft: 800
    wind_speed_kt: 30
    wind_gusts_kt: 45
    wind_direction: 090

  - time: "07:00"
    type: rain
    severity: severe
    duration_hours: 5.0
    visibility_nm: 0.5
    ceiling_ft: 200
    wind_speed_kt: 48
    wind_gusts_kt: 65
    wind_direction: 100

  - time: "12:00"
    type: thunderstorm
    severity: severe
    duration_hours: 3.0
    visibility_nm: 0.25
    ceiling_ft: 200
    wind_speed_kt: 55
    wind_gusts_kt: 72
    wind_direction: 120

  - time: "15:00"
    type: rain
    severity: moderate
    duration_hours: 3.0
    visibility_nm: 1.5
    ceiling_ft: 600
    wind_speed_kt: 35
    wind_gusts_kt: 50
    wind_direction: 150

  - time: "18:00"
    type: rain
    severity: light
    duration_hours: 3.0
    visibility_nm: 4.0
    ceiling_ft: 2000
    wind_speed_kt: 20
    wind_direction: 180

  - time: "21:00"
    type: clear
    severity: light
    duration_hours: 3.0
    visibility_nm: 8.0
    ceiling_ft: 4000
    wind_speed_kt: 12
    wind_direction: 200

runway_events:
  - time: "07:00"
    type: closure
    runway: "8R"
    duration_minutes: 360
    reason: Tropical storm — wind exceeds limits

  - time: "08:00"
    type: closure
    runway: "8L"
    duration_minutes: 300
    reason: Flooding on taxiways and runway

ground_events:
  - time: "06:00"
    type: taxiway_closure
    target: "Taxiway J (flooding)"
    duration_hours: 10.0
    impact:
      turnaround_multiplier: 1.8

  - time: "08:00"
    type: gate_failure
    target: "North Terminal-D22"
    duration_hours: 6.0

  - time: "10:00"
    type: gate_failure
    target: "South Terminal-H14"
    duration_hours: 5.0

traffic_modifiers:
  - time: "06:00"
    type: ground_stop
    duration_hours: 8.0

  - time: "16:00"
    type: diversion
    extra_arrivals: 10
    diversion_origin: FLL
"""),
    "MSP": ("msp_arctic_blast", """\
name: MSP Winter Arctic Blast — Upper Midwest
description: >
  Polar vortex dip brings extreme cold to Minneapolis. Temperatures
  drop to -25F with wind chill -50F. Equipment malfunctions, jet
  bridges freeze, and de-icing holdover times shorten dramatically.
  Blowing snow reduces visibility. Realistic for Dec-Feb.

weather_events:
  - time: "00:00"
    type: snow
    severity: moderate
    duration_hours: 4.0
    visibility_nm: 1.0
    ceiling_ft: 600
    wind_speed_kt: 20
    wind_gusts_kt: 35
    wind_direction: 320

  - time: "04:00"
    type: snow
    severity: severe
    duration_hours: 4.0
    visibility_nm: 0.25
    ceiling_ft: 200
    wind_speed_kt: 30
    wind_gusts_kt: 48
    wind_direction: 330

  - time: "08:00"
    type: snow
    severity: moderate
    duration_hours: 4.0
    visibility_nm: 0.75
    ceiling_ft: 500
    wind_speed_kt: 25
    wind_gusts_kt: 40
    wind_direction: 340

  - time: "12:00"
    type: snow
    severity: light
    duration_hours: 3.0
    visibility_nm: 2.0
    ceiling_ft: 1500
    wind_speed_kt: 18
    wind_direction: 350

  - time: "15:00"
    type: clear
    severity: light
    duration_hours: 9.0
    visibility_nm: 6.0
    ceiling_ft: 3000
    wind_speed_kt: 15
    wind_direction: 360

runway_events:
  - time: "04:00"
    type: closure
    runway: "30L"
    duration_minutes: 240
    reason: Blowing snow — near-zero visibility

  - time: "05:00"
    type: closure
    runway: "30R"
    duration_minutes: 180
    reason: Snow accumulation and ice

ground_events:
  - time: "01:00"
    type: deicing_required
    duration_hours: 16.0
    impact:
      turnaround_multiplier: 2.0

  - time: "04:00"
    type: gate_failure
    target: "Terminal 1-F12"
    duration_hours: 6.0

  - time: "06:00"
    type: fuel_shortage
    duration_hours: 4.0
    impact:
      turnaround_multiplier: 1.3

traffic_modifiers:
  - time: "04:00"
    type: ground_stop
    duration_hours: 4.0

  - time: "09:00"
    type: diversion
    extra_arrivals: 6
    diversion_origin: MKE
"""),
    "ORD": ("ord_winter_blizzard", """\
name: ORD Winter Blizzard — Great Lakes
description: >
  Major winter storm buries Chicago with 12+ inches of snow.
  O'Hare is the nation's busiest hub and delays cascade nationally.
  Extended ground stops, de-icing queues over 2 hours, and
  hundreds of cancellations. Realistic for Nov-Mar.

weather_events:
  - time: "03:00"
    type: snow
    severity: moderate
    duration_hours: 3.0
    visibility_nm: 1.5
    ceiling_ft: 800
    wind_speed_kt: 22
    wind_gusts_kt: 35
    wind_direction: 020

  - time: "06:00"
    type: snow
    severity: severe
    duration_hours: 6.0
    visibility_nm: 0.12
    ceiling_ft: 100
    wind_speed_kt: 35
    wind_gusts_kt: 52
    wind_direction: 030

  - time: "12:00"
    type: snow
    severity: moderate
    duration_hours: 4.0
    visibility_nm: 0.5
    ceiling_ft: 400
    wind_speed_kt: 28
    wind_gusts_kt: 42
    wind_direction: 340

  - time: "16:00"
    type: snow
    severity: light
    duration_hours: 3.0
    visibility_nm: 2.0
    ceiling_ft: 1500
    wind_speed_kt: 18
    wind_direction: 330

  - time: "19:00"
    type: clear
    severity: light
    duration_hours: 5.0
    visibility_nm: 8.0
    ceiling_ft: 4000
    wind_speed_kt: 12
    wind_direction: 310

runway_events:
  - time: "06:00"
    type: closure
    runway: "10C"
    duration_minutes: 300
    reason: Blizzard — continuous plowing required

  - time: "07:00"
    type: closure
    runway: "10L"
    duration_minutes: 240
    reason: Heavy snow — braking action nil

ground_events:
  - time: "04:00"
    type: deicing_required
    duration_hours: 15.0
    impact:
      turnaround_multiplier: 2.0

  - time: "06:00"
    type: gate_failure
    target: "Terminal 1-C18"
    duration_hours: 6.0

  - time: "08:00"
    type: taxiway_closure
    target: "Taxiway M (snow drifts)"
    duration_hours: 8.0
    impact:
      turnaround_multiplier: 1.5

traffic_modifiers:
  - time: "06:00"
    type: ground_stop
    duration_hours: 5.0

  - time: "13:00"
    type: diversion
    extra_arrivals: 12
    diversion_origin: MDW
"""),
    "PDX": ("pdx_atmospheric_river", """\
name: PDX Atmospheric River — Pacific Northwest
description: >
  Pineapple Express atmospheric river makes landfall in Oregon.
  Persistent heavy rain with embedded thunderstorms. Ceilings
  hover near minimums for hours. River flooding threatens
  ground access. Realistic for Nov-Mar.

weather_events:
  - time: "02:00"
    type: rain
    severity: moderate
    duration_hours: 4.0
    visibility_nm: 2.0
    ceiling_ft: 600
    wind_speed_kt: 20
    wind_gusts_kt: 32
    wind_direction: 180

  - time: "06:00"
    type: rain
    severity: severe
    duration_hours: 6.0
    visibility_nm: 0.5
    ceiling_ft: 200
    wind_speed_kt: 30
    wind_gusts_kt: 48
    wind_direction: 190

  - time: "12:00"
    type: rain
    severity: moderate
    duration_hours: 4.0
    visibility_nm: 1.5
    ceiling_ft: 500
    wind_speed_kt: 25
    wind_gusts_kt: 40
    wind_direction: 200

  - time: "16:00"
    type: rain
    severity: light
    duration_hours: 4.0
    visibility_nm: 3.0
    ceiling_ft: 1500
    wind_speed_kt: 18
    wind_direction: 210

  - time: "20:00"
    type: clear
    severity: light
    duration_hours: 4.0
    visibility_nm: 8.0
    ceiling_ft: 4000
    wind_speed_kt: 10
    wind_direction: 220

runway_events:
  - time: "06:00"
    type: closure
    runway: "10R"
    duration_minutes: 240
    reason: Visibility below minimums — ILS approach only

  - time: "08:00"
    type: closure
    runway: "10L"
    duration_minutes: 180
    reason: Standing water — hydroplaning risk

ground_events:
  - time: "06:00"
    type: taxiway_closure
    target: "Taxiway C (flooding)"
    duration_hours: 8.0
    impact:
      turnaround_multiplier: 1.5

  - time: "09:00"
    type: gate_failure
    target: "Concourse D-8"
    duration_hours: 4.0

traffic_modifiers:
  - time: "06:00"
    type: surge
    extra_arrivals: 4
    extra_departures: 2

  - time: "10:00"
    type: diversion
    extra_arrivals: 6
    diversion_origin: SEA
"""),
    "PHL": ("phl_summer_thunderstorm", """\
name: PHL Summer Severe Thunderstorm — US Mid-Atlantic
description: >
  Summer squall line moves through the Delaware Valley with severe
  thunderstorms, large hail, and damaging wind gusts. PHL's close
  proximity to EWR and JFK means coordinated flow control across
  the NY/PHL metroplex. Realistic for Jun-Aug.

weather_events:
  - time: "15:00"
    type: thunderstorm
    severity: moderate
    duration_hours: 1.5
    visibility_nm: 3.0
    ceiling_ft: 2000
    wind_speed_kt: 22
    wind_gusts_kt: 35
    wind_direction: 250

  - time: "16:30"
    type: thunderstorm
    severity: severe
    duration_hours: 2.0
    visibility_nm: 0.5
    ceiling_ft: 400
    wind_speed_kt: 42
    wind_gusts_kt: 60
    wind_direction: 270

  - time: "18:30"
    type: thunderstorm
    severity: moderate
    duration_hours: 1.5
    visibility_nm: 2.0
    ceiling_ft: 1200
    wind_speed_kt: 25
    wind_gusts_kt: 40
    wind_direction: 280

  - time: "20:00"
    type: clear
    severity: light
    duration_hours: 4.0
    visibility_nm: 10.0
    ceiling_ft: 5000
    wind_speed_kt: 10
    wind_direction: 290

runway_events:
  - time: "16:30"
    type: closure
    runway: "27L"
    duration_minutes: 120
    reason: Severe thunderstorm — wind shear

  - time: "17:00"
    type: closure
    runway: "27R"
    duration_minutes: 90
    reason: Hail on runway

ground_events:
  - time: "16:30"
    type: gate_failure
    target: "Terminal F-28"
    duration_hours: 3.0

  - time: "17:00"
    type: taxiway_closure
    target: "Taxiway K (hail/debris)"
    duration_hours: 2.5
    impact:
      turnaround_multiplier: 1.4

traffic_modifiers:
  - time: "16:00"
    type: ground_stop
    duration_hours: 2.0

  - time: "18:30"
    type: diversion
    extra_arrivals: 6
    diversion_origin: EWR
"""),
    "PHX": ("phx_extreme_heat_dust", """\
name: PHX Extreme Heat + Dust Storm — Arizona Desert
description: >
  Record heat wave (120F+) combined with monsoon-triggered haboob.
  Density altitude severely limits takeoff performance. Dust storm
  drops visibility to near zero. Microbursts on approach. Airport
  surface too hot for ground crews. Realistic for Jun-Sep.

weather_events:
  - time: "10:00"
    type: clear
    severity: moderate
    duration_hours: 5.0
    visibility_nm: 6.0
    ceiling_ft: 8000
    wind_speed_kt: 8
    wind_direction: 200

  - time: "15:00"
    type: dust
    severity: moderate
    duration_hours: 1.5
    visibility_nm: 2.0
    ceiling_ft: 2000
    wind_speed_kt: 22
    wind_direction: 210

  - time: "16:30"
    type: sandstorm
    severity: severe
    duration_hours: 2.0
    visibility_nm: 0.12
    ceiling_ft: 100
    wind_speed_kt: 45
    wind_gusts_kt: 60
    wind_direction: 220

  - time: "18:30"
    type: thunderstorm
    severity: moderate
    duration_hours: 2.0
    visibility_nm: 1.5
    ceiling_ft: 1000
    wind_speed_kt: 30
    wind_gusts_kt: 50
    wind_direction: 240

  - time: "20:30"
    type: clear
    severity: light
    duration_hours: 3.5
    visibility_nm: 8.0
    ceiling_ft: 6000
    wind_speed_kt: 10
    wind_direction: 260

runway_events:
  - time: "16:30"
    type: closure
    runway: "25L"
    duration_minutes: 120
    reason: Haboob — zero visibility

  - time: "17:00"
    type: closure
    runway: "25R"
    duration_minutes: 90
    reason: Microburst wind shear on approach

ground_events:
  - time: "12:00"
    type: gate_failure
    target: "Terminal 4-B8"
    duration_hours: 5.0

  - time: "16:30"
    type: taxiway_closure
    target: "Taxiway A (dust accumulation)"
    duration_hours: 3.0
    impact:
      turnaround_multiplier: 1.5

traffic_modifiers:
  - time: "16:00"
    type: ground_stop
    duration_hours: 2.5

  - time: "19:00"
    type: diversion
    extra_arrivals: 6
    diversion_origin: TUS
"""),
    "SAN": ("san_marine_santa_ana", """\
name: SAN Marine Layer + Santa Ana Transition — Southern California
description: >
  Morning marine layer brings dense fog to Lindbergh Field, then
  afternoon Santa Ana winds arrive with a dramatic shift. The
  transition between fog and wind creates challenging conditions
  for SAN's single runway. Realistic for Oct-Mar.

weather_events:
  - time: "04:00"
    type: fog
    severity: severe
    duration_hours: 3.0
    visibility_nm: 0.25
    ceiling_ft: 100
    wind_speed_kt: 3
    wind_direction: 270

  - time: "07:00"
    type: fog
    severity: moderate
    duration_hours: 2.0
    visibility_nm: 1.0
    ceiling_ft: 400
    wind_speed_kt: 5
    wind_direction: 280

  - time: "09:00"
    type: fog
    severity: light
    duration_hours: 2.0
    visibility_nm: 3.0
    ceiling_ft: 1200
    wind_speed_kt: 8
    wind_direction: 290

  - time: "11:00"
    type: clear
    severity: light
    duration_hours: 2.0
    visibility_nm: 10.0
    ceiling_ft: 6000
    wind_speed_kt: 10
    wind_direction: 300

  - time: "13:00"
    type: wind_shift
    severity: moderate
    duration_hours: 4.0
    visibility_nm: 6.0
    ceiling_ft: 8000
    wind_speed_kt: 35
    wind_gusts_kt: 52
    wind_direction: 060

  - time: "17:00"
    type: wind_shift
    severity: moderate
    duration_hours: 4.0
    visibility_nm: 5.0
    ceiling_ft: 6000
    wind_speed_kt: 28
    wind_gusts_kt: 42
    wind_direction: 070

  - time: "21:00"
    type: clear
    severity: light
    duration_hours: 3.0
    visibility_nm: 10.0
    ceiling_ft: 8000
    wind_speed_kt: 15
    wind_direction: 080

runway_events:
  - time: "04:00"
    type: config_change
    runway_config: "27_ILS_only"
    duration_minutes: 300
    reason: Dense fog — CAT III ILS required

  - time: "13:00"
    type: config_change
    runway_config: "27_strong_crosswind"
    duration_minutes: 240
    reason: Santa Ana crosswind component exceeds limits for small aircraft

ground_events:
  - time: "05:00"
    type: gate_failure
    target: "Terminal 2-34"
    duration_hours: 3.0

  - time: "14:00"
    type: taxiway_closure
    target: "Taxiway B (wind debris)"
    duration_hours: 3.0
    impact:
      turnaround_multiplier: 1.3

traffic_modifiers:
  - time: "05:00"
    type: surge
    extra_arrivals: 4
    extra_departures: 2

  - time: "14:00"
    type: diversion
    extra_arrivals: 4
    diversion_origin: LAX
"""),
    "SEA": ("sea_atmospheric_river_windstorm", """\
name: SEA Atmospheric River + Windstorm — Pacific Northwest
description: >
  Powerful atmospheric river makes landfall with an embedded
  extratropical cyclone. Heavy rain and hurricane-force gusts
  to 60kt topple trees and cause power outages. Sea-Tac faces
  extended IFR conditions. Realistic for Oct-Mar.

weather_events:
  - time: "04:00"
    type: rain
    severity: moderate
    duration_hours: 3.0
    visibility_nm: 2.0
    ceiling_ft: 800
    wind_speed_kt: 25
    wind_gusts_kt: 40
    wind_direction: 180

  - time: "07:00"
    type: rain
    severity: severe
    duration_hours: 5.0
    visibility_nm: 0.5
    ceiling_ft: 200
    wind_speed_kt: 45
    wind_gusts_kt: 65
    wind_direction: 190

  - time: "12:00"
    type: rain
    severity: moderate
    duration_hours: 3.0
    visibility_nm: 1.5
    ceiling_ft: 600
    wind_speed_kt: 35
    wind_gusts_kt: 52
    wind_direction: 200

  - time: "15:00"
    type: rain
    severity: light
    duration_hours: 3.0
    visibility_nm: 3.0
    ceiling_ft: 2000
    wind_speed_kt: 22
    wind_gusts_kt: 38
    wind_direction: 210

  - time: "18:00"
    type: clear
    severity: light
    duration_hours: 6.0
    visibility_nm: 8.0
    ceiling_ft: 4000
    wind_speed_kt: 12
    wind_direction: 220

runway_events:
  - time: "07:00"
    type: closure
    runway: "16L"
    duration_minutes: 240
    reason: Windstorm — gusts exceeding 60kt

  - time: "08:00"
    type: closure
    runway: "16R"
    duration_minutes: 180
    reason: Debris on runway from downed trees

ground_events:
  - time: "07:00"
    type: gate_failure
    target: "Concourse A-8"
    duration_hours: 5.0

  - time: "08:00"
    type: taxiway_closure
    target: "Taxiway B (debris/flooding)"
    duration_hours: 6.0
    impact:
      turnaround_multiplier: 1.5

  - time: "10:00"
    type: gate_failure
    target: "Concourse D-4"
    duration_hours: 4.0

traffic_modifiers:
  - time: "07:00"
    type: ground_stop
    duration_hours: 3.0

  - time: "11:00"
    type: diversion
    extra_arrivals: 8
    diversion_origin: PDX
"""),
    "CDG": ("cdg_winter_fog_freezing", """\
name: CDG Winter Fog + Freezing Rain — Northern France
description: >
  Radiation fog blankets the Paris basin overnight, then a warm front
  brings freezing drizzle. CDG's massive dual-terminal operation
  grinds to a halt under CAT IIIb restrictions. De-icing queues
  build across all four runways. Realistic for Nov-Feb.

weather_events:
  - time: "03:00"
    type: fog
    severity: severe
    duration_hours: 3.0
    visibility_nm: 0.12
    ceiling_ft: 50
    wind_speed_kt: 3
    wind_direction: 180

  - time: "06:00"
    type: fog
    severity: moderate
    duration_hours: 2.0
    visibility_nm: 0.5
    ceiling_ft: 200
    wind_speed_kt: 5
    wind_direction: 190

  - time: "08:00"
    type: freezing_rain
    severity: moderate
    duration_hours: 3.0
    visibility_nm: 1.0
    ceiling_ft: 400
    wind_speed_kt: 10
    wind_direction: 200

  - time: "11:00"
    type: freezing_rain
    severity: light
    duration_hours: 2.0
    visibility_nm: 2.0
    ceiling_ft: 1000
    wind_speed_kt: 12
    wind_direction: 220

  - time: "13:00"
    type: rain
    severity: light
    duration_hours: 3.0
    visibility_nm: 4.0
    ceiling_ft: 2000
    wind_speed_kt: 15
    wind_direction: 240

  - time: "16:00"
    type: clear
    severity: light
    duration_hours: 8.0
    visibility_nm: 10.0
    ceiling_ft: 5000
    wind_speed_kt: 8
    wind_direction: 260

runway_events:
  - time: "03:00"
    type: config_change
    runway_config: "27R_only"
    duration_minutes: 300
    reason: CAT IIIb fog — single runway autoland only

  - time: "08:00"
    type: closure
    runway: "27L"
    duration_minutes: 180
    reason: Freezing rain — ice on runway

ground_events:
  - time: "06:00"
    type: deicing_required
    duration_hours: 8.0
    impact:
      turnaround_multiplier: 1.7

  - time: "04:00"
    type: gate_failure
    target: "Terminal 2E-K46"
    duration_hours: 5.0

  - time: "08:00"
    type: taxiway_closure
    target: "Taxiway Y (ice)"
    duration_hours: 4.0
    impact:
      turnaround_multiplier: 1.4

traffic_modifiers:
  - time: "04:00"
    type: surge
    extra_arrivals: 8
    extra_departures: 6

  - time: "09:00"
    type: diversion
    extra_arrivals: 10
    diversion_origin: ORY
"""),
    "AMS": ("ams_north_sea_storm", """\
name: AMS North Sea Winter Storm — Netherlands
description: >
  Deep low-pressure system over the North Sea drives gale-force
  winds and heavy rain across Schiphol. Gusts exceed 55kt on the
  exposed polder airfield. Crosswind limits reached on multiple
  runway pairs. Water accumulation on the flat terrain. Realistic for Oct-Mar.

weather_events:
  - time: "06:00"
    type: rain
    severity: moderate
    duration_hours: 3.0
    visibility_nm: 3.0
    ceiling_ft: 1000
    wind_speed_kt: 30
    wind_gusts_kt: 45
    wind_direction: 260

  - time: "09:00"
    type: rain
    severity: severe
    duration_hours: 4.0
    visibility_nm: 1.0
    ceiling_ft: 400
    wind_speed_kt: 42
    wind_gusts_kt: 58
    wind_direction: 270

  - time: "13:00"
    type: rain
    severity: moderate
    duration_hours: 3.0
    visibility_nm: 2.0
    ceiling_ft: 800
    wind_speed_kt: 35
    wind_gusts_kt: 50
    wind_direction: 280

  - time: "16:00"
    type: rain
    severity: light
    duration_hours: 3.0
    visibility_nm: 4.0
    ceiling_ft: 2000
    wind_speed_kt: 25
    wind_gusts_kt: 38
    wind_direction: 290

  - time: "19:00"
    type: clear
    severity: light
    duration_hours: 5.0
    visibility_nm: 8.0
    ceiling_ft: 4000
    wind_speed_kt: 18
    wind_direction: 300

runway_events:
  - time: "09:00"
    type: closure
    runway: "18R"
    duration_minutes: 180
    reason: Crosswind exceeds limits

  - time: "10:00"
    type: closure
    runway: "27"
    duration_minutes: 120
    reason: Standing water — hydroplaning risk

ground_events:
  - time: "09:00"
    type: gate_failure
    target: "Pier D-52"
    duration_hours: 4.0

  - time: "10:00"
    type: taxiway_closure
    target: "Taxiway V (flooding)"
    duration_hours: 5.0
    impact:
      turnaround_multiplier: 1.4

  - time: "12:00"
    type: gate_failure
    target: "Pier E-18"
    duration_hours: 3.0

traffic_modifiers:
  - time: "09:00"
    type: surge
    extra_arrivals: 6
    extra_departures: 4

  - time: "11:00"
    type: diversion
    extra_arrivals: 10
    diversion_origin: BRU
"""),
    "HKG": ("hkg_typhoon_signal8", """\
name: HKG Typhoon Signal 8 — South China Sea
description: >
  Typhoon passes within 100km of Hong Kong, triggering Signal 8
  hoisting. HKIA suspends all flights. Wind gusts exceed 80kt.
  Massive passenger stranding as hundreds of flights cancel.
  Recovery takes 12+ hours after signal lowered. Realistic for Jun-Oct.

weather_events:
  - time: "06:00"
    type: rain
    severity: moderate
    duration_hours: 3.0
    visibility_nm: 2.0
    ceiling_ft: 800
    wind_speed_kt: 35
    wind_gusts_kt: 50
    wind_direction: 090

  - time: "09:00"
    type: rain
    severity: severe
    duration_hours: 6.0
    visibility_nm: 0.25
    ceiling_ft: 100
    wind_speed_kt: 60
    wind_gusts_kt: 85
    wind_direction: 100

  - time: "15:00"
    type: rain
    severity: moderate
    duration_hours: 3.0
    visibility_nm: 1.0
    ceiling_ft: 400
    wind_speed_kt: 40
    wind_gusts_kt: 58
    wind_direction: 150

  - time: "18:00"
    type: rain
    severity: light
    duration_hours: 3.0
    visibility_nm: 3.0
    ceiling_ft: 1500
    wind_speed_kt: 25
    wind_gusts_kt: 40
    wind_direction: 180

  - time: "21:00"
    type: clear
    severity: light
    duration_hours: 3.0
    visibility_nm: 8.0
    ceiling_ft: 4000
    wind_speed_kt: 15
    wind_direction: 200

runway_events:
  - time: "09:00"
    type: closure
    runway: "07L"
    duration_minutes: 420
    reason: Typhoon Signal 8 — airport closed

  - time: "09:00"
    type: closure
    runway: "07R"
    duration_minutes: 420
    reason: Typhoon Signal 8 — airport closed

ground_events:
  - time: "08:00"
    type: taxiway_closure
    target: "Taxiway N (flooding)"
    duration_hours: 10.0
    impact:
      turnaround_multiplier: 2.0

  - time: "09:00"
    type: gate_failure
    target: "Terminal 1-Gate 40"
    duration_hours: 8.0

  - time: "10:00"
    type: gate_failure
    target: "Terminal 1-Gate 65"
    duration_hours: 7.0

traffic_modifiers:
  - time: "08:00"
    type: ground_stop
    duration_hours: 9.0

  - time: "18:00"
    type: diversion
    extra_arrivals: 15
    diversion_origin: MFM
"""),
    "ICN": ("icn_monsoon_typhoon", """\
name: ICN Summer Monsoon + Typhoon — Korean Peninsula
description: >
  Changma monsoon season brings persistent heavy rain, then a
  weakening typhoon tracks up the Yellow Sea adding gusty winds.
  Low ceilings and visibility persist for hours. Incheon's exposed
  island location amplifies wind effects. Realistic for Jun-Sep.

weather_events:
  - time: "04:00"
    type: rain
    severity: moderate
    duration_hours: 4.0
    visibility_nm: 2.0
    ceiling_ft: 600
    wind_speed_kt: 20
    wind_gusts_kt: 32
    wind_direction: 200

  - time: "08:00"
    type: rain
    severity: severe
    duration_hours: 5.0
    visibility_nm: 0.5
    ceiling_ft: 200
    wind_speed_kt: 40
    wind_gusts_kt: 58
    wind_direction: 210

  - time: "13:00"
    type: thunderstorm
    severity: severe
    duration_hours: 3.0
    visibility_nm: 0.25
    ceiling_ft: 200
    wind_speed_kt: 50
    wind_gusts_kt: 70
    wind_direction: 230

  - time: "16:00"
    type: rain
    severity: moderate
    duration_hours: 3.0
    visibility_nm: 1.5
    ceiling_ft: 600
    wind_speed_kt: 30
    wind_gusts_kt: 45
    wind_direction: 250

  - time: "19:00"
    type: rain
    severity: light
    duration_hours: 3.0
    visibility_nm: 4.0
    ceiling_ft: 2000
    wind_speed_kt: 18
    wind_direction: 270

  - time: "22:00"
    type: clear
    severity: light
    duration_hours: 2.0
    visibility_nm: 8.0
    ceiling_ft: 4000
    wind_speed_kt: 10
    wind_direction: 280

runway_events:
  - time: "08:00"
    type: closure
    runway: "15L"
    duration_minutes: 300
    reason: Typhoon approach — wind exceeds limits

  - time: "09:00"
    type: closure
    runway: "15R"
    duration_minutes: 240
    reason: Standing water and poor visibility

ground_events:
  - time: "06:00"
    type: taxiway_closure
    target: "Taxiway A (flooding)"
    duration_hours: 10.0
    impact:
      turnaround_multiplier: 1.7

  - time: "08:00"
    type: gate_failure
    target: "Terminal 2-248"
    duration_hours: 6.0

  - time: "13:00"
    type: gate_failure
    target: "Terminal 1-118"
    duration_hours: 4.0

traffic_modifiers:
  - time: "08:00"
    type: ground_stop
    duration_hours: 6.0

  - time: "15:00"
    type: diversion
    extra_arrivals: 10
    diversion_origin: GMP
"""),
}


def _root() -> Path:
    """Repository root (parent of scripts/)."""
    return Path(__file__).resolve().parent.parent


def generate_normal_configs(root: Path) -> list[tuple[str, str, str]]:
    """Generate 99 normal-day config YAMLs.

    Returns list of (iata, task_key, config_path) tuples.
    """
    out_dir = root / "configs" / "calibration_batch"
    out_dir.mkdir(parents=True, exist_ok=True)

    tasks = []
    for iata in AIRPORTS:
        iata_lower = iata.lower()
        for idx, seed in enumerate([100, 200, 300], start=1):
            tag = f"normal_d{idx}"
            task_key = f"cal_{iata_lower}_{tag}"
            config_rel = f"configs/calibration_batch/simulation_{iata_lower}_{tag}.yaml"
            output_file = f"simulation_output/calibrated/cal_{iata_lower}_{tag}.json"

            content = (
                f"airport: {iata}\n"
                f"arrivals: 500\n"
                f"departures: 500\n"
                f"duration_hours: 36\n"
                f"time_step_seconds: 2.0\n"
                f"seed: {seed}\n"
                f"output_file: {output_file}\n"
            )
            (out_dir / f"simulation_{iata_lower}_{tag}.yaml").write_text(content)
            tasks.append((iata, task_key, config_rel))

    return tasks


def generate_weather_scenarios(root: Path) -> None:
    """Generate 23 new weather scenario YAMLs."""
    out_dir = root / "scenarios"
    out_dir.mkdir(parents=True, exist_ok=True)

    for iata, (filename, content) in NEW_SCENARIOS.items():
        path = out_dir / f"{filename}.yaml"
        path.write_text(content)
        print(f"  scenario: {path.relative_to(root)}")


def get_scenario_file(iata: str) -> str:
    """Get scenario file path for an airport."""
    if iata in EXISTING_SCENARIOS:
        return EXISTING_SCENARIOS[iata]
    if iata in NEW_SCENARIOS:
        return f"scenarios/{NEW_SCENARIOS[iata][0]}.yaml"
    raise ValueError(f"No scenario file for {iata}")


def generate_weather_configs(root: Path) -> list[tuple[str, str, str]]:
    """Generate 33 weather config YAMLs.

    Returns list of (iata, task_key, config_path) tuples.
    """
    out_dir = root / "configs" / "calibration_batch"
    out_dir.mkdir(parents=True, exist_ok=True)

    tasks = []
    for iata in AIRPORTS:
        iata_lower = iata.lower()
        task_key = f"cal_{iata_lower}_weather"
        config_rel = f"configs/calibration_batch/simulation_{iata_lower}_weather.yaml"
        output_file = f"simulation_output/calibrated/cal_{iata_lower}_weather.json"
        scenario = get_scenario_file(iata)

        content = (
            f"airport: {iata}\n"
            f"arrivals: 500\n"
            f"departures: 500\n"
            f"duration_hours: 36\n"
            f"time_step_seconds: 2.0\n"
            f"seed: 42\n"
            f"output_file: {output_file}\n"
            f"scenario_file: {scenario}\n"
        )
        (out_dir / f"simulation_{iata_lower}_weather.yaml").write_text(content)
        tasks.append((iata, task_key, config_rel))

    return tasks


def generate_job_yaml(
    root: Path,
    normal_tasks: list[tuple[str, str, str]],
    weather_tasks: list[tuple[str, str, str]],
) -> None:
    """Generate resources/calibration_batch_job.yml.

    Uses inline parameters instead of config_file references so that
    configs/calibration_batch/ does not need to be synced to workspace.
    """
    lines = [
        "resources:",
        "  jobs:",
        "    calibration_batch:",
        '      name: "[${bundle.target}] Airport DT - Calibration Batch (132 sims)"',
        '      description: "33 airports x 4 runs each (3 normal + 1 weather), 36h duration, calibrated profiles"',
        "",
        "      tasks:",
    ]

    # Normal-day tasks (no scenario file)
    for iata, task_key, _config_rel in normal_tasks:
        iata_lower = iata.lower()
        # Extract seed from task_key: cal_{iata}_normal_d{N} -> seed = N*100
        day_num = int(task_key.split("_d")[-1])
        seed = day_num * 100
        output = f"simulation_output/calibrated/cal_{iata_lower}_normal_d{day_num}.json"

        lines.append(f"        - task_key: {task_key}")
        lines.append("          notebook_task:")
        lines.append(
            "            notebook_path: ../databricks/notebooks/run_simulation_airport.py"
        )
        lines.append("            base_parameters:")
        lines.append(f'              airport: "{iata}"')
        lines.append(f'              arrivals: "500"')
        lines.append(f'              departures: "500"')
        lines.append(f'              duration_hours: "36"')
        lines.append(f'              time_step_seconds: "2.0"')
        lines.append(f'              seed: "{seed}"')
        lines.append(f'              output_file: "{output}"')
        lines.append("")

    # Weather tasks (with scenario file)
    for iata, task_key, _config_rel in weather_tasks:
        iata_lower = iata.lower()
        output = f"simulation_output/calibrated/cal_{iata_lower}_weather.json"
        scenario = get_scenario_file(iata)

        lines.append(f"        - task_key: {task_key}")
        lines.append("          notebook_task:")
        lines.append(
            "            notebook_path: ../databricks/notebooks/run_simulation_airport.py"
        )
        lines.append("            base_parameters:")
        lines.append(f'              airport: "{iata}"')
        lines.append(f'              arrivals: "500"')
        lines.append(f'              departures: "500"')
        lines.append(f'              duration_hours: "36"')
        lines.append(f'              time_step_seconds: "2.0"')
        lines.append(f'              seed: "42"')
        lines.append(f'              output_file: "{output}"')
        lines.append(f'              scenario_file: "{scenario}"')
        lines.append("")

    lines.append("      tags:")
    lines.append("        project: airport-digital-twin")
    lines.append("        component: calibration-batch")
    lines.append("        target: ${bundle.target}")
    lines.append("")
    lines.append("      timeout_seconds: 7200")
    lines.append("")

    (root / "resources" / "calibration_batch_job.yml").write_text("\n".join(lines))


def main() -> None:
    root = _root()
    print(f"Repository root: {root}")
    print(f"Airports: {len(AIRPORTS)}")
    print()

    print("Generating 23 new weather scenarios...")
    generate_weather_scenarios(root)
    print()

    print("Generating 99 normal-day configs...")
    normal_tasks = generate_normal_configs(root)
    print(f"  Created {len(normal_tasks)} configs")
    print()

    print("Generating 33 weather configs...")
    weather_tasks = generate_weather_configs(root)
    print(f"  Created {len(weather_tasks)} configs")
    print()

    print("Generating job YAML...")
    generate_job_yaml(root, normal_tasks, weather_tasks)
    print(f"  resources/calibration_batch_job.yml")
    print()

    total = len(normal_tasks) + len(weather_tasks)
    print(f"Done! {total} simulation tasks generated.")
    print(f"  Normal-day: {len(normal_tasks)} (3 per airport, seeds 100/200/300)")
    print(f"  Weather:    {len(weather_tasks)} (1 per airport, seed 42)")
    print()
    print("Next steps:")
    print("  databricks bundle deploy --target dev")
    print("  databricks bundle run calibration_batch --target dev")


if __name__ == "__main__":
    main()
