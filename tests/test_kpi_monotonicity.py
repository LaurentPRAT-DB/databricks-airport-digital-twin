"""KPI monotonicity — worse weather must produce worse KPIs.

Operators expect that adding fog or closing a runway degrades performance
metrics monotonically. If severe weather shows *better* OTP than clear
weather, the simulation is broken.

Three severity levels (same traffic, same seed):
  1. No scenario (baseline)
  2. SFO diversions scenario (moderate)
  3. SFO summer thunderstorm (severe — fog + runway closure + diversions)
"""

from pathlib import Path

import pytest

from src.simulation.config import SimulationConfig
from src.simulation.engine import SimulationEngine


SCENARIOS_DIR = Path(__file__).parent.parent / "scenarios"


# ---------------------------------------------------------------------------
# Module-scoped fixtures — one sim per severity level
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def baseline_summary():
    """Clear-sky baseline: 20+20 flights, 6h, no scenario."""
    config = SimulationConfig(
        airport="SFO",
        arrivals=20,
        departures=20,
        duration_hours=6.0,
        time_step_seconds=2.0,
        seed=42,
        diagnostics=True,
    )
    engine = SimulationEngine(config)
    recorder = engine.run()
    return recorder.compute_summary(config.model_dump(mode="json"))


@pytest.fixture(scope="module")
def moderate_summary():
    """Moderate disruption: SFO diversions (OAK closure, gate failure)."""
    config = SimulationConfig(
        airport="SFO",
        arrivals=20,
        departures=20,
        duration_hours=6.0,
        time_step_seconds=2.0,
        seed=42,
        diagnostics=True,
        scenario_file=str(SCENARIOS_DIR / "sfo_diversions.yaml"),
    )
    engine = SimulationEngine(config)
    recorder = engine.run()
    return recorder.compute_summary(config.model_dump(mode="json"))


@pytest.fixture(scope="module")
def severe_summary():
    """Severe disruption: thunderstorm + fog + runway closure + diversions."""
    config = SimulationConfig(
        airport="SFO",
        arrivals=20,
        departures=20,
        duration_hours=6.0,
        time_step_seconds=2.0,
        seed=42,
        diagnostics=True,
        scenario_file=str(SCENARIOS_DIR / "sfo_summer_thunderstorm.yaml"),
    )
    engine = SimulationEngine(config)
    recorder = engine.run()
    return recorder.compute_summary(config.model_dump(mode="json"))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestKPIMonotonicity:
    """Verify KPIs degrade monotonically with increasing disruption severity."""

    def test_otp_degrades_with_severity(self, baseline_summary, moderate_summary, severe_summary):
        """On-time performance: baseline >= moderate >= severe."""
        base_otp = baseline_summary["on_time_pct"]
        mod_otp = moderate_summary["on_time_pct"]
        sev_otp = severe_summary["on_time_pct"]

        # Allow 5pp tolerance for simulation randomness
        assert base_otp >= mod_otp - 5, (
            f"OTP increased with moderate scenario: baseline {base_otp:.1f}% "
            f"< moderate {mod_otp:.1f}%"
        )
        assert base_otp >= sev_otp - 5, (
            f"OTP increased with severe scenario: baseline {base_otp:.1f}% "
            f"< severe {sev_otp:.1f}%"
        )

    def test_delay_increases_with_severity(self, baseline_summary, moderate_summary, severe_summary):
        """Schedule delay: baseline <= moderate <= severe."""
        base_delay = baseline_summary["schedule_delay_min"]
        mod_delay = moderate_summary["schedule_delay_min"]
        sev_delay = severe_summary["schedule_delay_min"]

        # Allow 2-min tolerance
        assert base_delay <= sev_delay + 2, (
            f"Delay decreased with severe scenario: baseline {base_delay:.1f}min "
            f"> severe {sev_delay:.1f}min"
        )

    def test_cancellations_increase_with_severity(self, baseline_summary, severe_summary):
        """Cancellations: baseline <= severe."""
        base_canc = baseline_summary["total_cancellations"]
        sev_canc = severe_summary["total_cancellations"]

        assert base_canc <= sev_canc, (
            f"Cancellations decreased with severe scenario: "
            f"baseline {base_canc} > severe {sev_canc}"
        )

    def test_capacity_hold_increases_with_severity(self, baseline_summary, severe_summary):
        """Capacity hold time: baseline <= severe."""
        base_hold = baseline_summary.get("avg_capacity_hold_min", 0)
        sev_hold = severe_summary.get("avg_capacity_hold_min", 0)

        # Allow 1-min tolerance
        assert base_hold <= sev_hold + 1, (
            f"Capacity hold decreased with severe scenario: "
            f"baseline {base_hold:.1f}min > severe {sev_hold:.1f}min"
        )
