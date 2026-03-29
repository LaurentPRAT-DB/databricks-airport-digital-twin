"""Tests for the aircraft inpainting pipeline (YOLO + LaMa)."""

import base64
import io
import json
import sys
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.ml.inpainting.detector import AircraftDetector, BBox
from src.ml.inpainting.inpainter import LaMaInpainter
from src.ml.inpainting.pipeline import InpaintingPipeline, InpaintResult


# ---------------------------------------------------------------------------
# BBox tests
# ---------------------------------------------------------------------------

class TestBBox:
    def test_properties(self):
        bbox = BBox(x1=10, y1=20, x2=50, y2=80, confidence=0.9)
        assert bbox.width == 40
        assert bbox.height == 60
        assert bbox.area == 2400

    def test_default_class_name(self):
        bbox = BBox(x1=0, y1=0, x2=10, y2=10, confidence=0.5)
        assert bbox.class_name == "aircraft"


# ---------------------------------------------------------------------------
# AircraftDetector tests
# ---------------------------------------------------------------------------

class TestAircraftDetector:
    def test_generate_mask_empty(self):
        detector = AircraftDetector()
        mask = detector.generate_mask((256, 256), [], dilation_px=0)
        assert mask.shape == (256, 256)
        assert mask.max() == 0

    def test_generate_mask_single_detection(self):
        detector = AircraftDetector()
        detections = [BBox(x1=50, y1=50, x2=100, y2=100, confidence=0.9)]
        mask = detector.generate_mask((256, 256), detections, dilation_px=0)
        assert mask[75, 75] == 255  # Inside bbox
        assert mask[0, 0] == 0  # Outside bbox

    def test_generate_mask_with_dilation(self):
        detector = AircraftDetector()
        detections = [BBox(x1=50, y1=50, x2=100, y2=100, confidence=0.9)]
        mask = detector.generate_mask((256, 256), detections, dilation_px=10)
        # Dilated region should extend beyond original bbox
        assert mask[45, 45] == 255  # Inside dilated region
        assert mask[0, 0] == 0

    def test_generate_mask_clamps_to_image_bounds(self):
        detector = AircraftDetector()
        detections = [BBox(x1=0, y1=0, x2=10, y2=10, confidence=0.9)]
        mask = detector.generate_mask((20, 20), detections, dilation_px=15)
        # Should not go negative — clamps at 0
        assert mask.shape == (20, 20)
        assert mask[0, 0] == 255

    def test_generate_mask_multiple_detections(self):
        detector = AircraftDetector()
        detections = [
            BBox(x1=10, y1=10, x2=30, y2=30, confidence=0.9),
            BBox(x1=200, y1=200, x2=220, y2=220, confidence=0.7),
        ]
        mask = detector.generate_mask((256, 256), detections, dilation_px=0)
        assert mask[20, 20] == 255
        assert mask[210, 210] == 255
        assert mask[128, 128] == 0  # Between the two

    def test_detect_filters_non_aircraft(self):
        """YOLO results with non-aircraft classes should be filtered out."""
        # Create mock YOLO boxes that behave like ultralytics results
        cls_items = [MagicMock(item=lambda c=c: c) for c in [2, 4]]
        conf_items = [MagicMock(item=lambda: 0.8), MagicMock(item=lambda: 0.8)]
        xyxy_items = [
            MagicMock(cpu=lambda: MagicMock(numpy=lambda: np.array([10, 10, 50, 50]))),
            MagicMock(cpu=lambda: MagicMock(numpy=lambda: np.array([60, 60, 120, 120]))),
        ]

        mock_boxes = MagicMock()
        mock_boxes.__len__ = lambda self: 2
        mock_boxes.cls.__getitem__ = lambda self, i: cls_items[i]
        mock_boxes.conf.__getitem__ = lambda self, i: conf_items[i]
        mock_boxes.xyxy.__getitem__ = lambda self, i: xyxy_items[i]

        mock_result = MagicMock()
        mock_result.boxes = mock_boxes
        mock_result.names = {2: "car", 4: "airplane"}

        mock_ultralytics = MagicMock()
        mock_model = MagicMock()
        mock_ultralytics.YOLO.return_value = mock_model
        mock_model.predict.return_value = [mock_result]

        with patch.dict(sys.modules, {"ultralytics": mock_ultralytics}):
            detector = AircraftDetector(confidence_threshold=0.3)
            image = np.zeros((256, 256, 3), dtype=np.uint8)
            detections = detector.detect(image)

        # Only the airplane (class 4) should be detected, not the car (class 2)
        assert len(detections) == 1
        assert detections[0].class_name == "airplane"


# ---------------------------------------------------------------------------
# LaMaInpainter tests
# ---------------------------------------------------------------------------

