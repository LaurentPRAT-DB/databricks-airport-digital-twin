"""Tests for the realism scorecard scoring functions."""

import math

import pytest

from scripts.realism_scorecard import (
    js_divergence,
    cosine_similarity,
    score_jsd,
    score_abs_diff,
    score_cosine,
    DIMENSION_WEIGHTS,
)


# ---------------------------------------------------------------------------
# Jensen-Shannon divergence
# ---------------------------------------------------------------------------

class TestJSDivergence:
    def test_identical_distributions(self):
        p = {"A": 0.5, "B": 0.3, "C": 0.2}
        assert js_divergence(p, p) == pytest.approx(0.0, abs=1e-10)

    def test_completely_different(self):
        p = {"A": 1.0}
        q = {"B": 1.0}
        jsd = js_divergence(p, q)
        assert 0.9 < jsd <= 1.0  # Near maximum divergence

    def test_symmetric(self):
        p = {"A": 0.7, "B": 0.3}
        q = {"A": 0.4, "B": 0.6}
        assert js_divergence(p, q) == pytest.approx(js_divergence(q, p), abs=1e-10)

    def test_empty_distributions(self):
        assert js_divergence({}, {}) == 0.0

    def test_overlapping_keys(self):
        p = {"A": 0.5, "B": 0.5}
        q = {"B": 0.5, "C": 0.5}
        jsd = js_divergence(p, q)
        assert 0.0 < jsd < 1.0  # Partially different

    def test_similar_distributions_low_jsd(self):
        p = {"A": 0.50, "B": 0.30, "C": 0.20}
        q = {"A": 0.48, "B": 0.32, "C": 0.20}
        jsd = js_divergence(p, q)
        assert jsd < 0.01  # Very similar → very low JSD

    def test_unnormalized_input(self):
        """JSD should normalize inputs, so raw counts work."""
        p = {"A": 50, "B": 30, "C": 20}
        q = {"A": 48, "B": 32, "C": 20}
        jsd = js_divergence(p, q)
        assert jsd < 0.01

    def test_range_bounded(self):
        """JSD should be in [0, 1] for any input."""
        p = {"X": 0.9, "Y": 0.1}
        q = {"Y": 0.8, "Z": 0.2}
        jsd = js_divergence(p, q)
        assert 0.0 <= jsd <= 1.0


# ---------------------------------------------------------------------------
# Cosine similarity
# ---------------------------------------------------------------------------

class TestCosineSimilarity:
    def test_identical_vectors(self):
        a = [1.0, 2.0, 3.0]
        assert cosine_similarity(a, a) == pytest.approx(1.0, abs=1e-10)

    def test_orthogonal_vectors(self):
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert cosine_similarity(a, b) == pytest.approx(0.0, abs=1e-10)

    def test_proportional_vectors(self):
        a = [1.0, 2.0, 3.0]
        b = [2.0, 4.0, 6.0]
        assert cosine_similarity(a, b) == pytest.approx(1.0, abs=1e-10)

    def test_empty_vectors(self):
        assert cosine_similarity([], []) == 0.0

    def test_zero_vector(self):
        assert cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0

    def test_different_lengths_returns_zero(self):
        assert cosine_similarity([1.0, 2.0], [1.0]) == 0.0

    def test_hourly_pattern_similar(self):
        """Two similar hourly patterns should have high cosine similarity."""
        pattern_a = [0.01, 0.01, 0.01, 0.01, 0.02, 0.05,
                     0.08, 0.08, 0.08, 0.08, 0.06, 0.06,
                     0.06, 0.06, 0.06, 0.06, 0.08, 0.08,
                     0.08, 0.08, 0.04, 0.04, 0.02, 0.01]
        # Slightly noisy version
        pattern_b = [0.02, 0.01, 0.01, 0.01, 0.02, 0.04,
                     0.07, 0.09, 0.08, 0.07, 0.06, 0.06,
                     0.06, 0.06, 0.06, 0.07, 0.08, 0.07,
                     0.09, 0.08, 0.04, 0.04, 0.03, 0.01]
        sim = cosine_similarity(pattern_a, pattern_b)
        assert sim > 0.99


# ---------------------------------------------------------------------------
# Score conversion functions
# ---------------------------------------------------------------------------

class TestScoreConversions:
    def test_jsd_score_perfect(self):
        assert score_jsd(0.0) == 100.0

    def test_jsd_score_worst(self):
        assert score_jsd(0.2) == 0.0

    def test_jsd_score_midpoint(self):
        assert score_jsd(0.1) == pytest.approx(50.0)

    def test_jsd_score_beyond_threshold(self):
        assert score_jsd(0.5) == 0.0  # Clamped to 0

    def test_abs_diff_score_perfect(self):
        assert score_abs_diff(0.0) == 100.0

    def test_abs_diff_score_worst(self):
        assert score_abs_diff(0.10) == 0.0

    def test_abs_diff_score_midpoint(self):
        assert score_abs_diff(0.05) == pytest.approx(50.0)

    def test_cosine_score_perfect(self):
        assert score_cosine(1.0) == 100.0

    def test_cosine_score_zero(self):
        assert score_cosine(0.0) == 0.0

    def test_cosine_score_negative_clamped(self):
        assert score_cosine(-0.5) == 0.0


# ---------------------------------------------------------------------------
# Dimension weights
# ---------------------------------------------------------------------------

class TestDimensionWeights:
    def test_weights_sum_to_one(self):
        assert sum(DIMENSION_WEIGHTS.values()) == pytest.approx(1.0)

    def test_all_seven_dimensions(self):
        expected = {"airline", "route", "fleet", "hourly", "delay_rate", "delay_codes", "domestic_ratio"}
        assert set(DIMENSION_WEIGHTS.keys()) == expected


# ---------------------------------------------------------------------------
# Integration: score_airport with a single schedule
# ---------------------------------------------------------------------------

class TestScoreAirport:
    def test_score_airport_returns_structure(self):
        """Smoke test: scoring SFO with 1 schedule should return valid structure."""
        from scripts.realism_scorecard import score_airport
        from src.calibration.profile import AirportProfileLoader

        loader = AirportProfileLoader()
        result = score_airport("KSFO", loader, n_schedules=1)

        assert result["icao"] == "KSFO"
        assert result["iata"] == "SFO"
        assert "scores" in result
        assert "overall" in result
        assert 0.0 <= result["overall"] <= 100.0
        for dim in DIMENSION_WEIGHTS:
            assert dim in result["scores"]
            assert 0.0 <= result["scores"][dim] <= 100.0

    def test_score_airport_known_profile_scores_well(self):
        """Known profiled airports should generally score above 50 overall."""
        from scripts.realism_scorecard import score_airport
        from src.calibration.profile import AirportProfileLoader

        loader = AirportProfileLoader()
        result = score_airport("KSFO", loader, n_schedules=3)

        # SFO has a detailed profile — should score reasonably well
        assert result["overall"] > 30.0  # Conservative threshold
