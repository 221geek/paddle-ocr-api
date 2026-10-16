from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from pathlib import Path

from ocr_service.api.dependencies import build_container
from ocr_service.core.config import get_settings
from ocr_service.core.logging import configure_logging
from ocr_service.domain.enums import JobStatus
from ocr_service.domain.models import JobRecord, OCRResult, PageResult, utcnow
from ocr_service.infrastructure.imaging.pdf_renderer import render_page_isolated
from ocr_service.infrastructure.imaging.preprocessor import normalize_image
from ocr_service.infrastructure.ocr.paddle_engine import PaddleOCREngine
from ocr_service.infrastructure.persistence.redis_jobs import WORKER_READY_KEY, RedisJobRepository
from ocr_service.infrastructure.telemetry.metrics import (
    JOBS_COMPLETED,
    JOBS_FAILED,
    PROCESSING_SECONDS,
)

logger = logging.getLogger(__name__)


class Worker:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.container = build_container(self.settings)
        self.engine = PaddleOCREngine(self.settings.paddle_num_threads)

    async def run(self) -> None:
        if self.settings.job_backend != "redis":
            raise RuntimeError("The OCR worker requires JOB_BACKEND=redis")
        repository = self.container.repository
        assert isinstance(repository, RedisJobRepository)
        configure_logging(self.settings.log_level)
        await repository.recover_expired_leases()
        self.engine.initialize()  # Exactly once per worker process.
        heartbeat_ttl = self.settings.ocr_job_timeout_seconds + 60
        await repository.redis.set(WORKER_READY_KEY, "true", ex=heartbeat_ttl)
        try:
            while True:
                await repository.redis.expire(WORKER_READY_KEY, heartbeat_ttl)
                job = await repository.claim(timeout_seconds=5)
                if job is None:
                    continue
                await self._process(job.job_id)
        finally:
            await repository.redis.delete(WORKER_READY_KEY)
            await self.container.close()

    async def _process(self, job_id: str) -> None:
        repository = self.container.repository
        job = await repository.get(job_id)
        if job is None:
            await repository.acknowledge(job_id)
            return
        started = time.perf_counter()
        try:
            loop = asyncio.get_running_loop()

            def report_progress(processed_pages: int) -> None:
                job.processed_pages = processed_pages
                update = asyncio.run_coroutine_threadsafe(repository.update(job), loop)
                update.result()

            pages = await asyncio.wait_for(
                asyncio.to_thread(self._extract_pages, job, report_progress),
                timeout=self.settings.ocr_job_timeout_seconds,
            )
            result = OCRResult(
                job_id=job.job_id,
                document_id=job.input.document_id,
                engine=self.engine.engine_metadata,
                pages=pages,
            )
            job.status = JobStatus.COMPLETED
            job.processed_pages = len(pages)
            job.completed_at = utcnow()
            job.processing_ms = round((time.perf_counter() - started) * 1000)
            await repository.save_result(result, self.settings.result_ttl_seconds)
            await repository.update(job)
            JOBS_COMPLETED.inc()
            PROCESSING_SECONDS.observe(time.perf_counter() - started)
        except TimeoutError:
            await self._fail(job, "job_timeout", "OCR job exceeded its configured time limit")
        except Exception:
            logger.exception("OCR job failed", extra={"job_id": job_id})
            await self._fail(job, "ocr_processing_failed", "OCR processing failed")
        finally:
            await repository.acknowledge(job_id)
            self.container.temp_store.remove_job_dir(job_id)

    async def _fail(self, job: JobRecord, code: str, message: str) -> None:
        job.status = JobStatus.FAILED
        job.completed_at = utcnow()
        job.error_code = code
        job.error_message = message
        job.processing_ms = job.processing_ms or 0
        await self.container.repository.update(job)
        JOBS_FAILED.inc()

    def _extract_pages(
        self, job: JobRecord, report_progress: Callable[[int], None]
    ) -> list[PageResult]:
        source = Path(job.source_path)
        rendered = source.parent / "rendered"
        rendered.mkdir(exist_ok=True)
        pages = []
        if job.media_type == "image":
            normalized = rendered / "page-1.png"
            normalize_image(source, normalized, self.settings.ocr_max_image_pixels)
            pages.append(
                self.engine.extract_page(
                    normalized, job.input.page_number or 1, job.input.include_boxes
                )
            )
            report_progress(1)
            return pages
        page_start = (job.input.page_start or 1) - 1
        page_end = job.input.page_end or job.total_pages
        for page_index in range(page_start, page_end):
            output = rendered / f"page-{page_index + 1}.png"
            render_page_isolated(
                source,
                page_index,
                self.settings.ocr_render_dpi,
                output,
                self.settings.ocr_job_timeout_seconds,
            )
            normalize_image(output, output, self.settings.ocr_max_image_pixels)
            pages.append(self.engine.extract_page(output, page_index + 1, job.input.include_boxes))
            report_progress(len(pages))
        return pages


def main() -> None:
    asyncio.run(Worker().run())


if __name__ == "__main__":
    main()
