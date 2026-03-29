"""YOLO-based aircraft detection in satellite/aerial imagery."""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class BBox:
    """Detected aircraft bounding box."""

    x1: int
    y1: int
    x2: int
    y2: int
    confidence: float
    class_name: str = "aircraft"

    @property
    def width(self) -> int:
        return self.x2 - self.x1

    @property
    def height(self) -> int:
        return self.y2 - self.y1

    @property
    def area(self) -> int:
        return self.width * self.height


class AircraftDetector:
    """Detects aircraft in satellite tiles using YOLOv8.

    Expects a YOLO model trained on aerial/satellite imagery with an
    'aircraft' or 'airplane' class.  Falls back to COCO-pretrained
    yolov8n.pt (class 4 = "airplane") when no custom weights are provided.
    """

    # COCO class index for "airplane"
    _COCO_AIRPLANE_CLASS = 4

    def __init__(
        self,
        weights_path: Optional[str] = None,
        confidence_threshold: float = 0.5,
        device: str = "cpu",
    ):
        self.weights_path = weights_path or "yolov8n.pt"
        self.confidence_threshold = confidence_threshold
        self.device = device
        self._model = None

    def _load_model(self):
        """Lazy-load YOLO model."""
        if self._model is not None:
            return
        from ultralytics import YOLO

        logger.info("Loading YOLO model from %s (device=%s)", self.weights_path, self.device)
        self._model = YOLO(self.weights_path)

    def detect(self, image: np.ndarray) -> List[BBox]:
        """Detect aircraft in an image.

        Args:
            image: RGB image as numpy array (H, W, 3), uint8.

        Returns:
            List of BBox detections above the confidence threshold.
        """
        self._load_model()

        results = self._model.predict(
            image,
            conf=self.confidence_threshold,
            device=self.device,
            verbose=False,
        )

        detections: List[BBox] = []
        for result in results:
            boxes = result.boxes
            if boxes is None:
                continue
            for i in range(len(boxes)):
                cls_id = int(boxes.cls[i].item())
                conf = float(boxes.conf[i].item())
                # Accept 'airplane' class from COCO or any class from custom model
                class_names = result.names
                class_name = class_names.get(cls_id, "")
                is_aircraft = (
                    cls_id == self._COCO_AIRPLANE_CLASS
                    or "aircraft" in class_name.lower()
                    or "airplane" in class_name.lower()
                    or "plane" in class_name.lower()
                )
                if not is_aircraft:
                    continue

                x1, y1, x2, y2 = boxes.xyxy[i].cpu().numpy().astype(int)
                detections.append(
                    BBox(
                        x1=int(x1),
                        y1=int(y1),
                        x2=int(x2),
                        y2=int(y2),
                        confidence=conf,
                        class_name=class_name or "airplane",
                    )
                )

        logger.info("Detected %d aircraft (threshold=%.2f)", len(detections), self.confidence_threshold)
        return detections

    def generate_mask(
        self,
        image_shape: tuple,
        detections: List[BBox],
        dilation_px: int = 10,
    ) -> np.ndarray:
        """Generate a binary mask from detections.

        Args:
            image_shape: (H, W) or (H, W, C) of the source image.
            detections: List of BBox from detect().
            dilation_px: Pixels to expand each bbox for cleaner inpainting edges.

        Returns:
            Binary mask (H, W) with 255 for regions to inpaint, 0 elsewhere.
        """
        h, w = image_shape[:2]
        mask = np.zeros((h, w), dtype=np.uint8)

        for det in detections:
            x1 = max(0, det.x1 - dilation_px)
            y1 = max(0, det.y1 - dilation_px)
            x2 = min(w, det.x2 + dilation_px)
            y2 = min(h, det.y2 + dilation_px)
            mask[y1:y2, x1:x2] = 255

        return mask
