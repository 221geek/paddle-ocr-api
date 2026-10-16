from fastapi import APIRouter, Depends, HTTPException, Response, status

from ocr_service.api.dependencies import Container, get_container
from ocr_service.core.security import require_api_token
from ocr_service.infrastructure.persistence.redis_jobs import WORKER_READY_KEY, RedisJobRepository
from ocr_service.infrastructure.telemetry.metrics import prometheus_payload

router = APIRouter(tags=["technical"])


@router.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "live"}


@router.get("/health/ready")
async def ready(container: Container = Depends(get_container)) -> dict[str, str]:
    if not await container.repository.ping():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Job backend unavailable",
        )
    if isinstance(container.repository, RedisJobRepository):
        worker_ready = await container.repository.redis.get(WORKER_READY_KEY)
        if worker_ready != "true":
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="OCR worker not ready",
            )
    return {"status": "ready"}


@router.get("/metrics", dependencies=[Depends(require_api_token)], include_in_schema=False)
async def metrics() -> Response:
    payload, content_type = prometheus_payload()
    return Response(content=payload, media_type=content_type)
