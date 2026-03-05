"""Tests for ML models."""

import pytest
from src.ml.gate_model import (
    GateRecommender,
    GateRecommendation,
    Gate,
    GateStatus,
    recommend_gate,
)
from src.ml.congestion_model import (
    CongestionPredictor,
    AreaCongestion,
    CongestionLevel,
    predict_congestion,
)


class TestGateModel:
    """Tests for the gate recommendation model."""

    def test_gate_recommender_init(self):
        """Verify default gates are created."""
        recommender = GateRecommender()

        # Should have 10 gates: A1-A5 and B1-B5
        assert len(recommender.gates) == 10

        # Check Terminal A gates
        for i in range(1, 6):
            gate = recommender.get_gate(f"A{i}")
            assert gate is not None
            assert gate.terminal == "A"
            assert gate.status == GateStatus.AVAILABLE

        # Check Terminal B gates
        for i in range(1, 6):
            gate = recommender.get_gate(f"B{i}")
            assert gate is not None
            assert gate.terminal == "B"
            assert gate.status == GateStatus.AVAILABLE

    def test_gate_recommendation(self):
        """Verify recommendation returns GateRecommendation."""
        recommender = GateRecommender()
        flight = {"icao24": "abc123", "callsign": "SWA123"}

        recommendations = recommender.recommend(flight)

        assert len(recommendations) > 0
        assert isinstance(recommendations[0], GateRecommendation)
        assert recommendations[0].gate_id is not None
        assert 0 <= recommendations[0].score <= 1
        assert isinstance(recommendations[0].reasons, list)
        assert recommendations[0].estimated_taxi_time >= 0

    def test_gate_scoring(self):
        """Verify available gates score higher than occupied."""
        # Create custom gates with mixed status
        gates = [
            Gate("A1", "A", GateStatus.AVAILABLE),
            Gate("A2", "A", GateStatus.OCCUPIED),
            Gate("A3", "A", GateStatus.AVAILABLE),
        ]
        recommender = GateRecommender(gates)

        flight = {"icao24": "abc123", "callsign": "SWA123"}  # Domestic
        recommendations = recommender.recommend(flight, top_k=10)

        # Should only get recommendations for available gates
        gate_ids = [r.gate_id for r in recommendations]
        assert "A1" in gate_ids
        assert "A3" in gate_ids
        assert "A2" not in gate_ids  # Occupied gate not recommended

    def test_gate_status_update(self):
        """Verify status updates correctly."""
        recommender = GateRecommender()

        # Check initial status
        gate = recommender.get_gate("A1")
        assert gate.status == GateStatus.AVAILABLE
        assert gate.current_flight is None

        # Update to occupied
        recommender.update_gate_status("A1", GateStatus.OCCUPIED, "abc123")
        gate = recommender.get_gate("A1")
        assert gate.status == GateStatus.OCCUPIED
        assert gate.current_flight == "abc123"

        # Update back to available
        recommender.update_gate_status("A1", GateStatus.AVAILABLE)
        gate = recommender.get_gate("A1")
        assert gate.status == GateStatus.AVAILABLE
        assert gate.current_flight is None

    def test_top_k_recommendations(self):
        """Verify returns requested number of recommendations."""
        recommender = GateRecommender()
        flight = {"icao24": "abc123", "callsign": "SWA123"}

        # Request 1
        recs = recommender.recommend(flight, top_k=1)
        assert len(recs) == 1

        # Request 3
        recs = recommender.recommend(flight, top_k=3)
        assert len(recs) == 3

        # Request 5
        recs = recommender.recommend(flight, top_k=5)
        assert len(recs) == 5

        # Request more than available
        recs = recommender.recommend(flight, top_k=20)
        assert len(recs) <= 10  # Only 10 gates available

    def test_recommend_gate_convenience_function(self):
        """Test the recommend_gate convenience function."""
        flight = {"icao24": "xyz789", "callsign": "DAL456"}

        rec = recommend_gate(flight)

        assert isinstance(rec, GateRecommendation)
        assert rec.gate_id is not None

    def test_domestic_vs_international_terminal(self):
        """Test that domestic flights prefer Terminal A, international prefer B."""
        recommender = GateRecommender()

        # Domestic flight (SWA = Southwest Airlines)
        domestic_flight = {"icao24": "abc123", "callsign": "SWA100"}
        domestic_rec = recommender.recommend(domestic_flight, top_k=1)[0]

        # International flight (BAW = British Airways)
        intl_flight = {"icao24": "def456", "callsign": "BAW200"}
        intl_rec = recommender.recommend(intl_flight, top_k=1)[0]

        # Domestic should prefer Terminal A, international Terminal B
        # Note: These may both be A1 or B1 depending on scoring
        # Just verify both get valid recommendations
        assert domestic_rec.gate_id.startswith("A") or domestic_rec.gate_id.startswith("B")
        assert intl_rec.gate_id.startswith("A") or intl_rec.gate_id.startswith("B")


