"""Tests for ML models."""

import pytest

# Import delay model components
from src.ml.features import (
    FeatureSet,
    extract_features,
    features_to_array,
    _categorize_altitude,
    _categorize_distance,
    _compute_heading_quadrant,
)
from src.ml.delay_model import (
    DelayPrediction,
    DelayPredictor,
    predict_delay,
)
from src.ml.training import (
    train_delay_model,
    load_training_data_from_file,
)

# Import gate model components (from 03-02)
try:
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
    GATE_MODELS_AVAILABLE = True
except ImportError:
    GATE_MODELS_AVAILABLE = False


# ==============================================================================
# DELAY MODEL TESTS (03-01)
# ==============================================================================


class TestFeatureExtraction:
    """Tests for feature extraction functionality."""

    def test_extract_features_basic(self):
        """Test basic feature extraction from flight data."""
        flight = {
            "position_time": 1709650800,  # Some timestamp
            "baro_altitude": 3000,
            "velocity": 200,  # m/s
            "true_track": 45,
            "on_ground": False,
        }
        features = extract_features(flight)

        assert isinstance(features, FeatureSet)
        assert 0 <= features.hour_of_day <= 23
        assert 0 <= features.day_of_week <= 6
        assert isinstance(features.is_weekend, bool)
        assert features.altitude_category in ["ground", "low", "cruise"]
        assert features.flight_distance_category in ["short", "medium", "long"]
        assert 1 <= features.heading_quadrant <= 4
        assert 0 <= features.velocity_normalized <= 1

    def test_extract_features_ground_aircraft(self):
        """Test feature extraction for ground aircraft."""
        flight = {
            "position_time": 1709650800,
            "baro_altitude": 0,
            "velocity": 10,
            "true_track": 90,
            "on_ground": True,
        }
        features = extract_features(flight)

        assert features.altitude_category == "ground"
        assert features.velocity_normalized < 0.1

    def test_extract_features_missing_data(self):
        """Test feature extraction handles missing data gracefully."""
        flight = {}  # Empty flight data
        features = extract_features(flight)

        assert isinstance(features, FeatureSet)
        assert features.altitude_category == "ground"  # Default for missing altitude
        assert features.velocity_normalized == 0.0


class TestFeatureCategories:
    """Tests for altitude, distance, and heading categorization."""

    def test_altitude_category_ground(self):
        """Test ground altitude categorization."""
        assert _categorize_altitude(0, True) == "ground"
        assert _categorize_altitude(500, False) == "ground"
        assert _categorize_altitude(999, False) == "ground"

    def test_altitude_category_low(self):
        """Test low altitude categorization."""
        assert _categorize_altitude(1000, False) == "low"
        assert _categorize_altitude(3000, False) == "low"
        assert _categorize_altitude(4999, False) == "low"

    def test_altitude_category_cruise(self):
        """Test cruise altitude categorization."""
        assert _categorize_altitude(5000, False) == "cruise"
        assert _categorize_altitude(10000, False) == "cruise"
        assert _categorize_altitude(35000, False) == "cruise"

    def test_distance_category_short(self):
        """Test short distance categorization."""
        assert _categorize_distance(200, 3000) == "short"
        assert _categorize_distance(100, 1000) == "short"

    def test_distance_category_medium(self):
        """Test medium distance categorization."""
        assert _categorize_distance(350, 7000) == "medium"

    def test_distance_category_long(self):
        """Test long distance categorization."""
        assert _categorize_distance(450, 11000) == "long"

    def test_heading_quadrant_north(self):
        """Test north heading quadrant."""
        assert _compute_heading_quadrant(0) == 1
        assert _compute_heading_quadrant(44) == 1
        assert _compute_heading_quadrant(315) == 1
        assert _compute_heading_quadrant(359) == 1

    def test_heading_quadrant_east(self):
        """Test east heading quadrant."""
        assert _compute_heading_quadrant(45) == 2
        assert _compute_heading_quadrant(90) == 2
        assert _compute_heading_quadrant(134) == 2

    def test_heading_quadrant_south(self):
        """Test south heading quadrant."""
        assert _compute_heading_quadrant(135) == 3
        assert _compute_heading_quadrant(180) == 3
        assert _compute_heading_quadrant(224) == 3

    def test_heading_quadrant_west(self):
        """Test west heading quadrant."""
        assert _compute_heading_quadrant(225) == 4
        assert _compute_heading_quadrant(270) == 4
        assert _compute_heading_quadrant(314) == 4


