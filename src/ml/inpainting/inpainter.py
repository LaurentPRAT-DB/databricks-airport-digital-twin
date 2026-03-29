"""LaMa inpainting via IOPaint for satellite tile cleanup."""

import logging
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


class LaMaInpainter:
    """Wraps IOPaint's LaMa model for inpainting masked regions.

    LaMa (Large Mask Inpainting) excels at filling regular textures
    like airport tarmac, concrete, and runway surfaces.
    """

    def __init__(
        self,
        model_name: str = "lama",
        device: str = "cpu",
        weights_dir: Optional[str] = None,
    ):
        """
        Args:
            model_name: IOPaint model name (default "lama").
            device: "cpu" or "cuda".
            weights_dir: Directory for cached model weights.
                         On Databricks, point to a UC Volume path.
        """
        self.model_name = model_name
        self.device = device
        self.weights_dir = weights_dir
        self._model = None

    def _load_model(self):
        """Lazy-load the IOPaint model."""
        if self._model is not None:
            return

        import torch
        from iopaint.model_manager import ModelManager

        logger.info(
            "Loading IOPaint model '%s' (device=%s, weights_dir=%s)",
            self.model_name,
            self.device,
            self.weights_dir,
        )

        # IOPaint's ModelManager handles weight download/caching
        # When weights_dir is set, it looks there first before downloading
        self._model = ModelManager(
            name=self.model_name,
            device=torch.device(self.device),
        )

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

        result = self._model(image, mask)
        logger.debug("Inpainting complete (%dx%d)", image.shape[1], image.shape[0])
        return result
