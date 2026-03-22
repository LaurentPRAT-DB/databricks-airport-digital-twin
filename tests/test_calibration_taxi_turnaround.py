"""Validate that BTS OTP taxi and turnaround data flows through the calibration pipeline."""

import json
from pathlib import Path

import pytest

PROFILES_DIR = Path(__file__).resolve().parent.parent / "data" / "calibration" / "profiles"


class TestSFOProfileCalibration:
    """Verify KSFO profile has realistic taxi/turnaround stats from BTS OTP."""

    @pytest.fixture(autouse=True)
    def load_profile(self):
        path = PROFILES_DIR / "KSFO.json"
        if not path.exists():
            pytest.skip("KSFO profile not built yet")
        self.profile = json.loads(path.read_text())

    def test_taxi_out_mean_realistic(self):
        """SFO taxi-out mean should be 15-30 min (real ~20 min)."""
        val = self.profile.get("taxi_out_mean_min", 0)
        assert 15 <= val <= 30, f"taxi_out_mean_min={val}, expected 15-30"

    def test_taxi_out_p95_realistic(self):
        """SFO taxi-out P95 should be 25-50 min (real ~36 min)."""
        val = self.profile.get("taxi_out_p95_min", 0)
        assert 25 <= val <= 50, f"taxi_out_p95_min={val}, expected 25-50"

    def test_taxi_in_mean_realistic(self):
        """SFO taxi-in mean should be 5-15 min (real ~8.5 min)."""
        val = self.profile.get("taxi_in_mean_min", 0)
        assert 5 <= val <= 15, f"taxi_in_mean_min={val}, expected 5-15"

    def test_turnaround_median_realistic(self):
        """SFO turnaround median should be 50-100 min (real ~72 min)."""
        val = self.profile.get("turnaround_median_min", 0)
        assert 50 <= val <= 100, f"turnaround_median_min={val}, expected 50-100"

    def test_turnaround_p75_realistic(self):
        """SFO turnaround P75 should be 70-130 min (real ~96 min)."""
        val = self.profile.get("turnaround_p75_min", 0)
        assert 70 <= val <= 130, f"turnaround_p75_min={val}, expected 70-130"


class TestCalibratedTurnaround:
    """Verify the calibrated turnaround function uses profile data."""

    def test_uses_profile_when_available(self):
        from src.calibration.profile import AirportProfile
        from src.simulation.engine import _calibrated_turnaround

        profile = AirportProfile(icao_code="KTEST", iata_code="TST", turnaround_median_min=70.0)
        result = _calibrated_turnaround("A320", "UAL", profile)
        # Should be around 70 min * 1.0 (UAL factor) * ±15% jitter = 59.5-80.5
        assert 50 <= result <= 90, f"Calibrated turnaround={result:.1f}, expected 50-90"

    def test_falls_back_to_dag_without_profile(self):
        from src.calibration.profile import AirportProfile
        from src.simulation.engine import _calibrated_turnaround

        profile = AirportProfile(icao_code="KTEST", iata_code="TST", turnaround_median_min=0.0)
        result = _calibrated_turnaround("A320", "UAL", profile)
        # Fallback: DAG critical path includes all 12 phases with ±20% jitter
        # Narrow-body nominal ~45 min, DAG critical path ~55-65 min
        assert 40 <= result <= 75, f"Fallback turnaround={result:.1f}, expected 40-75"

    def test_wide_body_longer_than_narrow(self):
        from src.calibration.profile import AirportProfile
        from src.simulation.engine import _calibrated_turnaround

        profile = AirportProfile(icao_code="KTEST", iata_code="TST", turnaround_median_min=70.0)
        narrow_times = [_calibrated_turnaround("A320", "UAL", profile) for _ in range(50)]
        wide_times = [_calibrated_turnaround("B777", "UAL", profile) for _ in range(50)]
        assert sum(wide_times) / len(wide_times) > sum(narrow_times) / len(narrow_times), (
            "Wide-body should have longer average turnaround than narrow-body"
        )


class TestPhysicsTurnaroundCalibration:
    """Verify the physics engine respects calibration override."""

    def test_calibrated_gate_time_longer_than_default(self):
        from src.ingestion.fallback import (
            _create_new_flight, _update_flight_state, _flight_states,
            FlightPhase, set_calibration_gate_minutes,
        )

        # With calibration: 70 min median → aircraft should still be parked at 45 min
        set_calibration_gate_minutes(70.0)
        try:
            flight = _create_new_flight(
                "cal_test", "UAL100", FlightPhase.PARKED,
                origin="JFK", destination="SFO",
            )
            _flight_states["cal_test"] = flight
            flight.time_at_gate = 0
            flight.aircraft_type = "A320"

            # Simulate 45 minutes
            for _ in range(2700):
                _update_flight_state(flight, 1.0)

            assert flight.phase == FlightPhase.PARKED, (
                "With 70-min calibration, A320 should still be parked at 45 min"
            )
        finally:
            set_calibration_gate_minutes(0)
            _flight_states.pop("cal_test", None)
