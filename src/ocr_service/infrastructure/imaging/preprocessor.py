from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps

from ocr_service.domain.errors import InvalidInputError, UnsupportedMediaError

IMAGE_MAGIC_BYTES = {
    b"\x89PNG\r\n\x1a\n": "png",
    b"\xff\xd8\xff": "jpeg",
    b"RIFF": "webp",
}
PDF_MAGIC = b"%PDF-"


def detect_file_kind(path: Path) -> str:
    header = path.read_bytes()[:16]
    if header.startswith(PDF_MAGIC):
        return "pdf"
    if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return "image"
    if any(header.startswith(magic) for magic in IMAGE_MAGIC_BYTES if magic != b"RIFF"):
        return "image"
    raise UnsupportedMediaError("Only PNG, JPEG, WebP and PDF files are supported")


def inspect_image(path: Path, max_pixels: int) -> tuple[int, int]:
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            width, height = image.size
    except (OSError, ValueError) as error:
        raise InvalidInputError("Image cannot be decoded") from error
    if width * height > max_pixels:
        raise InvalidInputError("Image dimensions exceed the configured pixel limit")
    return width, height


def normalize_image(source: Path, destination: Path, max_pixels: int) -> tuple[int, int]:
    """Apply only EXIF rotation; scans are otherwise left untouched."""
    try:
        with Image.open(source) as image:
            image = ImageOps.exif_transpose(image)
            width, height = image.size
            if width * height > max_pixels:
                raise InvalidInputError("Image dimensions exceed the configured pixel limit")
            image.convert("RGB").save(destination, format="PNG", optimize=False)
            return width, height
    except InvalidInputError:
        raise
    except (OSError, ValueError) as error:
        raise InvalidInputError("Image cannot be normalized") from error