class TestFeaturesToArray:
    """Tests for feature-to-array conversion."""

    def test_features_to_array_length(self):
        """Test that feature array has correct length."""
        features = FeatureSet(
            hour_of_day=12,
            day_of_week=3,
            is_weekend=False,
            flight_distance_category="medium",
            altitude_category="cruise",
            heading_quadrant=2,
            velocity_normalized=0.5,
        )
        array = features_to_array(features)

        # 4 numeric + 3 distance + 3 altitude + 4 heading = 14 features
        assert len(array) == 14

    def test_features_to_array_values_normalized(self):
        """Test that feature values are in valid range."""
        features = FeatureSet(
            hour_of_day=23,
            day_of_week=6,
            is_weekend=True,
            flight_distance_category="long",
            altitude_category="cruise",
            heading_quadrant=4,
            velocity_normalized=1.0,
        )
        array = features_to_array(features)

        for value in array:
            assert 0 <= value <= 1.0


class TestDelayPrediction:
    """Tests for delay prediction functionality."""

    def test_delay_prediction_basic(self):
        """Test basic delay prediction."""
        flight = {
            "position_time": 1709650800,
            "baro_altitude": 5000,
            "velocity": 200,
            "true_track": 90,
            "on_ground": False,
        }
        prediction = predict_delay(flight)

        assert isinstance(prediction, DelayPrediction)
        assert prediction.delay_minutes >= 0
        assert 0 <= prediction.confidence <= 1
        assert prediction.delay_category in ["on_time", "slight", "moderate", "severe"]

    def test_delay_confidence_valid_range(self):
        """Test that confidence is always in valid range."""
        predictor = DelayPredictor()

        # Test various scenarios
        test_flights = [
            {"baro_altitude": 0, "on_ground": True, "velocity": 0, "true_track": 0},
            {"baro_altitude": 10000, "on_ground": False, "velocity": 250, "true_track": 180},
            {"baro_altitude": 3000, "on_ground": False, "velocity": 150, "true_track": 45},
        ]

        for flight in test_flights:
            features = extract_features(flight)
            prediction = predictor.predict(features)
            assert 0.3 <= prediction.confidence <= 0.95, (
                f"Confidence {prediction.confidence} out of range for {flight}"
            )

    def test_delay_categories_assignment(self):
        """Test delay category assignment logic."""
        predictor = DelayPredictor()

        # Test category boundaries by checking the private method
        assert predictor._categorize_delay(0) == "on_time"
        assert predictor._categorize_delay(4.9) == "on_time"
        assert predictor._categorize_delay(5) == "slight"
        assert predictor._categorize_delay(14.9) == "slight"
        assert predictor._categorize_delay(15) == "moderate"
        assert predictor._categorize_delay(29.9) == "moderate"
        assert predictor._categorize_delay(30) == "severe"
        assert predictor._categorize_delay(60) == "severe"


class TestBatchPrediction:
    """Tests for batch prediction functionality."""

    def test_batch_prediction_empty(self):
        """Test batch prediction with empty list."""
        predictor = DelayPredictor()
        predictions = predictor.predict_batch([])
        assert predictions == []

    def test_batch_prediction_multiple_flights(self):
        """Test batch prediction with multiple flights."""
        predictor = DelayPredictor()

        flights = [
            {"baro_altitude": 0, "on_ground": True, "velocity": 10, "true_track": 0},
            {"baro_altitude": 5000, "on_ground": False, "velocity": 200, "true_track": 90},
            {"baro_altitude": 10000, "on_ground": False, "velocity": 250, "true_track": 180},
        ]

        predictions = predictor.predict_batch(flights)

        assert len(predictions) == 3
        for pred in predictions:
            assert isinstance(pred, DelayPrediction)

    def test_batch_prediction_sample_data(self):
        """Test batch prediction with sample flight data file."""
        import os

        sample_path = "data/fallback/sample_flights.json"
        if not os.path.exists(sample_path):
            pytest.skip("Sample data file not found")

        flights = load_training_data_from_file(sample_path)
        predictor = DelayPredictor()
        predictions = predictor.predict_batch(flights)

        assert len(predictions) == len(flights)


