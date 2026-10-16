from pathlib import Path
from typing import Protocol

from ocr_service.domain.models import PageResult


class OCREngine(Protocol):
    @property
    def is_ready(self) -> bool: ...
    @property
    def engine_metadata(self) -> dict[str, str]: ...
    def extract_page(
        self, image_path: Path, page_number: int, include_boxes: bool
    ) -> PageResult: ...
