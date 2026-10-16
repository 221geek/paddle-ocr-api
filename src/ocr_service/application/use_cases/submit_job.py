from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from uuid import uuid4

from ocr_service.application.ports.job_repository import JobRepository
from ocr_service.core.config import Settings
from ocr_service.domain.errors import QueueSaturatedError
from ocr_service.domain.models import JobInput, JobRecord
from ocr_service.infrastructure.imaging.pdf_renderer import inspect_pdf
from ocr_service.infrastructure.imaging.preprocessor import detect_file_kind, inspect_image
from ocr_service.infrastructure.storage.local_temp import TempFileStore


def make_work_key(content_hash: str, job_input: JobInput, model_version: str) -> str:
    material = "|".join(
        [
            content_hash,
            str(job_input.page_number),
            str(job_input.page_start),
            str(job_input.page_end),
            job_input.language,
            job_input.model_profile,
            str(job_input.detect_layout),
            str(job_input.include_boxes),
            model_version,
        ]
    )
    return hashlib.sha256(material.encode()).hexdigest()


async def submit_job(
    repository: JobRepository,
    temp_store: TempFileStore,
    settings: Settings,
    source: Path,
    job_input: JobInput,
    supplied_idempotency_key: str | None,
) -> JobRecord:
    file_size = source.stat().st_size
    if file_size > settings.ocr_max_upload_mb * 1024 * 1024:
        from ocr_service.domain.errors import PayloadTooLargeError

        raise PayloadTooLargeError("Upload exceeds the configured size limit")
    with source.open("rb") as file_handle:
        content_hash = hashlib.file_digest(file_handle, "sha256").hexdigest()
    work_key = make_work_key(content_hash, job_input, "PP-OCRv5_mobile/pinned-at-build")
    idempotency_key = supplied_idempotency_key or work_key
    existing = await repository.get_by_idempotency_key(idempotency_key)
    if existing is not None:
        return existing
    if await repository.queue_size() >= settings.ocr_max_queued_jobs:
        raise QueueSaturatedError("OCR queue is at capacity")

    media_type = detect_file_kind(source)
    if media_type == "image":
        inspect_image(source, settings.ocr_max_image_pixels)
        if job_input.page_number is None:
            from ocr_service.domain.errors import InvalidInputError

            raise InvalidInputError("page_number is required for an image")
        total_pages = 1
    else:
        total_pages = inspect_pdf(source, settings.ocr_max_pages_per_job)
        start = job_input.page_start or 1
        end = job_input.page_end or total_pages
        if start > end or end > total_pages or end - start + 1 > settings.ocr_max_pages_per_job:
            from ocr_service.domain.errors import InvalidInputError

            raise InvalidInputError("Requested PDF page range is invalid")
        total_pages = end - start + 1

    job_id = f"ocr_{uuid4().hex}"
    job_dir = temp_store.job_dir(job_id)
    destination = job_dir / ("source.pdf" if media_type == "pdf" else "source.bin")
    try:
        shutil.copyfile(source, destination)
        job = JobRecord(
            job_id=job_id,
            idempotency_key=idempotency_key,
            input=job_input,
            source_path=str(destination),
            media_type=media_type,
            content_sha256=content_hash,
            total_pages=total_pages,
        )
        stored_job = await repository.create(job)
        if stored_job.job_id != job_id:
            temp_store.remove_job_dir(job_id)
        return stored_job
    except BaseException:
        temp_store.remove_job_dir(job_id)
        raise
