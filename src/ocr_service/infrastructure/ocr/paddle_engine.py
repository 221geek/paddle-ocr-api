from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from ocr_service.domain.models import PageResult, PolygonBlock

OCRLine = tuple[list[list[float]], str, float]


def _reading_order(items: list[OCRLine]) -> list[OCRLine]:
    """Stable top-to-bottom, left-to-right approximation; validate on multi-column pages."""

    def key(item: OCRLine) -> tuple[float, float]:
        polygon = item[0]
        top = min(point[1] for point in polygon)
        left = min(point[0] for point in polygon)
        return (round(top / 24) * 24, left)

    return sorted(items, key=key)


class PaddleOCREngine:
    def __init__(self, num_threads: int = 2) -> None:
        os.environ["OMP_NUM_THREADS"] = str(num_threads)
        os.environ["MKL_NUM_THREADS"] = str(num_threads)
        self._ocr: Any | None = None

    def initialize(self) -> None:
        from paddleocr import PaddleOCR  # type: ignore[import-not-found]

        # PP-OCRv5 Mobile is the CPU baseline. `lang=fr` selects Paddle's Latin
        # recognition model; clients cannot request a more expensive profile.
        self._ocr = PaddleOCR(
            lang="fr",
            device="cpu",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )

    @property
    def is_ready(self) -> bool:
        return self._ocr is not None

    @property
    def engine_metadata(self) -> dict[str, str]:
        return {"name": "paddleocr", "model": "PP-OCRv5_mobile", "version": "pinned-at-build"}

    def extract_page(self, image_path: Path, page_number: int, include_boxes: bool) -> PageResult:
        if self._ocr is None:
            raise RuntimeError("PaddleOCR engine was not initialized")
        started = time.perf_counter()
        raw_result = self._ocr.predict(str(image_path))
        items = self._parse_v3_output(raw_result)
        ordered = _reading_order(items)
        blocks = [
            PolygonBlock(
                id=f"b{index + 1}",
                text=text,
                confidence=confidence,
                polygon=polygon if include_boxes else [],
                reading_order=index,
            )
            for index, (polygon, text, confidence) in enumerate(ordered)
        ]
        from PIL import Image

        with Image.open(image_path) as image:
            width, height = image.size
        return PageResult(
            page_number=page_number,
            width=width,
            height=height,
            text="\n".join(block.text for block in blocks),
            blocks=blocks,
            processing_ms=round((time.perf_counter() - started) * 1000),
        )

    @staticmethod
    def _parse_v3_output(raw_result: Any) -> list[OCRLine]:
        """Map the documented PaddleOCR 3.x pipeline result to domain blocks."""
        parsed: list[OCRLine] = []
        for entry in raw_result:
            payload: Any
            if isinstance(entry, dict):
                payload = entry
            else:
                payload = getattr(entry, "json", None)
                if callable(payload):
                    payload = payload()
            if not isinstance(payload, dict):
                continue
            result = payload.get("res", payload)
            polygons = result.get("dt_polys", [])
            texts = result.get("rec_texts", [])
            scores = result.get("rec_scores", [])
            for polygon_raw, text, score in zip(polygons, texts, scores, strict=False):
                try:
                    polygon = [[float(x), float(y)] for x, y in polygon_raw]
                    parsed.append((polygon, str(text), float(score)))
                except (TypeError, ValueError):
                    continue
        return parsed
