from datetime import datetime

from pydantic import BaseModel, Field

from ocr_service.domain.enums import JobStatus
from ocr_service.domain.models import JobInput, OCRResult


class ObjectReferenceRequest(JobInput):
    object_key: str = Field(min_length=1, max_length=1024)


class JobAcceptedResponse(BaseModel):
    job_id: str
    status: JobStatus
    created_at: datetime
    status_url: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    processed_pages: int
    total_pages: int
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    processing_ms: int | None
    error_code: str | None


class ErrorResponse(BaseModel):
    code: str
    message: str
    request_id: str


class PendingResultResponse(BaseModel):
    job_id: str
    status: JobStatus


ResultResponse = OCRResult | PendingResultResponse