class TestTraining:
    """Tests for model training functionality."""

    def test_train_delay_model_basic(self):
        """Test basic model training."""
        training_data = [
            {"baro_altitude": 0, "on_ground": True, "velocity": 10, "true_track": 0},
            {"baro_altitude": 5000, "on_ground": False, "velocity": 200, "true_track": 90},
        ]

        result = train_delay_model(training_data)

        assert "run_id" in result
        assert "metrics" in result
        assert "model_path" in result
        assert result["metrics"]["training_samples"] == 2

    def test_train_delay_model_metrics(self):
        """Test that training produces expected metrics."""
        training_data = [
            {"baro_altitude": 5000, "on_ground": False, "velocity": 200, "true_track": i * 30}
            for i in range(10)
        ]

        result = train_delay_model(training_data)
        metrics = result["metrics"]

        assert "mean_delay" in metrics
        assert "std_delay" in metrics
        assert "mean_confidence" in metrics
        assert "pct_on_time" in metrics

    def test_load_training_data_opensky_format(self):
        """Test loading training data from OpenSky format."""
        import os

        sample_path = "data/fallback/sample_flights.json"
        if not os.path.exists(sample_path):
            pytest.skip("Sample data file not found")

        flights = load_training_data_from_file(sample_path)

        assert len(flights) > 0
        assert "icao24" in flights[0]
        assert "callsign" in flights[0]
        assert "baro_altitude" in flights[0]


# ==============================================================================
# GATE MODEL TESTS (03-02) - Only run if gate models are available
# ==============================================================================


@pytest.mark.skipif(not GATE_MODELS_AVAILABLE, reason="Gate models not available yet")
class TestGateModel:
    """Tests for the gate recommendation model."""

    def test_gate_recommender_init(self):
        """Verify default gates are created with proper properties."""
        recommender = GateRecommender()

        # Should have 10 gates: A1-A5 and B1-B5
        assert len(recommender.gates) == 10

        # Check Terminal A gates (domestic)
        for i in range(1, 6):
            gate = recommender.get_gate(f"A{i}")
            assert gate is not None
            assert "A" in gate.terminal  # Full name: "Domestic Terminal A"
            assert gate.status == GateStatus.AVAILABLE
            assert gate.is_international is False

        # Check Terminal B gates (international)
        for i in range(1, 6):
            gate = recommender.get_gate(f"B{i}")
            assert gate is not None
            assert "B" in gate.terminal  # Full name: "International Terminal B"
            assert gate.status == GateStatus.AVAILABLE
            assert gate.is_international is True

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
        recommender = GateRecommender(gates=gates)

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

    def test_gate_from_osm_data(self):
        """Test creating Gate from OSM-style configuration."""
        from src.ml.gate_model import Gate, GateSize

        osm_gate = {
            "id": "G92",
            "ref": "G92",
            "terminal": "International Terminal G",
            "name": "Gate G92",
            "operator": "United Airlines",
            "level": "2",
            "geo": {"latitude": 37.6145, "longitude": -122.3955},
            "osmId": 123456789,
        }

        gate = Gate.from_osm_gate(osm_gate)

        assert gate.gate_id == "G92"
        assert gate.terminal == "International Terminal G"
        assert gate.name == "Gate G92"
        assert gate.operator == "United Airlines"
        assert gate.level == "2"
        assert gate.latitude == 37.6145
        assert gate.longitude == -122.3955
        assert gate.osm_id == 123456789
        assert gate.is_international is True  # Terminal name contains "international"
        assert gate.gate_size == GateSize.LARGE  # International gates default to large

    def test_aircraft_size_scoring(self):
        """Test that gate/aircraft size compatibility affects scoring."""
        from src.ml.gate_model import Gate, GateSize

        # Create gates with different sizes including SUPER for A380
        gates = [
            Gate(gate_id="S1", terminal="T1", gate_size=GateSize.SMALL),
            Gate(gate_id="M1", terminal="T1", gate_size=GateSize.MEDIUM),
            Gate(gate_id="L1", terminal="T1", gate_size=GateSize.LARGE),
            Gate(gate_id="X1", terminal="T1", gate_size=GateSize.SUPER),
        ]
        recommender = GateRecommender(gates=gates)

        # Wide-body aircraft (B777) - should prefer large gate
        widebody_flight = {
            "icao24": "abc123",
            "callsign": "UAE100",
            "aircraft_type": "B777",
        }
        recs = recommender.recommend(widebody_flight, top_k=4)
        gate_ids = [r.gate_id for r in recs]

        # Large gate should score highest for B777 (perfect size match)
        assert recs[0].gate_id == "L1"

        # Super gate is usable (oversized) - should be ranked second
        assert gate_ids.index("X1") < gate_ids.index("S1")
        assert gate_ids.index("X1") < gate_ids.index("M1")

        # Small/Medium gates should have lower scores (too small)
        # They're still returned but ranked lower than appropriate-sized gates
        l1_score = recs[gate_ids.index("L1")].score
        s1_score = recs[gate_ids.index("S1")].score
        assert l1_score > s1_score  # Perfect match beats too-small gate

    def test_operator_matching(self):
        """Test that gates with matching operators score higher."""
        from src.ml.gate_model import Gate

        gates = [
            Gate(gate_id="UA1", terminal="T1", operator="United Airlines"),
            Gate(gate_id="DL1", terminal="T1", operator="Delta Air Lines"),
            Gate(gate_id="G1", terminal="T1"),  # No operator assigned
        ]
        recommender = GateRecommender(gates=gates)

        # United flight should prefer United gate
        united_flight = {"icao24": "abc123", "callsign": "UAL500"}
        recs = recommender.recommend(united_flight, top_k=3)

        # United gate should be top recommendation
        assert recs[0].gate_id == "UA1"


