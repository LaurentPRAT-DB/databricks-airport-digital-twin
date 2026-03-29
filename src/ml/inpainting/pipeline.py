"""End-to-end aircraft removal pipeline: detect → mask → inpaint."""

import logging
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np

from src.ml.inpainting.detector import AircraftDetector, BBox
from src.ml.inpainting.inpainter import LaMaInpainter

logger = logging.getLogger(__name__)


@dataclass
class InpaintResult:
    """Result of the aircraft removal pipeline."""

    image: np.ndarray
    detections: List[BBox]
    aircraft_count: int
    mask: Optional[np.ndarray] = None

    @property
    def had_aircraft(self) -> bool:
        return self.aircraft_count > 0


class InpaintingPipeline:
    """Orchestrates YOLO detection + LaMa inpainting to remove aircraft
    from satellite imagery tiles."""

    def __init__(
        self,
        yolo_weights: Optional[str] = None,
        confidence_threshold: float = 0.5,
        mask_dilation_px: int = 10,
        device: str = "cpu",
        lama_weights_dir: Optional[str] = None,
    ):
        self.detector = AircraftDetector(
            weights_path=yolo_weights,
            confidence_threshold=confidence_threshold,
            device=device,
        )
        self.inpainter = LaMaInpainter(
            device=device,
            weights_dir=lama_weights_dir,
        )
        self.mask_dilation_px = mask_dilation_px

    def remove_aircraft(
        self,
        image: np.ndarray,
        return_mask: bool = False,
    ) -> InpaintResult:
        """Remove aircraft from a satellite tile image.

        Args:
            image: RGB image (H, W, 3), uint8.
            return_mask: If True, include the binary mask in the result.

        Returns:
            InpaintResult with clean image and detection metadata.
        """
        detections = self.detector.detect(image)

        if not detections:
            logger.debug("No aircraft detected — returning original")
            return InpaintResult(
                image=image.copy(),
                detections=[],
                aircraft_count=0,
            )

        mask = self.detector.generate_mask(
            image.shape, detections, dilation_px=self.mask_dilation_px
        )

        clean_image = self.inpainter.inpaint(image, mask)

        logger.info(
            "Removed %d aircraft from %dx%d tile",
            len(detections),
            image.shape[1],
            image.shape[0],
        )

        return InpaintResult(
            image=clean_image,
            detections=detections,
            aircraft_count=len(detections),
            mask=mask if return_mask else None,
        )
