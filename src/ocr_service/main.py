from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.middleware.base import RequestResponseEndpoint

from ocr_service.api.dependencies import build_container
from ocr_service.api.exception_handlers import (
    domain_error_handler,
    http_error_handler,
    validation_error_handler,
)
from ocr_service.api.v1.routes import health, jobs
from ocr_service.core.config import get_settings
from ocr_service.core.logging import configure_logging
from ocr_service.domain.errors import DomainError


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    app.state.container = build_container(settings)
    yield
    await app.state.container.close()


async def unexpected_error_handler(request: Request, error: Exception) -> JSONResponse:
    # Deliberately do not serialize exception details: OCR input can be sensitive.
    del error
    return JSONResponse(
        status_code=500,
        content={
            "code": "internal_error",
            "message": "An unexpected error occurred",
            "request_id": getattr(request.state, "request_id", "unknown"),
        },
    )


app = FastAPI(
    title="Paddle OCR API",
    version="1.0.0",
    description="Asynchronous CPU-first OCR service. API version is carried by /v1.",
    lifespan=lifespan,
)
app.include_router(health.router)
app.include_router(jobs.router)
app.add_exception_handler(DomainError, domain_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.add_exception_handler(Exception, unexpected_error_handler)
app.add_exception_handler(HTTPException, http_error_handler)


@app.middleware("http")
async def request_context(request: Request, call_next: RequestResponseEndpoint) -> Response:
    request.state.request_id = request.headers.get("X-Request-ID", uuid.uuid4().hex)
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    return response
