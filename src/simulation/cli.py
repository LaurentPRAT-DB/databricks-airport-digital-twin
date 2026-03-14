"""CLI entry point for running airport simulations.

Usage:
    python -m src.simulation.cli --config configs/simulation_sfo_50.yaml
    python -m src.simulation.cli --airport SFO --arrivals 25 --departures 25 --debug
"""

import argparse
import logging
import sys

from src.simulation.config import SimulationConfig, load_config
from src.simulation.engine import SimulationEngine


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Airport Digital Twin — Standalone Simulation Mode",
    )
    parser.add_argument(
        "--config", type=str, help="Path to YAML config file",
    )
    parser.add_argument("--airport", type=str, help="IATA airport code")
    parser.add_argument("--arrivals", type=int, help="Number of arrivals")
    parser.add_argument("--departures", type=int, help="Number of departures")
    parser.add_argument("--duration", type=float, help="Duration in hours")
    parser.add_argument("--time-step", type=float, help="Time step in seconds")
    parser.add_argument("--seed", type=int, help="Random seed")
    parser.add_argument("--output", type=str, help="Output file path")
    parser.add_argument("--scenario", type=str, help="Path to scenario YAML file")
    parser.add_argument("--debug", action="store_true", help="Debug mode (4h, verbose)")

    args = parser.parse_args()

    # Load config from file or build from args
    if args.config:
        config = load_config(args.config)
    else:
        config = SimulationConfig()

    # Override with CLI args
    if args.airport:
        config.airport = args.airport
    if args.arrivals is not None:
        config.arrivals = args.arrivals
    if args.departures is not None:
        config.departures = args.departures
    if args.duration is not None:
        config.duration_hours = args.duration
    if args.time_step is not None:
        config.time_step_seconds = args.time_step
    if args.seed is not None:
        config.seed = args.seed
    if args.output:
        config.output_file = args.output
    if args.scenario:
        config.scenario_file = args.scenario
    if args.debug:
        config.debug = True

    # Configure logging
    level = logging.DEBUG if config.debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # Run simulation
    engine = SimulationEngine(config)
    recorder = engine.run()

    # Write output
    config_dict = config.model_dump(mode="json")
    recorder.write_output(config.output_file, config_dict)

    # Print summary
    summary = recorder.compute_summary(config_dict)
    print(f"\nSimulation Summary:")
    print(f"  Total flights:          {summary['total_flights']}")
    print(f"  Arrivals:               {summary['arrivals']}")
    print(f"  Departures:             {summary['departures']}")
    print(f"  Schedule delay (avg):   {summary['schedule_delay_min']} min")
    print(f"  Capacity hold (avg):    {summary['avg_capacity_hold_min']} min")
    print(f"  Capacity hold (max):    {summary['max_capacity_hold_min']} min")
    print(f"  On-time:                {summary['on_time_pct']}%")
    print(f"  Spawned:                {summary['spawned_count']}/{summary['total_flights']}")
    print(f"  Cancellation rate:      {summary['cancellation_rate_pct']}%")
    print(f"  Avg turnaround:         {summary['avg_turnaround_min']} min")
    print(f"  Peak simultaneous:      {summary['peak_simultaneous_flights']}")
    print(f"  Gates used:             {summary['gate_utilization_gates_used']}")
    print(f"  Position snapshots:     {summary['total_position_snapshots']:,}")
    print(f"  Phase transitions:      {summary['total_phase_transitions']}")
    print(f"  Gate events:            {summary['total_gate_events']}")
    print(f"  Weather snapshots:      {summary['total_weather_snapshots']}")
    if summary.get("scenario_name"):
        print(f"  Scenario:               {summary['scenario_name']}")
        print(f"  Scenario events:        {summary.get('total_scenario_events', 0)}")
        print(f"  Total go-arounds:       {summary.get('total_go_arounds', 0)}")
        print(f"  Total holdings:         {summary.get('total_holdings', 0)}")
    print(f"\n  Output: {config.output_file}")


if __name__ == "__main__":
    main()
