from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ocr_service.domain.enums import JobStatus


def utcnow() -> datetime:
    return datetime.now(UTC)


class JobInput(BaseModel):
    archive_id: str = Field(min_length=1, max_length=200)
    document_id: str = Field(min_length=1, max_length=200)
    page_number: int | None = Field(default=None, ge=1)
    language: Literal["fr"] = "fr"
    model_profile: Literal["mobile"] = "mobile"
    detect_layout: bool = True
    include_boxes: bool = True
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)


class JobRecord(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    job_id: str
    idempotency_key: str
    input: JobInput
    source_path: str
    media_type: Literal["image", "pdf"]
    content_sha256: str
    status: JobStatus = JobStatus.QUEUED
    created_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    total_pages: int = 0
    processed_pages: int = 0
    error_code: str | None = None
    error_message: str | None = None
    processing_ms: int | None = None
    attempts: int = 0


class PolygonBlock(BaseModel):
    id: str
    text: str
    confidence: float = Field(ge=0, le=1)
    polygon: list[list[float]]
    reading_order: int


class PageResult(BaseModel):
    page_number: int
    width: int
    height: int
    text: str
    blocks: list[PolygonBlock]
    processing_ms: int
    warnings: list[str] = Field(default_factory=list)


class OCRResult(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    job_id: str
    document_id: str
    engine: dict[str, str]
    pages: list[PageResult]
