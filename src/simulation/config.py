"""Simulation configuration model and loader."""

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field


class SimulationConfig(BaseModel):
    """Configuration for a simulation run."""

    airport: str = Field(default="SFO", description="IATA airport code")
    arrivals: int = Field(default=25, description="Number of arriving flights")
    departures: int = Field(default=25, description="Number of departing flights")
    duration_hours: float = Field(default=24.0, description="Simulation duration in hours")
    time_step_seconds: float = Field(default=2.0, description="Simulated seconds per tick")
    time_acceleration: float = Field(
        default=3600.0,
        description="Informational: 1 real second = N sim seconds (for progress display)",
    )
    start_time: Optional[datetime] = Field(
        default=None,
        description="Simulation start time (defaults to midnight UTC today)",
    )
    seed: Optional[int] = Field(default=None, description="Random seed for reproducibility")
    debug: bool = Field(default=False, description="Debug mode: 4h duration, verbose logging")
    output_file: str = Field(
        default="simulation_output.json", description="Output file path"
    )
    scenario_file: Optional[str] = Field(
        default=None, description="Path to scenario YAML file for disruption injection"
    )

    def effective_start_time(self) -> datetime:
        """Return start_time or midnight UTC today."""
        if self.start_time is not None:
            return self.start_time
        now = datetime.now(timezone.utc)
        return now.replace(hour=0, minute=0, second=0, microsecond=0)

    def effective_duration_hours(self) -> float:
        """Return duration, overridden to 4h in debug mode."""
        if self.debug:
            return min(self.duration_hours, 4.0)
        return self.duration_hours


def load_config(path: str) -> SimulationConfig:
    """Load simulation config from a YAML file."""
    import yaml

    with open(path) as f:
        data = yaml.safe_load(f) or {}
    return SimulationConfig(**data)
