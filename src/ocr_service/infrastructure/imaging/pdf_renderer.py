from __future__ import annotations

import multiprocessing as mp
from multiprocessing.connection import Connection
from pathlib import Path

from ocr_service.domain.errors import InvalidInputError


def inspect_pdf(path: Path, max_pages: int) -> int:
    try:
        import fitz  # type: ignore[import-not-found]

        with fitz.open(path) as document:
            page_count = int(document.page_count)
    except (ImportError, RuntimeError, ValueError) as error:
        raise InvalidInputError("PDF cannot be decoded") from error
    if page_count < 1 or page_count > max_pages:
        raise InvalidInputError("PDF page count exceeds the configured limit")
    return page_count


def _render_page(
    source: str, page_index: int, dpi: int, output: str, connection: Connection
) -> None:
    try:
        import fitz

        with fitz.open(source) as document:
            page = document.load_page(page_index)
            pixmap = page.get_pixmap(dpi=dpi, alpha=False)
            pixmap.save(output)
        connection.send(None)
    except Exception as error:  # Renderer subprocess boundary: return a safe error string only.
        connection.send(str(error))
    finally:
        connection.close()


def render_page_isolated(
    source: Path, page_index: int, dpi: int, destination: Path, timeout: int
) -> None:
    """Renders one page in a short-lived process, limiting PDF parser blast radius."""
    parent, child = mp.Pipe(duplex=False)
    process = mp.Process(
        target=_render_page,
        args=(str(source), page_index, dpi, str(destination), child),
    )
    process.start()
    child.close()
    process.join(timeout)
    if process.is_alive():
        process.kill()
        process.join()
        raise InvalidInputError("PDF rendering exceeded its time limit")
    error = parent.recv() if parent.poll() else "PDF renderer stopped unexpectedly"
    parent.close()
    if error is not None:
        raise InvalidInputError("PDF page cannot be rendered")
