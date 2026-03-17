#!/usr/bin/env python3
"""Generate simulation YAML configs for all known-profile airports.

Creates one config per airport for 7-day simulations (168 hours).
Start date is Monday 2025-06-16 so the 7-day span covers all days of the week.

Usage:
    python scripts/generate_sim_configs.py          # generate 7-day configs
    python scripts/generate_sim_configs.py --days 1  # generate 1-day configs
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

# Add project root to path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.calibration.known_profiles import list_known_airports  # noqa: E402

# Map airports to their scenario files (where they exist)
SCENARIO_MAP: dict[str, str] = {
    "SFO": "scenarios/sfo_summer_thunderstorm.yaml",
    "JFK": "scenarios/jfk_winter_storm.yaml",
    "ATL": "scenarios/atl_summer_thunderstorm.yaml",
    "ORD": "scenarios/ord_winter_blizzard.yaml",
    "LAX": "scenarios/lax_santa_ana_winds.yaml",
    "DFW": "scenarios/dfw_tornado_outbreak.yaml",
    "DEN": "scenarios/den_spring_blizzard.yaml",
    "SEA": "scenarios/sea_atmospheric_river_windstorm.yaml",
    "MIA": "scenarios/mia_tropical_storm.yaml",
    "EWR": "scenarios/ewr_ice_storm.yaml",
    "BOS": "scenarios/bos_noreaster.yaml",
    "PHX": "scenarios/phx_extreme_heat_dust.yaml",
    "LAS": "scenarios/las_haboob.yaml",
    "MCO": "scenarios/mco_thunderstorm_complex.yaml",
    "CLT": "scenarios/clt_derecho.yaml",
    "MSP": "scenarios/msp_arctic_blast.yaml",
    "DTW": "scenarios/dtw_lake_effect_blizzard.yaml",
    "PHL": "scenarios/phl_summer_thunderstorm.yaml",
    "IAH": "scenarios/iah_hurricane_approach.yaml",
    "SAN": "scenarios/san_marine_santa_ana.yaml",
    "PDX": "scenarios/pdx_atmospheric_river.yaml",
    "LHR": "scenarios/lhr_winter_fog.yaml",
    "DXB": "scenarios/dxb_sandstorm.yaml",
    "NRT": "scenarios/nrt_typhoon.yaml",
    "SIN": "scenarios/sin_monsoon.yaml",
    "HKG": "scenarios/hkg_typhoon_signal8.yaml",
    "CDG": "scenarios/cdg_winter_fog_freezing.yaml",
    "FRA": "scenarios/fra_winter_crosswind.yaml",
    "AMS": "scenarios/ams_north_sea_storm.yaml",
    "SYD": "scenarios/syd_bushfire_smoke.yaml",
    "ICN": "scenarios/icn_monsoon_typhoon.yaml",
    "GRU": "scenarios/gru_tropical_storm.yaml",
    "JNB": "scenarios/jnb_summer_thunderstorm.yaml",
}


def generate_configs(days: int = 7) -> list[Path]:
    """Generate YAML configs for all known airports."""
    airports = list_known_airports()
    duration_hours = days * 24
    suffix = f"{days}day" if days > 1 else "1000"
    configs_dir = ROOT / "configs"
    configs_dir.mkdir(exist_ok=True)

    created = []
    for iata in airports:
        flights_per_day = 1000
        total_flights = flights_per_day * days
        arrivals = total_flights // 2
        departures = total_flights - arrivals

        config = {
            "airport": iata,
            "start_date": "2025-06-16",  # Monday
            "arrivals": arrivals,
            "departures": departures,
            "duration_hours": duration_hours,
            "time_step_seconds": 10.0 if days > 1 else 2.0,
            "seed": 42,
            "output_file": f"simulation_output/simulation_{iata.lower()}_{suffix}.json",
        }

        # Add scenario if available
        scenario = SCENARIO_MAP.get(iata)
        if scenario and (ROOT / scenario).exists():
            config["scenario_file"] = scenario

        out_path = configs_dir / f"simulation_{iata.lower()}_{suffix}.yaml"
        with open(out_path, "w") as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)

        created.append(out_path)
        print(f"  {out_path.name}")

    return created


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate simulation configs")
    parser.add_argument("--days", type=int, default=7, help="Simulation duration in days")
    args = parser.parse_args()

    print(f"Generating {args.days}-day configs for all known airports...")
    configs = generate_configs(days=args.days)
    print(f"\nCreated {len(configs)} config files in configs/")


if __name__ == "__main__":
    main()
