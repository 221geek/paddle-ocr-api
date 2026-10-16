from __future__ import annotations

import time
from collections import deque
from typing import Any

from redis.asyncio import Redis

from ocr_service.application.ports.job_repository import JobRepository
from ocr_service.domain.enums import JobStatus
from ocr_service.domain.models import JobRecord, OCRResult, utcnow

QUEUE_KEY = "ocr:jobs:queued"
PROCESSING_KEY = "ocr:jobs:processing"
JOB_KEY_PREFIX = "ocr:job:"
IDEMPOTENCY_KEY_PREFIX = "ocr:idempotency:"
RESULT_KEY_PREFIX = "ocr:result:"
WORKER_READY_KEY = "ocr:worker:ready"


class RedisJobRepository(JobRepository):
    def __init__(self, redis: Redis) -> None:
        # redis-py exposes sync/async unions to static analyzers. The instance is
        # created by redis.asyncio and only awaited methods are used here.
        self.redis: Any = redis

    @staticmethod
    def _job_key(job_id: str) -> str:
        return f"{JOB_KEY_PREFIX}{job_id}"

    async def ping(self) -> bool:
        return bool(await self.redis.ping())

    async def queue_size(self) -> int:
        return int(await self.redis.llen(QUEUE_KEY))

    async def get_by_idempotency_key(self, key: str) -> JobRecord | None:
        job_id = await self.redis.get(f"{IDEMPOTENCY_KEY_PREFIX}{key}")
        if not job_id:
            return None
        return await self.get(job_id.decode() if isinstance(job_id, bytes) else job_id)

    async def create(self, job: JobRecord) -> JobRecord:
        # Redis Lua executes atomically: concurrent API processes observing the same
        # idempotency key receive one job instead of queuing duplicate OCR work.
        existing_or_new_id = await self.redis.eval(
            """
            local current = redis.call('GET', KEYS[1])
            if current then return current end
            redis.call('SET', KEYS[1], ARGV[1])
            redis.call('SET', KEYS[2], ARGV[2])
            redis.call('LPUSH', KEYS[3], ARGV[1])
            return ARGV[1]
            """,
            3,
            f"{IDEMPOTENCY_KEY_PREFIX}{job.idempotency_key}",
            self._job_key(job.job_id),
            QUEUE_KEY,
            job.job_id,
            job.model_dump_json(),
        )
        job_id = (
            existing_or_new_id.decode()
            if isinstance(existing_or_new_id, bytes)
            else existing_or_new_id
        )
        if job_id == job.job_id:
            return job
        existing = await self.get(job_id)
        if existing is None:
            raise RuntimeError("Idempotency record exists without its OCR job")
        return existing

    async def get(self, job_id: str) -> JobRecord | None:
        raw = await self.redis.get(self._job_key(job_id))
        if raw is None:
            return None
        return JobRecord.model_validate_json(raw)

    async def update(self, job: JobRecord) -> None:
        await self.redis.set(self._job_key(job.job_id), job.model_dump_json())

    async def cancel_queued(self, job_id: str) -> JobRecord | None:
        job = await self.get(job_id)
        if job is None:
            return None
        if job.status is not JobStatus.QUEUED:
            return job
        job.status = JobStatus.CANCELLED
        job.completed_at = utcnow()
        await self.update(job)
        return job

    async def claim(self, timeout_seconds: int) -> JobRecord | None:
        # BRPOPLPUSH leaves the item in a processing list until acknowledged. A worker
        # restart can therefore requeue it after its lease expires.
        job_id = await self.redis.brpoplpush(QUEUE_KEY, PROCESSING_KEY, timeout=timeout_seconds)
        if job_id is None:
            return None
        if isinstance(job_id, bytes):
            job_id = job_id.decode()
        job = await self.get(job_id)
        if job is None:
            await self.acknowledge(job_id)
            return None
        if job.status is JobStatus.CANCELLED:
            await self.acknowledge(job_id)
            return None
        job.status = JobStatus.PROCESSING
        job.started_at = utcnow()
        job.attempts += 1
        await self.update(job)
        await self.redis.zadd("ocr:jobs:leases", {job_id: time.time()})
        return job

    async def acknowledge(self, job_id: str) -> None:
        pipeline = self.redis.pipeline(transaction=True)
        pipeline.lrem(PROCESSING_KEY, 0, job_id)
        pipeline.zrem("ocr:jobs:leases", job_id)
        await pipeline.execute()

    async def recover_expired_leases(self) -> int:
        # Leases make controlled worker restarts recoverable. Jobs are only retried a
        # bounded number of times; a third expired lease is recorded as a failure.
        cutoff = time.time() - 600
        raw_ids = await self.redis.zrangebyscore("ocr:jobs:leases", 0, cutoff)
        recovered = 0
        for raw_id in raw_ids:
            job_id = raw_id.decode() if isinstance(raw_id, bytes) else raw_id
            job = await self.get(job_id)
            if job is not None and job.attempts < 3 and job.status is JobStatus.PROCESSING:
                job.status = JobStatus.QUEUED
                job.started_at = None
                await self.update(job)
                await self.redis.lpush(QUEUE_KEY, job_id)
                recovered += 1
            elif job is not None and job.status is JobStatus.PROCESSING:
                job.status = JobStatus.FAILED
                job.completed_at = utcnow()
                job.error_code = "worker_lease_expired"
                job.error_message = "Worker stopped before completing the job"
                await self.update(job)
            await self.acknowledge(job_id)
        return recovered

    async def save_result(self, result: OCRResult, ttl_seconds: int) -> None:
        await self.redis.setex(
            f"{RESULT_KEY_PREFIX}{result.job_id}", ttl_seconds, result.model_dump_json()
        )

    async def get_result(self, job_id: str) -> OCRResult | None:
        raw = await self.redis.get(f"{RESULT_KEY_PREFIX}{job_id}")
        return None if raw is None else OCRResult.model_validate_json(raw)

    async def close(self) -> None:
        await self.redis.aclose()


