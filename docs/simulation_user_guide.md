# Simulation Mode — User Guide

Run a deterministic, accelerated simulation of airport operations that produces a structured JSON event log.

## Quick Start

```bash
# Debug mode (4h, 20 flights, ~0.2s)
python -m src.simulation.cli --config configs/simulation_sfo_50_debug.yaml

# Full day (24h, 50 flights, ~5s)
python -m src.simulation.cli --config configs/simulation_sfo_50.yaml

# Custom via CLI args
python -m src.simulation.cli --airport SFO --arrivals 50 --departures 50 --seed 42
```

## Configuration

### YAML Config File

```yaml
airport: SFO             # IATA code
arrivals: 25             # Number of arriving flights
departures: 25           # Number of departing flights
duration_hours: 24       # Simulation duration
time_step_seconds: 2.0   # Physics tick interval (sim-seconds)
seed: 42                 # Random seed for reproducibility
debug: false             # Debug mode limits to 4h + verbose logs
output_file: output.json # Where to write results
```

### CLI Arguments

All config fields can be overridden via CLI:

| Flag | Description |
|------|-------------|
| `--config` | Path to YAML config file |
| `--airport` | IATA airport code |
| `--arrivals` | Number of arrivals |
| `--departures` | Number of departures |
| `--duration` | Duration in hours |
| `--time-step` | Time step in seconds |
| `--seed` | Random seed |
| `--output` | Output file path |
| `--debug` | Enable debug mode |

CLI args override values from the config file.

## Output Format

The simulation writes a JSON file with this structure:

```json
{
  "config": { ... },
  "summary": {
    "total_flights": 50,
    "arrivals": 25,
    "departures": 25,
    "avg_delay_min": 8.2,
    "on_time_pct": 85.0,
    "avg_turnaround_min": 45.3,
    "peak_simultaneous_flights": 12,
    "gate_utilization_gates_used": 15,
    "total_position_snapshots": 73460,
    "total_phase_transitions": 274,
    "total_gate_events": 25,
    "total_weather_snapshots": 24,
    "total_baggage_events": 25
  },
  "schedule": [ ... ],
  "position_snapshots": [ ... ],
  "phase_transitions": [ ... ],
  "gate_events": [ ... ],
  "baggage_events": [ ... ],
  "weather_snapshots": [ ... ]
}
```

### Event Types

- **position_snapshots**: Aircraft position every 30 sim-seconds (lat, lon, alt, velocity, heading, phase)
- **phase_transitions**: Every phase change (approaching → landing → taxi → parked → pushback → taxi → takeoff → departing)
- **gate_events**: Gate assign/occupy/release events
- **baggage_events**: Per-flight baggage generation when aircraft reaches PARKED
- **weather_snapshots**: Hourly METAR weather observations
- **schedule**: The complete flight schedule with delays

## How It Works

1. **Schedule generation**: Flights are distributed across the duration using the existing peak-hour pattern (6-9am, 4-7pm peaks)
2. **State machine**: Reuses the production flight state machine from `fallback.py` — same phase transitions, separation rules, wake turbulence, and physics
3. **Virtual clock**: Time advances by `time_step_seconds` each tick. No `datetime.now()` calls — everything is keyed to sim_time
4. **Deterministic**: Set `seed` for reproducible results. Same seed = same schedule, same flight paths

## Performance

| Config | Flights | Duration | Wall Time |
|--------|---------|----------|-----------|
| Debug  | 20      | 4h       | ~0.2s     |
| Full   | 50      | 24h      | ~5s       |
| Large  | 200     | 24h      | ~20s      |

## Tests

```bash
uv run pytest tests/test_simulation.py -v
```

20 tests covering config, recorder, engine, and integration scenarios.
