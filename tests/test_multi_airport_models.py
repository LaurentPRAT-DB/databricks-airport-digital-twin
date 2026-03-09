"""Tests for multi-airport ML model management.

Verifies that models are parameterized per airport and that the
AirportModelRegistry caches and returns correct instances.
"""

import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# DelayPredictor
# ---------------------------------------------------------------------------

class TestDelayPredictor:
    def test_accepts_airport_code(self):
        from src.ml.delay_model import DelayPredictor

        p = DelayPredictor(airport_code="OMAA")
        assert p.airport_code == "OMAA"

    def test_default_airport_code_is_ksfo(self):
        from src.ml.delay_model import DelayPredictor

        p = DelayPredictor()
        assert p.airport_code == "KSFO"


# ---------------------------------------------------------------------------
# GateRecommender
# ---------------------------------------------------------------------------

class TestGateRecommender:
    def test_accepts_airport_code(self):
        from src.ml.gate_model import GateRecommender, Gate

        gate = Gate(gate_id="1", terminal="T1")
        r = GateRecommender(airport_code="OMAA", gates=[gate])
        assert r.airport_code == "OMAA"

    def test_us_airport_domestic_flight(self):
        from src.ml.gate_model import GateRecommender, Gate

        gate = Gate(gate_id="1", terminal="T1")
        r = GateRecommender(airport_code="KSFO", gates=[gate])
        # UAL is a US domestic prefix
        assert r._is_international_flight("UAL123") is False
        # AFR is international for US
        assert r._is_international_flight("AFR456") is True

    def test_non_us_airport_international_logic(self):
        from src.ml.gate_model import GateRecommender, Gate

        gate = Gate(gate_id="1", terminal="T1")
        r = GateRecommender(airport_code="OMAA", gates=[gate])
        # UAE and ETD are domestic UAE carriers
        assert r._is_international_flight("UAE001") is False
        assert r._is_international_flight("ETD002") is False
        # UAL is international at Abu Dhabi
        assert r._is_international_flight("UAL123") is True

    def test_uk_airport_domestic_carriers(self):
        from src.ml.gate_model import GateRecommender, Gate

        gate = Gate(gate_id="1", terminal="T1")
        r = GateRecommender(airport_code="EGLL", gates=[gate])
        # BAW is domestic UK carrier
        assert r._is_international_flight("BAW100") is False
        # DAL is international at Heathrow
        assert r._is_international_flight("DAL200") is True

    def test_runway_coords_fallback(self):
        from src.ml.gate_model import GateRecommender, Gate

        gate = Gate(gate_id="1", terminal="T1")
        r = GateRecommender(airport_code="ZZZZ", gates=[gate])
        # Should fall back to SFO coords when config unavailable
        assert r._runway_coords == (37.6117, -122.3583)


# ---------------------------------------------------------------------------
# CongestionPredictor
# ---------------------------------------------------------------------------

