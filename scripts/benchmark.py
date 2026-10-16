"""Repeatable single-worker benchmark for representative OCR pages.

Run in the worker image after building a corpus outside the repository:
    python scripts/benchmark.py /data/corpus --output benchmark-report.json
"""

from __future__ import annotations

import argparse
import json
import resource
import statistics
import time
from pathlib import Path

from ocr_service.infrastructure.ocr.paddle_engine import PaddleOCREngine


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark PP-OCRv5 Mobile on image pages")
    parser.add_argument("corpus", type=Path)
    parser.add_argument("--output", type=Path, default=Path("benchmark-report.json"))
    parser.add_argument("--threads", type=int, default=2)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    images = sorted(
        path
        for path in args.corpus.iterdir()
        if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
    )
    if not images:
        raise SystemExit("Corpus contains no supported images")
    engine = PaddleOCREngine(args.threads)
    engine.initialize()
    durations: list[float] = []
    for index, image in enumerate(images, start=1):
        started = time.perf_counter()
        engine.extract_page(image, index, include_boxes=True)
        durations.append((time.perf_counter() - started) * 1000)
    report = {
        "pages": len(durations),
        "p50_ms": statistics.median(durations),
        "p95_ms": sorted(durations)[max(0, round(len(durations) * 0.95) - 1)],
        "pages_per_minute": 60_000 / statistics.mean(durations),
        "max_rss_kb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
