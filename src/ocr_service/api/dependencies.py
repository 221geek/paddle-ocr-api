from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from fastapi import Request
from redis.asyncio import Redis

from ocr_service.application.ports.job_repository import JobRepository
from ocr_service.core.config import Settings
from ocr_service.infrastructure.persistence.redis_jobs import (
    InMemoryJobRepository,
    RedisJobRepository,
)
from ocr_service.infrastructure.storage.local_temp import LocalObjectBlobStore, TempFileStore


@dataclass
class Container:
    settings: Settings
    repository: JobRepository
    temp_store: TempFileStore
    blob_store: LocalObjectBlobStore

    async def close(self) -> None:
        await self.repository.close()


def build_container(settings: Settings) -> Container:
    repository: JobRepository
    if settings.job_backend == "memory":
        repository = InMemoryJobRepository()
    else:
        repository = RedisJobRepository(Redis.from_url(settings.redis_url, decode_responses=True))
    return Container(
        settings=settings,
        repository=repository,
        temp_store=TempFileStore(settings.ocr_temp_dir),
        blob_store=LocalObjectBlobStore(
            settings.ocr_object_store_dir, settings.ocr_allowed_object_prefix
        ),
    )


def get_container(request: Request) -> Container:
    return cast(Container, request.app.state.container)