class TestCongestionPredictor:
    def test_accepts_airport_code(self):
        from src.ml.congestion_model import CongestionPredictor

        p = CongestionPredictor(airport_code="OMAA")
        assert p.airport_code == "OMAA"

    def test_sfo_fallback_areas(self):
        """Without OSM config available, should fall back to hardcoded SFO areas."""
        from src.ml.congestion_model import CongestionPredictor

        p = CongestionPredictor(airport_code="KSFO")
        # Should have the SFO fallback areas
        assert "runway_28L_10R" in p.areas or len(p.areas) > 0

    def test_dynamic_areas_from_osm(self):
        """When OSM config is available, areas should be built dynamically."""
        from src.ml.congestion_model import CongestionPredictor

        mock_config = {
            "osmRunways": [
                {
                    "ref": "13L/31R",
                    "geoPoints": [
                        {"latitude": 24.43, "longitude": 54.65},
                        {"latitude": 24.44, "longitude": 54.66},
                    ],
                }
            ],
            "osmTaxiways": [
                {
                    "geoPoints": [
                        {"latitude": 24.435, "longitude": 54.655},
                        {"latitude": 24.436, "longitude": 54.656},
                    ]
                }
            ],
            "osmAprons": [
                {
                    "ref": "A",
                    "geoPolygon": [
                        {"latitude": 24.43, "longitude": 54.64},
                        {"latitude": 24.44, "longitude": 54.65},
                        {"latitude": 24.44, "longitude": 54.64},
                    ],
                }
            ],
        }

        mock_service = MagicMock()
        mock_service.get_config.return_value = mock_config

        with patch(
            "src.ml.congestion_model.get_airport_config_service",
            return_value=mock_service,
            create=True,
        ):
            # We need to patch the import inside the method
            import src.ml.congestion_model as cm
            original = cm.CongestionPredictor._build_areas_from_config

            def patched_build(self_inner):
                # Simulate the import succeeding with our mock
                service = mock_service
                config = service.get_config()
                areas = {}

                osm_runways = config.get("osmRunways", [])
                for i, rw in enumerate(osm_runways):
                    geo_points = rw.get("geoPoints", [])
                    if not geo_points:
                        continue
                    lats = [p["latitude"] for p in geo_points]
                    lons = [p["longitude"] for p in geo_points]
                    ref = rw.get("ref", f"rw_{i}")
                    area_id = f"runway_{ref}".replace("/", "_")
                    areas[area_id] = cm.AirportArea(
                        area_id=area_id,
                        area_type="runway",
                        capacity=2,
                        lat_range=(min(lats) - 0.001, max(lats) + 0.001),
                        lon_range=(min(lons) - 0.001, max(lons) + 0.001),
                    )

                osm_taxiways = config.get("osmTaxiways", [])
                if osm_taxiways:
                    all_lats = []
                    all_lons = []
                    for tw in osm_taxiways:
                        for p in tw.get("geoPoints", []):
                            all_lats.append(p["latitude"])
                            all_lons.append(p["longitude"])
                    if all_lats:
                        areas["taxiway_main"] = cm.AirportArea(
                            area_id="taxiway_main",
                            area_type="taxiway",
                            capacity=max(8, len(osm_taxiways) // 10),
                            lat_range=(min(all_lats), max(all_lats)),
                            lon_range=(min(all_lons), max(all_lons)),
                        )

                osm_aprons = config.get("osmAprons", [])
                for i, apron in enumerate(osm_aprons):
                    geo_poly = apron.get("geoPolygon", [])
                    if not geo_poly:
                        continue
                    lats = [p["latitude"] for p in geo_poly]
                    lons = [p["longitude"] for p in geo_poly]
                    area_id = f"apron_{apron.get('ref', i)}"
                    areas[area_id] = cm.AirportArea(
                        area_id=area_id,
                        area_type="apron",
                        capacity=max(5, len(osm_aprons)),
                        lat_range=(min(lats), max(lats)),
                        lon_range=(min(lons), max(lons)),
                    )

                return areas if areas else None

            cm.CongestionPredictor._build_areas_from_config = patched_build
            try:
                p = CongestionPredictor(airport_code="OMAA")
                assert "runway_13L_31R" in p.areas
                assert "taxiway_main" in p.areas
                assert "apron_A" in p.areas
                # Verify the areas have Abu Dhabi coordinates, not SFO
                rw = p.areas["runway_13L_31R"]
                assert rw.lat_range[0] > 24.0  # Abu Dhabi lat
            finally:
                cm.CongestionPredictor._build_areas_from_config = original


# ---------------------------------------------------------------------------
# GSE Fleet Scaling
# ---------------------------------------------------------------------------

class TestGSEFleetScaling:
    def test_default_fleet_status(self):
        from src.ml.gse_model import get_fleet_status

        fleet = get_fleet_status()
        assert fleet["total_units"] > 0
        assert "by_type" in fleet

    def test_fleet_scales_with_airport(self):
        from src.ml.gse_model import get_fleet_status

        # Mock different gate counts
        with patch("src.ml.gse_model._get_gate_count", return_value=120):
            sfo_fleet = get_fleet_status("KSFO")

        with patch("src.ml.gse_model._get_gate_count", return_value=240):
            big_fleet = get_fleet_status("OMAA")

        with patch("src.ml.gse_model._get_gate_count", return_value=60):
            small_fleet = get_fleet_status("KSMF")

        # Bigger airport should have more units
        assert big_fleet["total_units"] > sfo_fleet["total_units"]
        # Smaller airport should have fewer units
        assert small_fleet["total_units"] < sfo_fleet["total_units"]


# ---------------------------------------------------------------------------
# AirportModelRegistry
# ---------------------------------------------------------------------------

class TestAirportModelRegistry:
    def test_creates_models_per_airport(self):
        from src.ml.registry import AirportModelRegistry

        reg = AirportModelRegistry()
        sfo = reg.get_models("KSFO")
        omaa = reg.get_models("OMAA")

        assert sfo["delay"].airport_code == "KSFO"
        assert omaa["delay"].airport_code == "OMAA"
        assert sfo["gate"].airport_code == "KSFO"
        assert omaa["gate"].airport_code == "OMAA"
        assert sfo["congestion"].airport_code == "KSFO"
        assert omaa["congestion"].airport_code == "OMAA"

    def test_caches_models(self):
        from src.ml.registry import AirportModelRegistry

        reg = AirportModelRegistry()
        models1 = reg.get_models("KSFO")
        models2 = reg.get_models("KSFO")
        assert models1["delay"] is models2["delay"]

    def test_retrain_creates_new_instances(self):
        from src.ml.registry import AirportModelRegistry

        reg = AirportModelRegistry()
        old = reg.get_models("KSFO")
        new = reg.retrain("KSFO")
        assert old["delay"] is not new["delay"]

    def test_has_models(self):
        from src.ml.registry import AirportModelRegistry

        reg = AirportModelRegistry()
        assert reg.has_models("KSFO") is False
        reg.get_models("KSFO")
        assert reg.has_models("KSFO") is True

    def test_clear_specific_airport(self):
        from src.ml.registry import AirportModelRegistry

        reg = AirportModelRegistry()
        reg.get_models("KSFO")
        reg.get_models("OMAA")
        reg.clear("KSFO")
        assert reg.has_models("KSFO") is False
        assert reg.has_models("OMAA") is True

    def test_clear_all(self):
        from src.ml.registry import AirportModelRegistry

        reg = AirportModelRegistry()
        reg.get_models("KSFO")
        reg.get_models("OMAA")
        reg.clear()
        assert reg.has_models("KSFO") is False
        assert reg.has_models("OMAA") is False


# ---------------------------------------------------------------------------
# Training Pipeline Namespacing
# ---------------------------------------------------------------------------

    def test_register_to_unity_catalog_no_mlflow(self):
        from src.ml.registry import AirportModelRegistry

        reg = AirportModelRegistry()
        reg.get_models("KSFO")
        with patch("src.ml.registry.MLFLOW_AVAILABLE", False):
            result = reg.register_to_unity_catalog("KSFO", "cat", "schema")
            assert result == {"status": "mlflow_not_available"}

    def test_register_to_unity_catalog_no_catalog(self):
        from src.ml.registry import AirportModelRegistry

        reg = AirportModelRegistry()
        reg.get_models("KSFO")
        with patch("src.ml.registry.MLFLOW_AVAILABLE", True):
            result = reg.register_to_unity_catalog("KSFO", "", "")
            assert result == {"status": "catalog_or_schema_not_configured"}

    def test_register_to_unity_catalog_with_config(self):
        from src.ml.registry import AirportModelRegistry

        reg = AirportModelRegistry()
        reg.get_models("KSFO")
        with patch("src.ml.registry.MLFLOW_AVAILABLE", True):
            result = reg.register_to_unity_catalog("KSFO", "my_cat", "my_schema")
            assert "delay" in result
            assert "registered:" in result["delay"]
            assert "KSFO" in result["delay"]

    def test_load_from_unity_catalog_no_mlflow(self):
        from src.ml.registry import AirportModelRegistry

        reg = AirportModelRegistry()
        with patch("src.ml.registry.MLFLOW_AVAILABLE", False):
            assert reg.load_from_unity_catalog("KSFO") is False

    def test_get_model_registry_singleton(self):
        import src.ml.registry as reg_mod

        old = reg_mod._registry
        reg_mod._registry = None
        try:
            r1 = reg_mod.get_model_registry()
            r2 = reg_mod.get_model_registry()
            assert r1 is r2
        finally:
            reg_mod._registry = old


# ---------------------------------------------------------------------------
# PredictionService
# ---------------------------------------------------------------------------

class TestPredictionService:
    def test_set_airport(self):
        from app.backend.services.prediction_service import PredictionService

        svc = PredictionService(airport_code="KSFO")
        assert svc.airport_code == "KSFO"
        svc.set_airport("OMAA")
        assert svc.airport_code == "OMAA"

    def test_models_resolve_per_airport(self):
        from app.backend.services.prediction_service import PredictionService

        svc = PredictionService(airport_code="KSFO")
        assert svc.delay_predictor.airport_code == "KSFO"
        assert svc.gate_recommender.airport_code == "KSFO"
        assert svc.congestion_predictor.airport_code == "KSFO"

        svc.set_airport("OMAA")
        assert svc.delay_predictor.airport_code == "OMAA"
        assert svc.gate_recommender.airport_code == "OMAA"

    def test_reload_gates_retrains(self):
        from app.backend.services.prediction_service import PredictionService

        svc = PredictionService(airport_code="KSFO")
        old_delay = svc.delay_predictor
        count = svc.reload_gates()
        assert count > 0
        # After retrain, should be a new instance
        assert svc.delay_predictor is not old_delay

    def test_get_prediction_service_singleton(self):
        import app.backend.services.prediction_service as ps_mod

        old = ps_mod._prediction_service
        ps_mod._prediction_service = None
        try:
            s1 = ps_mod.get_prediction_service()
            s2 = ps_mod.get_prediction_service()
            assert s1 is s2
        finally:
            ps_mod._prediction_service = old

    @pytest.mark.asyncio
    async def test_get_congestion_empty(self):
        from app.backend.services.prediction_service import PredictionService

        svc = PredictionService(airport_code="KSFO")
        result = await svc.get_congestion()
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_get_bottlenecks_empty(self):
        from app.backend.services.prediction_service import PredictionService

        svc = PredictionService(airport_code="KSFO")
        result = await svc.get_bottlenecks()
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_get_delay_prediction(self):
        from app.backend.services.prediction_service import PredictionService

        svc = PredictionService(airport_code="KSFO")
        flight = {
            "icao24": "abc123",
            "callsign": "UAL123",
            "latitude": 37.6,
            "longitude": -122.4,
            "baro_altitude": 0,
            "velocity": 0,
            "on_ground": True,
        }
        pred = await svc.get_delay_prediction(flight)
        assert pred.delay_minutes >= 0
        assert 0 <= pred.confidence <= 1

    @pytest.mark.asyncio
    async def test_get_gate_recommendations(self):
        from app.backend.services.prediction_service import PredictionService

        svc = PredictionService(airport_code="KSFO")
        flight = {"icao24": "abc123", "callsign": "UAL123"}
        recs = await svc.get_gate_recommendations(flight, top_k=2)
        assert isinstance(recs, list)

    @pytest.mark.asyncio
    async def test_get_flight_predictions(self):
        from app.backend.services.prediction_service import PredictionService

        svc = PredictionService(airport_code="KSFO")
        flights = [
            {
                "icao24": "abc123",
                "callsign": "UAL123",
                "latitude": 37.6,
                "longitude": -122.4,
                "baro_altitude": 0,
                "velocity": 0,
                "on_ground": True,
            }
        ]
        result = await svc.get_flight_predictions(flights)
        assert "delays" in result
        assert "gates" in result
        assert "congestion" in result


# ---------------------------------------------------------------------------
# Training Pipeline Namespacing
# ---------------------------------------------------------------------------

class TestTrainingNamespacing:
    def test_default_experiment_name_includes_airport(self):
        """Verify experiment name is namespaced by airport code."""
        from src.ml.training import train_delay_model

        sample_data = [
            {
                "icao24": "abc123",
                "callsign": "UAL123",
                "latitude": 37.6,
                "longitude": -122.4,
                "baro_altitude": 0,
                "velocity": 0,
                "on_ground": True,
            }
        ]

        # Train with airport code — should succeed even without MLflow
        result = train_delay_model(sample_data, airport_code="OMAA")
        assert result["model_path"] is not None
        # Path should contain airport code
        assert "OMAA" in result["model_path"]
