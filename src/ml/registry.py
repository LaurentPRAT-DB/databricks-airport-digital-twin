"""Per-airport ML model registry.

Manages model instances keyed by ICAO airport code, replacing the
previous singleton pattern.  Models are created on first access and
cached for the lifetime of the process.

When a calibrated AirportProfile is available, it is passed to model
constructors so predictions are calibrated with real-data priors.

Trained models are loaded from UC Volume pickles (saved by the training
notebooks) when running on Databricks. Falls back to untrained instances
when pickles are not available.
"""

import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

from src.ml.congestion_model import CongestionPredictor
from src.ml.delay_model import DelayPredictor
from src.ml.gate_model import GateRecommender
from src.calibration.profile import AirportProfileLoader

logger = logging.getLogger(__name__)

# UC Volume path for trained model pickles
_UC_CATALOG = os.getenv("DATABRICKS_CATALOG", "serverless_stable_3n0ihb_catalog")
_UC_SCHEMA = os.getenv("DATABRICKS_SCHEMA", "airport_digital_twin")
_ML_MODELS_DIR = Path(f"/Volumes/{_UC_CATALOG}/{_UC_SCHEMA}/simulation_data/ml_models")

# Lazy import — TurnaroundPredictor requires scikit-learn which may not be
# installed in the lightweight Databricks App runtime.
_turnaround_import_attempted = False
_TurnaroundPredictor = None

_obt_import_attempted = False
_OBTPredictor = None


def _get_turnaround_predictor_class():
    global _turnaround_import_attempted, _TurnaroundPredictor
    if not _turnaround_import_attempted:
        _turnaround_import_attempted = True
        try:
            from src.ml.turnaround_model import TurnaroundPredictor
            _TurnaroundPredictor = TurnaroundPredictor
        except ImportError:
            logger.warning("scikit-learn not available — Turnaround model disabled")
    return _TurnaroundPredictor


def _get_obt_predictor_class():
    global _obt_import_attempted, _OBTPredictor
    if not _obt_import_attempted:
        _obt_import_attempted = True
        try:
            from src.ml.obt_model import OBTPredictor
            _OBTPredictor = OBTPredictor
        except ImportError:
            logger.warning("scikit-learn not available — OBT model disabled")
    return _OBTPredictor

# Try mlflow for UC registration
try:
    import mlflow

    MLFLOW_AVAILABLE = True
except ImportError:
    MLFLOW_AVAILABLE = False


