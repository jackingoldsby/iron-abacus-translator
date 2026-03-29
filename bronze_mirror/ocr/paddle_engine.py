"""PaddleOCR wrapper for Chinese text recognition."""

import os
from dataclasses import dataclass
from pathlib import Path

# Suppress model-source connectivity check on startup
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

from paddleocr import PaddleOCR

from bronze_mirror.config.defaults import DEFAULT_OCR_LANG


@dataclass
class OcrBox:
    """A single OCR detection result."""

    text: str
    confidence: float
    bbox: list[list[float]]  # [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]

    @property
    def center_x(self) -> float:
        """Horizontal center of the bounding box."""
        return sum(p[0] for p in self.bbox) / 4

    @property
    def center_y(self) -> float:
        """Vertical center of the bounding box."""
        return sum(p[1] for p in self.bbox) / 4

    @property
    def top(self) -> float:
        return min(p[1] for p in self.bbox)

    @property
    def bottom(self) -> float:
        return max(p[1] for p in self.bbox)

    @property
    def left(self) -> float:
        return min(p[0] for p in self.bbox)

    @property
    def right(self) -> float:
        return max(p[0] for p in self.bbox)

    @property
    def width(self) -> float:
        return self.right - self.left

    @property
    def height(self) -> float:
        return self.bottom - self.top

    @property
    def is_vertical(self) -> bool:
        """Whether this text box is likely vertical (height >> width)."""
        return self.height > self.width * 1.5


def _detect_api_version() -> str:
    """Detect PaddleOCR API version (v2 uses .ocr(), v3 uses .predict())."""
    import paddleocr

    version = getattr(paddleocr, "__version__", "0.0.0")
    major = int(version.split(".")[0])
    return "v3" if major >= 3 else "v2"


class OcrEngine:
    """Wrapper around PaddleOCR for Chinese text recognition.

    Auto-detects API version:
    - PaddleOCR 2.x: uses .ocr() with use_angle_cls, show_log
    - PaddleOCR 3.x: uses .predict() with use_textline_orientation
    """

    def __init__(self, lang: str = DEFAULT_OCR_LANG, use_mobile: bool = False):
        self._api = _detect_api_version()

        if self._api == "v3":
            kwargs = dict(
                use_textline_orientation=True,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
            )
            if use_mobile:
                kwargs["text_detection_model_name"] = "PP-OCRv5_mobile_det"
                kwargs["text_recognition_model_name"] = "PP-OCRv5_mobile_rec"
            else:
                kwargs["lang"] = lang
        else:
            # v2 API
            kwargs = dict(
                lang=lang,
                use_angle_cls=True,
                use_gpu=False,
                show_log=False,
            )

        self._ocr = PaddleOCR(**kwargs)

    def recognize(self, image_path: str | Path) -> list[OcrBox]:
        """Run OCR on an image and return detected text boxes."""
        if self._api == "v3":
            return self._recognize_v3(image_path)
        return self._recognize_v2(image_path)

    def _recognize_v2(self, image_path: str | Path) -> list[OcrBox]:
        """PaddleOCR 2.x: .ocr() returns list of [bbox, (text, conf)]."""
        result = self._ocr.ocr(str(image_path), cls=True)

        boxes = []
        if not result or not result[0]:
            return boxes

        for line in result[0]:
            bbox = line[0]
            text = line[1][0]
            confidence = line[1][1]
            boxes.append(OcrBox(text=text, confidence=confidence, bbox=bbox))

        return boxes

    def _recognize_v3(self, image_path: str | Path) -> list[OcrBox]:
        """PaddleOCR 3.x: .predict() returns result objects with .json."""
        results = list(self._ocr.predict(str(image_path)))

        boxes = []
        if not results:
            return boxes

        for result in results:
            res = result.json.get("res", {}) if hasattr(result, "json") else {}
            rec_texts = res.get("rec_texts", [])
            rec_scores = res.get("rec_scores", [])
            dt_polys = res.get("dt_polys", [])

            for i, text in enumerate(rec_texts):
                score = rec_scores[i] if i < len(rec_scores) else 0.0
                poly = dt_polys[i] if i < len(dt_polys) else [[0, 0]] * 4
                bbox = poly.tolist() if hasattr(poly, "tolist") else list(poly)
                boxes.append(OcrBox(text=text, confidence=score, bbox=bbox))

        return boxes