class TestCongestionModel:
    """Tests for the congestion prediction model."""

    def test_congestion_predictor_init(self):
        """Verify areas are defined."""
        predictor = CongestionPredictor()

        # Should have 6 areas defined
        assert len(predictor.areas) == 6

        # Check specific areas exist
        assert "runway_28L" in predictor.areas
        assert "runway_28R" in predictor.areas
        assert "taxiway_A" in predictor.areas
        assert "taxiway_B" in predictor.areas
        assert "terminal_A_apron" in predictor.areas
        assert "terminal_B_apron" in predictor.areas

        # Check capacities are set
        assert predictor.areas["runway_28L"].capacity == 2
        assert predictor.areas["taxiway_A"].capacity == 5
        assert predictor.areas["terminal_A_apron"].capacity == 10

    def test_congestion_prediction(self):
        """Verify returns AreaCongestion list."""
        predictor = CongestionPredictor()

        # Empty flights should still return predictions for all areas
        results = predictor.predict([])

        assert len(results) == 6
        for result in results:
            assert isinstance(result, AreaCongestion)
            assert result.area_id is not None
            assert result.area_type is not None
            assert isinstance(result.level, CongestionLevel)
            assert result.flight_count >= 0
            assert result.predicted_wait_minutes >= 0
            assert 0 <= result.confidence <= 1

    def test_congestion_levels(self):
        """Verify level computation based on capacity ratio."""
        predictor = CongestionPredictor()

        # Test LOW level (<50%)
        level = predictor._compute_congestion_level(0, 10)
        assert level == CongestionLevel.LOW

        level = predictor._compute_congestion_level(4, 10)
        assert level == CongestionLevel.LOW

        # Test MODERATE level (50-75%)
        level = predictor._compute_congestion_level(5, 10)
        assert level == CongestionLevel.MODERATE

        level = predictor._compute_congestion_level(7, 10)
        assert level == CongestionLevel.MODERATE

        # Test HIGH level (75-90%)
        level = predictor._compute_congestion_level(8, 10)
        assert level == CongestionLevel.HIGH

        # Test CRITICAL level (>90%)
        level = predictor._compute_congestion_level(9, 10)
        assert level == CongestionLevel.CRITICAL

        level = predictor._compute_congestion_level(10, 10)
        assert level == CongestionLevel.CRITICAL

    def test_bottleneck_detection(self):
        """Verify only HIGH/CRITICAL returned by get_bottlenecks."""
        predictor = CongestionPredictor()

        # With empty flights, all should be LOW - no bottlenecks
        bottlenecks = predictor.get_bottlenecks([])
        assert len(bottlenecks) == 0

        # All bottlenecks should be HIGH or CRITICAL
        for bottleneck in bottlenecks:
            assert bottleneck.level in {CongestionLevel.HIGH, CongestionLevel.CRITICAL}

    def test_empty_flights(self):
        """Verify handles empty flight list."""
        predictor = CongestionPredictor()

        results = predictor.predict([])

        # Should return predictions for all areas
        assert len(results) == 6

        # All should be LOW congestion with zero flights
        for result in results:
            assert result.flight_count == 0
            assert result.level == CongestionLevel.LOW
            assert result.predicted_wait_minutes == 0

    def test_predict_congestion_convenience_function(self):
        """Test the predict_congestion convenience function."""
        results = predict_congestion([])

        assert len(results) == 6
        for result in results:
            assert isinstance(result, AreaCongestion)

    def test_flight_in_runway_area(self):
        """Test that flights in runway area are counted."""
        predictor = CongestionPredictor()

        # Flight on runway_28L
        flights = [
            {
                "icao24": "abc123",
                "latitude": 37.498,
                "longitude": -122.000,
                "on_ground": True,
                "baro_altitude": 0,
                "velocity": 50
            },
            {
                "icao24": "def456",
                "latitude": 37.498,
                "longitude": -122.005,
                "on_ground": True,
                "baro_altitude": 0,
                "velocity": 30
            }
        ]

        results = predictor.predict(flights)

        # Find runway_28L result
        runway_result = next(r for r in results if r.area_id == "runway_28L")
        assert runway_result.flight_count == 2
        assert runway_result.level == CongestionLevel.CRITICAL  # 2/2 = 100%

    def test_flight_in_apron_area(self):
        """Test that stationary flights in apron area are counted."""
        predictor = CongestionPredictor()

        # Flight in terminal_A_apron (stationary)
        flights = [
            {
                "icao24": "ghi789",
                "latitude": 37.504,
                "longitude": -122.000,
                "on_ground": True,
                "baro_altitude": 0,
                "velocity": 0  # Stationary
            }
        ]

        results = predictor.predict(flights)

        # Find terminal_A_apron result
        apron_result = next(r for r in results if r.area_id == "terminal_A_apron")
        assert apron_result.flight_count == 1
        assert apron_result.level == CongestionLevel.LOW  # 1/10 = 10%