class AirportModelRegistry:
    """Cache of ML model instances keyed by airport ICAO code."""

    def __init__(self):
        # {icao: {"delay": DelayPredictor, "gate": GateRecommender, "congestion": CongestionPredictor, "turnaround": TurnaroundPredictor}}
        self._instances: Dict[str, Dict[str, Any]] = {}
        self._profile_loader = AirportProfileLoader()

    def get_models(self, airport_code: str) -> Dict[str, Any]:
        """Get or create model set for an airport.

        When a calibrated AirportProfile is available, it is passed to
        model constructors for data-driven priors.

        Args:
            airport_code: ICAO code (e.g. "KSFO", "OMAA").

        Returns:
            Dict with keys "delay", "gate", "congestion".
        """
        if airport_code not in self._instances:
            logger.info(f"Creating model set for {airport_code}")
            profile = self._profile_loader.get_profile(airport_code)
            models = {
                "delay": DelayPredictor(airport_code=airport_code, airport_profile=profile),
                "gate": GateRecommender(airport_code=airport_code, airport_profile=profile),
                "congestion": CongestionPredictor(airport_code=airport_code, airport_profile=profile),
            }
            TA = _get_turnaround_predictor_class()
            if TA is not None:
                models["turnaround"] = TA(airport_code=airport_code, airport_profile=profile)
            OBT = _get_obt_predictor_class()
            if OBT is not None:
                models["obt"] = OBT(airport_code=airport_code, airport_profile=profile)
            self._instances[airport_code] = models
            # Try loading trained models from UC Volume
            if self.load_from_unity_catalog(airport_code):
                logger.info(f"Loaded trained models from UC for {airport_code}")
        return self._instances[airport_code]

    def retrain(self, airport_code: str) -> Dict[str, Any]:
        """Retrain all models for an airport using current synthetic data.

        Forces recreation of model instances so they pick up latest
        OSM config (runway coords, gate layout, etc.) and calibration profile.

        Returns:
            Dict with keys "delay", "gate", "congestion" and optionally "turnaround", "obt" (fresh instances).
        """
        logger.info(f"Retraining models for {airport_code}")
        profile = self._profile_loader.get_profile(airport_code)
        models = {
            "delay": DelayPredictor(airport_code=airport_code, airport_profile=profile),
            "gate": GateRecommender(airport_code=airport_code, airport_profile=profile),
            "congestion": CongestionPredictor(airport_code=airport_code, airport_profile=profile),
        }
        TA = _get_turnaround_predictor_class()
        if TA is not None:
            models["turnaround"] = TA(airport_code=airport_code, airport_profile=profile)
        OBT = _get_obt_predictor_class()
        if OBT is not None:
            models["obt"] = OBT(airport_code=airport_code, airport_profile=profile)
        self._instances[airport_code] = models
        return self._instances[airport_code]

    def register_to_unity_catalog(
        self, airport_code: str, catalog: str = "", schema: str = ""
    ) -> Dict[str, str]:
        """Deprecated — UC registration is handled by the training notebook.

        See databricks/notebooks/train_turnaround_model.py which registers models
        via mlflow.pyfunc.log_model with registered_model_name.
        """
        return {"status": "deprecated_use_training_notebook"}

    def load_from_unity_catalog(self, airport_code: str) -> bool:
        """Load trained models from UC Volume pickles if available.

        Loads turnaround (refined/coarse/board) and OBT departure
        (refined/coarse) pickles saved by the training notebooks.
        Models are airport-agnostic (trained on all airports), so
        the same pickles are used regardless of airport_code.

        Returns:
            True if at least one model was loaded, False otherwise.
        """
        if not _ML_MODELS_DIR.exists():
            logger.debug("UC Volume model dir not found: %s", _ML_MODELS_DIR)
            return False

        models = self.get_models(airport_code)
        loaded_any = False

        # Load turnaround model pickles
        turnaround = models.get("turnaround")
        if turnaround is not None:
            refined_pkl = _ML_MODELS_DIR / "obt_refined.pkl"
            coarse_pkl = _ML_MODELS_DIR / "obt_coarse.pkl"
            board_pkl = _ML_MODELS_DIR / "obt_board.pkl"

            if hasattr(turnaround, "load") and hasattr(turnaround, "refined"):
                # TwoStageTurnaroundPredictor
                r = turnaround.refined.load(refined_pkl) if refined_pkl.exists() else False
                c = turnaround.coarse.load(coarse_pkl) if coarse_pkl.exists() else False
                if r or c:
                    loaded_any = True
                    logger.info("Loaded turnaround model from UC Volume (refined=%s, coarse=%s)", r, c)
            elif hasattr(turnaround, "load"):
                # Single predictor
                if refined_pkl.exists() and turnaround.load(refined_pkl):
                    loaded_any = True
                    logger.info("Loaded turnaround refined model from UC Volume")

            # Load T-board model if available
            if hasattr(turnaround, "board_predictor"):
                bp = turnaround.board_predictor
                if bp is not None and hasattr(bp, "load") and board_pkl.exists():
                    if bp.load(board_pkl):
                        loaded_any = True
                        logger.info("Loaded turnaround T-board model from UC Volume")

        # Load OBT departure model pickles
        obt = models.get("obt")
        if obt is not None:
            obt_refined_pkl = _ML_MODELS_DIR / "obt_departure_refined.pkl"
            obt_coarse_pkl = _ML_MODELS_DIR / "obt_departure_coarse.pkl"

            if hasattr(obt, "refined") and hasattr(obt, "coarse"):
                r = obt.refined.load(obt_refined_pkl) if obt_refined_pkl.exists() else False
                c = obt.coarse.load(obt_coarse_pkl) if obt_coarse_pkl.exists() else False
                if r or c:
                    loaded_any = True
                    logger.info("Loaded OBT departure model from UC Volume (refined=%s, coarse=%s)", r, c)
            elif hasattr(obt, "load"):
                if obt_refined_pkl.exists() and obt.load(obt_refined_pkl):
                    loaded_any = True
                    logger.info("Loaded OBT departure refined model from UC Volume")

        return loaded_any

    def has_models(self, airport_code: str) -> bool:
        """Check if models are cached for an airport."""
        return airport_code in self._instances

    def clear(self, airport_code: Optional[str] = None) -> None:
        """Clear cached models.

        Args:
            airport_code: If provided, clear only that airport.
                          If None, clear all.
        """
        if airport_code:
            self._instances.pop(airport_code, None)
        else:
            self._instances.clear()


# Module-level singleton
_registry: Optional[AirportModelRegistry] = None


def get_model_registry() -> AirportModelRegistry:
    """Get the global AirportModelRegistry singleton."""
    global _registry
    if _registry is None:
        _registry = AirportModelRegistry()
    return _registry
