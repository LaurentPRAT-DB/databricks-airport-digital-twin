"""Per-run calibration parameters for the flight lifecycle simulation."""

from dataclasses import dataclass, field
from typing import Dict


@dataclass
class SimCalibration:
    """Per-run calibration parameters set by the simulation engine."""

    gate_minutes: float = 0.0
    taxi_out_target_s: float = 0.0
    taxi_out_waypoint_s: float = 0.0
    taxi_out_p95_s: float = 0.0
    taxi_in_target_s: float = 0.0
    taxi_in_waypoint_s: float = 0.0
    taxi_in_p95_s: float = 0.0
    weather_wind_kts: float = 0.0
    weather_visibility_sm: float = 10.0
    gate_last_delay: Dict[str, float] = field(default_factory=dict)