class InMemoryJobRepository(JobRepository):
    """Small deterministic adapter for tests and local API exploration only."""

    def __init__(self) -> None:
        self.jobs: dict[str, JobRecord] = {}
        self.idempotency: dict[str, str] = {}
        self.results: dict[str, OCRResult] = {}
        self.queue: deque[str] = deque()
        self.processing: set[str] = set()

    async def ping(self) -> bool:
        return True

    async def queue_size(self) -> int:
        return len(self.queue)

    async def get_by_idempotency_key(self, key: str) -> JobRecord | None:
        job_id = self.idempotency.get(key)
        return self.jobs.get(job_id) if job_id else None

    async def create(self, job: JobRecord) -> JobRecord:
        self.jobs[job.job_id] = job
        self.idempotency[job.idempotency_key] = job.job_id
        self.queue.append(job.job_id)
        return job

    async def get(self, job_id: str) -> JobRecord | None:
        return self.jobs.get(job_id)

    async def update(self, job: JobRecord) -> None:
        self.jobs[job.job_id] = job

    async def cancel_queued(self, job_id: str) -> JobRecord | None:
        job = self.jobs.get(job_id)
        if job is not None and job.status is JobStatus.QUEUED:
            job.status = JobStatus.CANCELLED
            job.completed_at = utcnow()
        return job

    async def claim(self, timeout_seconds: int) -> JobRecord | None:
        del timeout_seconds
        while self.queue:
            job = self.jobs[self.queue.popleft()]
            if job.status is JobStatus.QUEUED:
                job.status = JobStatus.PROCESSING
                job.started_at = utcnow()
                job.attempts += 1
                self.processing.add(job.job_id)
                return job
        return None

    async def acknowledge(self, job_id: str) -> None:
        self.processing.discard(job_id)

    async def recover_expired_leases(self) -> int:
        return 0

    async def save_result(self, result: OCRResult, ttl_seconds: int) -> None:
        del ttl_seconds
        self.results[result.job_id] = result

    async def get_result(self, job_id: str) -> OCRResult | None:
        return self.results.get(job_id)

    async def close(self) -> None:
        return None