class TestLaMaInpainter:
    def test_empty_mask_returns_copy(self):
        """Empty mask should return original image without loading model."""
        inpainter = LaMaInpainter()
        image = np.random.randint(0, 255, (64, 64, 3), dtype=np.uint8)
        mask = np.zeros((64, 64), dtype=np.uint8)

        result = inpainter.inpaint(image, mask)
        np.testing.assert_array_equal(result, image)
        assert result is not image  # Should be a copy

    def test_inpaint_calls_model(self):
        import sys

        mock_torch = MagicMock()
        mock_iopaint = MagicMock()
        mock_mm = MagicMock()
        expected_output = np.ones((64, 64, 3), dtype=np.uint8) * 128
        mock_mm.return_value = expected_output
        mock_iopaint.model_manager.ModelManager.return_value = mock_mm

        with patch.dict(sys.modules, {
            "torch": mock_torch,
            "iopaint": mock_iopaint,
            "iopaint.model_manager": mock_iopaint.model_manager,
        }):
            inpainter = LaMaInpainter()
            image = np.zeros((64, 64, 3), dtype=np.uint8)
            mask = np.ones((64, 64), dtype=np.uint8) * 255

            result = inpainter.inpaint(image, mask)
            mock_mm.assert_called_once_with(image, mask)
            np.testing.assert_array_equal(result, expected_output)


# ---------------------------------------------------------------------------
# InpaintingPipeline tests
# ---------------------------------------------------------------------------

class TestInpaintingPipeline:
    def _make_pipeline(self, detections=None, inpainted=None):
        """Create a pipeline with mocked detector and inpainter."""
        pipeline = InpaintingPipeline.__new__(InpaintingPipeline)
        pipeline.mask_dilation_px = 10

        pipeline.detector = MagicMock(spec=AircraftDetector)
        pipeline.detector.detect.return_value = detections or []
        pipeline.detector.generate_mask.return_value = np.zeros((64, 64), dtype=np.uint8)

        pipeline.inpainter = MagicMock(spec=LaMaInpainter)
        if inpainted is not None:
            pipeline.inpainter.inpaint.return_value = inpainted
        else:
            pipeline.inpainter.inpaint.return_value = np.zeros((64, 64, 3), dtype=np.uint8)

        return pipeline

    def test_no_detections_returns_original(self):
        pipeline = self._make_pipeline(detections=[])
        image = np.random.randint(0, 255, (64, 64, 3), dtype=np.uint8)

        result = pipeline.remove_aircraft(image)

        assert result.aircraft_count == 0
        assert not result.had_aircraft
        assert result.detections == []
        np.testing.assert_array_equal(result.image, image)
        pipeline.inpainter.inpaint.assert_not_called()

    def test_with_detections_calls_inpainter(self):
        detections = [BBox(x1=10, y1=10, x2=50, y2=50, confidence=0.9)]
        clean_image = np.ones((64, 64, 3), dtype=np.uint8) * 200
        pipeline = self._make_pipeline(detections=detections, inpainted=clean_image)
        image = np.zeros((64, 64, 3), dtype=np.uint8)

        result = pipeline.remove_aircraft(image)

        assert result.aircraft_count == 1
        assert result.had_aircraft
        assert len(result.detections) == 1
        np.testing.assert_array_equal(result.image, clean_image)
        pipeline.inpainter.inpaint.assert_called_once()

    def test_return_mask_option(self):
        detections = [BBox(x1=10, y1=10, x2=50, y2=50, confidence=0.9)]
        pipeline = self._make_pipeline(detections=detections)
        image = np.zeros((64, 64, 3), dtype=np.uint8)

        result_no_mask = pipeline.remove_aircraft(image, return_mask=False)
        assert result_no_mask.mask is None

        result_with_mask = pipeline.remove_aircraft(image, return_mask=True)
        assert result_with_mask.mask is not None


# ---------------------------------------------------------------------------
# InpaintResult tests
# ---------------------------------------------------------------------------

class TestInpaintResult:
    def test_had_aircraft_true(self):
        result = InpaintResult(
            image=np.zeros((10, 10, 3), dtype=np.uint8),
            detections=[BBox(0, 0, 5, 5, 0.9)],
            aircraft_count=1,
        )
        assert result.had_aircraft

    def test_had_aircraft_false(self):
        result = InpaintResult(
            image=np.zeros((10, 10, 3), dtype=np.uint8),
            detections=[],
            aircraft_count=0,
        )
        assert not result.had_aircraft


# ---------------------------------------------------------------------------
# Serving model tests (base64 round-trip)
# ---------------------------------------------------------------------------

class TestBase64RoundTrip:
    def test_encode_decode_image(self):
        """Verify base64 encoding/decoding preserves image data."""
        from PIL import Image

        # Create a small test image
        image = np.random.randint(0, 255, (32, 32, 3), dtype=np.uint8)
        pil_img = Image.fromarray(image)

        # Encode
        buf = io.BytesIO()
        pil_img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

        # Decode
        decoded_bytes = base64.b64decode(b64)
        decoded_img = Image.open(io.BytesIO(decoded_bytes))
        decoded_np = np.array(decoded_img)

        np.testing.assert_array_equal(decoded_np, image)
