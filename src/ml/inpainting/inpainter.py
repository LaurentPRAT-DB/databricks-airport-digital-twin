"""LaMa inpainting for satellite tile cleanup.

Tries IOPaint first (best quality), falls back to OpenCV's TELEA
inpainting if IOPaint/LaMa is unavailable.
"""

import logging
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


class LaMaInpainter:
    """Inpaints masked regions using LaMa (via IOPaint) or OpenCV fallback.

    LaMa (Large Mask Inpainting) excels at filling regular textures
    like airport tarmac, concrete, and runway surfaces.
    """

    def __init__(
        self,
        model_name: str = "lama",
        device: str = "cpu",
        weights_dir: Optional[str] = None,
    ):
        self.model_name = model_name
        self.device = device
        self.weights_dir = weights_dir
        self._model = None
        self._backend = None  # "iopaint" or "cv2"

    def _load_model(self):
        """Lazy-load the inpainting model. Tries IOPaint LaMa first, then cv2."""
        if self._model is not None:
            return

        # Try IOPaint with LaMa
        try:
            import torch
            from iopaint.model_manager import ModelManager

            logger.info("Loading IOPaint '%s' (device=%s)", self.model_name, self.device)
            self._model = ModelManager(
                name=self.model_name,
                device=torch.device(self.device),
            )
            self._backend = "iopaint"
            logger.info("IOPaint LaMa loaded successfully")
            return
        except Exception as e:
            logger.warning("IOPaint LaMa unavailable (%s), falling back to OpenCV", e)

        # Fallback: OpenCV inpainting (always available)
        self._backend = "cv2"
        self._model = "cv2"
        logger.info("Using OpenCV TELEA inpainting as fallback")

    def inpaint(self, image: np.ndarray, mask: np.ndarray) -> np.ndarray:
        """Inpaint masked regions of an image.

        Args:
            image: RGB image (H, W, 3), uint8.
            mask: Binary mask (H, W), uint8 — 255 = regions to fill.

        Returns:
            Inpainted RGB image (H, W, 3), uint8.
        """
        if mask.max() == 0:
            logger.debug("Empty mask — returning original image")
            return image.copy()

        self._load_model()

        if self._backend == "iopaint":
            result = self._model(image, mask)
        else:
            import cv2
            result = cv2.inpaint(image, mask, 10, cv2.INPAINT_TELEA)

        logger.debug("Inpainting complete (%dx%d) via %s", image.shape[1], image.shape[0], self._backend)
        return result