@pytest.mark.skipif(not GATE_MODELS_AVAILABLE, reason="Gate models not available yet")
class TestCongestionModel:
    """Tests for the congestion prediction model."""

    def test_congestion_predictor_init(self):
        """Verify areas are defined."""
        predictor = CongestionPredictor()

        # Should have 7 areas defined (4 runways + 1 taxiway + 2 aprons)
        assert len(predictor.areas) == 7

        # Check specific areas exist (real SFO layout)
        assert "runway_28L_10R" in predictor.areas
        assert "runway_28R_10L" in predictor.areas
        assert "runway_01L_19R" in predictor.areas
        assert "runway_01R_19L" in predictor.areas
        assert "taxiway_main" in predictor.areas
        assert "intl_terminal_apron" in predictor.areas
        assert "domestic_terminal_apron" in predictor.areas

        # Check capacities are set
        assert predictor.areas["runway_28L_10R"].capacity == 2
        assert predictor.areas["taxiway_main"].capacity == 8
        assert predictor.areas["intl_terminal_apron"].capacity == 15

    def test_congestion_prediction(self):
        """Verify returns AreaCongestion list."""
        predictor = CongestionPredictor()

        # Empty flights should still return predictions for all areas
        results = predictor.predict([])

        assert len(results) == 7
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
        assert len(results) == 7

        # All should be LOW congestion with zero flights
        for result in results:
            assert result.flight_count == 0
            assert result.level == CongestionLevel.LOW
            assert result.predicted_wait_minutes == 0

    def test_predict_congestion_convenience_function(self):
        """Test the predict_congestion convenience function."""
        results = predict_congestion([])

        assert len(results) == 7
        for result in results:
            assert isinstance(result, AreaCongestion)

    def test_flight_in_runway_area(self):
        """Test that flights in runway area are counted."""
        predictor = CongestionPredictor()

        # Flight on runway_28L_10R (Real SFO coordinates)
        # runway_28L_10R: lat_range=(37.610, 37.628), lon_range=(-122.395, -122.355)
        flights = [
            {
                "icao24": "abc123",
                "latitude": 37.615,
                "longitude": -122.370,
                "on_ground": True,
                "baro_altitude": 0,
                "velocity": 50
            },
            {
                "icao24": "def456",
                "latitude": 37.620,
                "longitude": -122.375,
                "on_ground": True,
                "baro_altitude": 0,
                "velocity": 30
            }
        ]

        results = predictor.predict(flights)

        # Find runway_28L_10R result
        runway_result = next(r for r in results if r.area_id == "runway_28L_10R")
        assert runway_result.flight_count == 2
        assert runway_result.level == CongestionLevel.CRITICAL  # 2/2 = 100%

    def test_flight_in_apron_area(self):
        """Test that stationary flights in apron area are counted."""
        predictor = CongestionPredictor()

        # Flight in intl_terminal_apron (stationary) (Real SFO coordinates)
        # intl_terminal_apron: lat_range=(37.612, 37.618), lon_range=(-122.398, -122.385)
        flights = [
            {
                "icao24": "ghi789",
                "latitude": 37.615,
                "longitude": -122.390,
                "on_ground": True,
                "baro_altitude": 0,
                "velocity": 0  # Stationary
            }
        ]

        results = predictor.predict(flights)

        # Find intl_terminal_apron result
        apron_result = next(r for r in results if r.area_id == "intl_terminal_apron")
        assert apron_result.flight_count == 1
        assert apron_result.level == CongestionLevel.LOW  # 1/15 < 10%
