"""CLI entry point for running airport simulations.

Usage:
    python -m src.simulation.cli --config configs/simulation_sfo_50.yaml
    python -m src.simulation.cli --airport SFO --arrivals 25 --departures 25 --debug
    python -m src.simulation.cli --airport SFO --arrivals 50 --departures 50 --scenario scenarios/sfo_summer_thunderstorm.yaml --report
"""

import argparse
import json
import logging
import sys

from src.simulation.config import SimulationConfig, load_config
from src.simulation.engine import SimulationEngine
from src.ingestion.fallback import get_airport_center


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
    parser.add_argument(
        "--skip-positions", action="store_true",
        help="Skip position snapshots to save memory (batch/ML training mode)",
    )
    parser.add_argument(
        "--report", action="store_true",
        help="Generate LLM analysis report after simulation completes",
    )
    parser.add_argument(
        "--report-prompt", type=str,
        help="Path to custom report prompt template file",
    )

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
    if args.skip_positions:
        config.skip_positions = True
    if args.report:
        config.generate_report = True
    if args.report_prompt:
        config.report_prompt_file = args.report_prompt

    # Configure logging
    level = logging.DEBUG if config.debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # Run simulation
    engine = SimulationEngine(config)
    recorder = engine.run()

    # Write output (compatible with both Pydantic v1 and v2)
    if hasattr(config, "model_dump"):
        config_dict = config.model_dump(mode="json")
    else:
        config_dict = config.dict()
    center = get_airport_center()
    config_dict["airport_center"] = {"latitude": center[0], "longitude": center[1]}
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
        print(f"  Go-arounds:             {summary.get('total_go_arounds', 0)}")
        print(f"  Diversions:             {summary.get('total_diversions', 0)}")
        print(f"  Holdings:               {summary.get('total_holdings', 0)}")
        print(f"  Cancellations:          {summary.get('total_cancellations', 0)}")
    print(f"\n  Output: {config.output_file}")

    # Generate report if requested
    if config.generate_report:
        _generate_report(config, engine)


def _generate_report(config: SimulationConfig, engine: SimulationEngine) -> None:
    """Generate LLM analysis report after simulation."""
    from src.simulation.report_generator import (
        ReportGenerator,
        derive_report_path,
        get_databricks_auth,
    )

    # Determine prompt source: scenario override > config file > default
    prompt_template = None
    prompt_file = config.report_prompt_file

    if engine.scenario:
        if engine.scenario.report_prompt:
            prompt_template = engine.scenario.report_prompt
        elif engine.scenario.report_prompt_file and not prompt_file:
            prompt_file = engine.scenario.report_prompt_file

    try:
        generator = ReportGenerator(
            prompt_template=prompt_template,
            prompt_file=prompt_file,
        )
    except FileNotFoundError as e:
        print(f"\n  Report generation skipped: {e}", file=sys.stderr)
        return

    # Load the simulation output we just wrote
    try:
        with open(config.output_file) as f:
            simulation_output = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"\n  Report generation failed (cannot read output): {e}", file=sys.stderr)
        return

    # Get auth and generate
    try:
        host, token = get_databricks_auth()
    except RuntimeError as e:
        print(f"\n  Report generation skipped (no auth): {e}", file=sys.stderr)
        return

    try:
        report_content = generator.generate_sync(simulation_output, host, token)
    except Exception as e:
        print(f"\n  Report generation failed: {e}", file=sys.stderr)
        return

    # Write report
    report_path = derive_report_path(config.output_file)
    from pathlib import Path
    Path(report_path).parent.mkdir(parents=True, exist_ok=True)
    Path(report_path).write_text(report_content, encoding="utf-8")
    print(f"  Report: {report_path}")


if __name__ == "__main__":
    main()
