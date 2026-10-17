from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from starlette.datastructures import UploadFile as StarletteUploadFile

from ocr_service.api.dependencies import Container, get_container
from ocr_service.api.schemas import (
    JobAcceptedResponse,
    JobStatusResponse,
    ObjectReferenceRequest,
    PendingResultResponse,
)
from ocr_service.application.use_cases.submit_job import submit_job
from ocr_service.core.security import require_api_token
from ocr_service.domain.enums import JobStatus
from ocr_service.domain.errors import JobNotFoundError, PayloadTooLargeError, ResultExpiredError
from ocr_service.domain.models import JobInput
from ocr_service.infrastructure.telemetry.metrics import JOBS_SUBMITTED

router = APIRouter(prefix="/v1/jobs", tags=["jobs"], dependencies=[Depends(require_api_token)])


async def _save_upload(upload: StarletteUploadFile, max_bytes: int, destination_dir: Path) -> Path:
    suffix = Path(upload.filename or "upload").suffix[:12]
    with tempfile.NamedTemporaryFile(dir=destination_dir, suffix=suffix, delete=False) as target:
        path = Path(target.name)
        size = 0
        while chunk := await upload.read(1024 * 1024):
            size += len(chunk)
            if size > max_bytes:
                path.unlink(missing_ok=True)
                raise PayloadTooLargeError("Upload exceeds the configured size limit")
            target.write(chunk)
    return path


async def _submit_from_source(
    container: Container, source: Path, payload: JobInput, idempotency_key: str | None
) -> JobAcceptedResponse:
    job = await submit_job(
        container.repository,
        container.temp_store,
        container.settings,
        source,
        payload,
        idempotency_key,
    )
    JOBS_SUBMITTED.inc()
    return JobAcceptedResponse(
        job_id=job.job_id,
        status=job.status,
        created_at=job.created_at,
        status_url=f"/v1/jobs/{job.job_id}",
    )


@router.post("", response_model=JobAcceptedResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_job(
    request: Request,
    container: Container = Depends(get_container),
    idempotency_key: Annotated[str | None, Header()] = None,
) -> JobAcceptedResponse:
    declared_length = request.headers.get("content-length")
    maximum_body_bytes = container.settings.ocr_max_upload_mb * 1024 * 1024 + 100_000
    if declared_length and int(declared_length) > maximum_body_bytes:
        raise PayloadTooLargeError("Upload exceeds the configured size limit")

    content_type = request.headers.get("content-type", "")
    if content_type.startswith("application/json"):
        parsed = ObjectReferenceRequest.model_validate(await request.json())
        source = container.blob_store.resolve_object_key(parsed.object_key)
        payload = JobInput(**parsed.model_dump(exclude={"object_key"}))
        return await _submit_from_source(container, source, payload, idempotency_key)
    if not content_type.startswith("multipart/form-data"):
        raise HTTPException(status_code=415, detail="Use multipart/form-data or application/json")

    form = await request.form()
    upload = form.get("file")
    if not isinstance(upload, StarletteUploadFile):
        raise HTTPException(status_code=422, detail="A file field is required")
    fields = {name: value for name, value in form.items() if name != "file"}
    payload = JobInput.model_validate(fields)
    container.settings.ocr_temp_dir.mkdir(parents=True, exist_ok=True)
    source = await _save_upload(
        upload,
        container.settings.ocr_max_upload_mb * 1024 * 1024,
        container.settings.ocr_temp_dir,
    )
    try:
        return await _submit_from_source(container, source, payload, idempotency_key)
    finally:
        source.unlink(missing_ok=True)


@router.get("/{job_id}", response_model=JobStatusResponse)
async def get_job(job_id: str, container: Container = Depends(get_container)) -> JobStatusResponse:
    job = await container.repository.get(job_id)
    if job is None:
        raise JobNotFoundError("Job does not exist")
    return JobStatusResponse(
        job_id=job.job_id,
        status=job.status,
        processed_pages=job.processed_pages,
        total_pages=job.total_pages,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        processing_ms=job.processing_ms,
        error_code=job.error_code,
    )


@router.get("/{job_id}/result")
async def get_result(job_id: str, container: Container = Depends(get_container)) -> JSONResponse:
    job = await container.repository.get(job_id)
    if job is None:
        raise JobNotFoundError("Job does not exist")
    if job.status != JobStatus.COMPLETED:
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content=PendingResultResponse(job_id=job_id, status=job.status).model_dump(mode="json"),
        )
    result = await container.repository.get_result(job_id)
    if result is None:
        raise ResultExpiredError("Job result has expired")
    return JSONResponse(status_code=200, content=result.model_dump(mode="json"))


@router.delete("/{job_id}", response_model=JobStatusResponse)
async def cancel_job(
    job_id: str, container: Container = Depends(get_container)
) -> JobStatusResponse:
    job = await container.repository.cancel_queued(job_id)
    if job is None:
        raise JobNotFoundError("Job does not exist")
    return JobStatusResponse(
        job_id=job.job_id,
        status=job.status,
        processed_pages=job.processed_pages,
        total_pages=job.total_pages,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        processing_ms=job.processing_ms,
        error_code=job.error_code,
    )
