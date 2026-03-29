"""Aircraft removal from satellite imagery via YOLO detection + LaMa inpainting."""

from src.ml.inpainting.detector import AircraftDetector, BBox
from src.ml.inpainting.inpainter import LaMaInpainter
from src.ml.inpainting.pipeline import InpaintingPipeline, InpaintResult

__all__ = [
    "AircraftDetector",
    "BBox",
    "LaMaInpainter",
    "InpaintingPipeline",
    "InpaintResult",
]
