from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ocr_service.domain.errors import DomainError


def request_id_for(request: Request) -> str:
    return getattr(request.state, "request_id", "unknown")


async def domain_error_handler(request: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, DomainError)
    return JSONResponse(
        status_code=error.status_code,
        content={
            "code": error.code,
            "message": error.message,
            "request_id": request_id_for(request),
        },
    )


async def validation_error_handler(request: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, RequestValidationError)
    return JSONResponse(
        status_code=422,
        content={
            "code": "validation_error",
            "message": "Request parameters are invalid",
            "request_id": request_id_for(request),
        },
    )


async def http_error_handler(request: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, HTTPException)
    detail = error.detail if isinstance(error.detail, str) else "Request could not be completed"
    code = {
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        413: "payload_too_large",
        415: "unsupported_media_type",
        422: "validation_error",
        503: "service_unavailable",
    }.get(error.status_code, "http_error")
    return JSONResponse(
        status_code=error.status_code,
        content={"code": code, "message": detail, "request_id": request_id_for(request)},
    )
