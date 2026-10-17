# Paddle OCR API

> Async, CPU-first, self-hostable OCR microservice for images and scanned PDFs.

Paddle OCR API extracts text from newspaper pages, retains blocks and their coordinates, and
returns stable JSON. It is designed to be called by an application backend — for example,
NestJS — which remains responsible for archiving, search, and indexing.

The project prioritizes controlled resource usage: a lightweight FastAPI API, Redis for jobs,
a single OCR worker, and PaddleOCR loaded only once per process.

## Features

- Versioned REST API under `/v1` with built-in OpenAPI documentation.
- Async jobs: `queued`, `processing`, `completed`, `failed`, and `cancelled`.
- PNG, JPEG, WebP, and multipage scanned PDFs, rendered one page at a time.
- Text, OCR blocks, polygons, confidence scores, and estimated reading order.
- French PP-OCRv5 Mobile on CPU, loaded once per worker.
- Atomic Redis idempotency, recovery leases, and expiring results.
- Limits for size, pages, pixels, queue depth, and processing time.
- Bearer authentication, correlated JSON logs, and Prometheus metrics.
- Non-root Docker image; separate API, worker, and Redis services.

### Out of scope

This project does not provide search, indexing, RAG, embeddings, or business-data persistence.
It does not correct text with an LLM. Reading order is a geometric heuristic: validate it on
the multi-column pages in your corpus before relying on it for critical business use.

## Architecture

```text
Client / application backend
        | POST /v1/jobs
        v
FastAPI ── auth, validation, limits, status
        |
        v
Redis ── jobs, idempotency, leases, TTL results
        |
        v
Single worker ── PaddleOCR loaded once
        |
        +─ image: minimal EXIF rotation -> OCR
        +─ PDF: isolated rendering -> one page -> OCR -> next page
        v
Versioned JSON result
```

```text
src/ocr_service/
├── api/              # FastAPI HTTP adapter
├── application/      # Use cases and interfaces (ports)
├── domain/           # Framework-independent models and errors
├── infrastructure/   # Redis, storage, PDF, image, PaddleOCR, metrics
├── workers/          # OCR worker loop
└── core/             # Configuration, logging, and security
```

## Prerequisites and quick start

- Docker Engine and Docker Compose v2 for the recommended runtime.
- Or Python 3.11 and [uv](https://docs.astral.sh/uv/) to contribute.
- Redis 7+ reachable by the API and worker.
- As a starting point, 4 vCPUs and 8 GB RAM for one isolated CPU OCR worker is prudent.

```bash
git clone https://github.com/221geek/paddle-ocr-api.git
cd paddle-ocr-api
cp .env.example .env
```

Set a random secret of at least 16 characters in `.env`:

```dotenv
API_TOKEN=replace-me-with-a-long-random-secret
```

Build and start the three services:

```bash
docker compose up --build
```

The image initializes PaddleOCR as root during the build because PaddleX writes a font to its
own package directory. Model weights and cache are then made available to `appuser`, the
non-root user that runs the API and worker. The worker therefore does not download models at
startup.

```bash
curl http://localhost:8000/health/live
curl http://localhost:8000/health/ready
```

`/health/ready` returns `503` until Redis and the OCR worker are ready.

### Development without Docker

```bash
uv sync --all-extras
uv run pytest
uv run ruff check .
uv run mypy src
```

The `memory` backend is intended for tests and local exploration only: it provides neither
durability, recovery, nor idempotency across multiple processes.

```bash
export API_TOKEN='a-very-long-development-secret'
export JOB_BACKEND=memory
uv run uvicorn ocr_service.main:app --reload
```

## API reference

Interactive documentation is available at [http://localhost:8000/docs](http://localhost:8000/docs)
and the OpenAPI schema at [http://localhost:8000/openapi.json](http://localhost:8000/openapi.json).

All job and metrics endpoints require:

```http
Authorization: Bearer <API_TOKEN>
```

Application errors use a stable structure:

```json
{
  "code": "payload_too_large",
  "message": "Upload exceeds the configured size limit",
  "request_id": "4c1570a1c6b248cd8f8a6083281f1fc5"
}
```

The `request_id` is also returned in the `X-Request-ID` header. You can supply your own
`X-Request-ID` to correlate it with the calling system.

### Create a job

```bash
curl --request POST http://localhost:8000/v1/jobs \
  --header "Authorization: Bearer <API_TOKEN>" \
  --header "Idempotency-Key: newspaper-1978-page-1" \
  --form archive_id=newspaper_1978 \
  --form document_id=newspaper_1978_0042 \
  --form page_number=1 \
  --form language=fr \
  --form include_boxes=true \
  --form file=@page-1.jpg
```

`202 Accepted` response:

```json
{
  "job_id": "ocr_7b4e7b9f7ec44d3a8ed08d8e6bb51ef3",
  "status": "queued",
  "created_at": "2026-10-16T15:00:00Z",
  "status_url": "/v1/jobs/ocr_7b4e7b9f7ec44d3a8ed08d8e6bb51ef3"
}
```

| Field | Required | Description |
| --- | --- | --- |
| `file` | yes | PNG, JPEG, WebP, or scanned PDF |
| `archive_id` | yes | Identifier of the calling archive |
| `document_id` | yes | Business identifier of the document |
| `page_number` | image | Page number, starting at 1 |
| `page_start`, `page_end` | PDF | Inclusive page bounds, starting at 1 |
| `language` | no | Currently fixed to `fr` |
| `model_profile` | no | Currently fixed to `mobile` |
| `detect_layout` | no | Reserved for future segmentation work |
| `include_boxes` | no | Returns or hides polygons |

Files are verified by signature, not only by extension or `Content-Type`.

### Internal object reference

To avoid sending a large document over HTTP, you can pass a JSON reference to approved internal
storage:

```bash
curl --request POST http://localhost:8000/v1/jobs \
  --header "Authorization: Bearer <API_TOKEN>" \
  --header "Content-Type: application/json" \
  --data '{
    "archive_id": "newspaper_1978",
    "document_id": "newspaper_1978_0042",
    "page_number": 1,
    "object_key": "archives/newspaper_1978/page-1.jpg"
  }'
```

Arbitrary URLs are intentionally refused to prevent SSRF. The supplied adapter resolves only
keys under `OCR_OBJECT_STORE_DIR`, prefixed by `OCR_ALLOWED_OBJECT_PREFIX`. For S3 or
another storage service, implement the `application/ports/blob_store.py` port.

### Retrieve a job and its result

`GET /v1/jobs/{job_id}` returns its state and progress:

```json
{
  "job_id": "ocr_7b4e7b9f7ec44d3a8ed08d8e6bb51ef3",
  "status": "processing",
  "processed_pages": 2,
  "total_pages": 12,
  "created_at": "2026-10-16T15:00:00Z",
  "started_at": "2026-10-16T15:00:03Z",
  "completed_at": null,
  "processing_ms": null,
  "error_code": null
}
```

`GET /v1/jobs/{job_id}/result` returns:

| Response | Meaning |
| --- | --- |
| `202` | Processing is not complete |
| `200` | Result available |
| `404` | Unknown job |
| `410` | Job completed but result expired |

Example result:

```json
{
  "schema_version": "1.0",
  "job_id": "ocr_7b4e7b9f7ec44d3a8ed08d8e6bb51ef3",
  "document_id": "newspaper_1978_0042",
  "engine": {
    "name": "paddleocr",
    "model": "PP-OCRv5_mobile",
    "version": "pinned-at-build"
  },
  "pages": [{
    "page_number": 1,
    "width": 2480,
    "height": 3508,
    "text": "Normalized page text…",
    "blocks": [{
      "id": "b1",
      "text": "Newspaper headline",
      "confidence": 0.98,
      "polygon": [[120,80],[1100,80],[1100,210],[120,210]],
      "reading_order": 0
    }],
    "processing_ms": 1234,
    "warnings": []
  }]
}
```

Coordinates are expressed in the OCR image coordinate system. For a PDF, that is the image
rendered at the configured DPI. PaddleOCR scores are informative, not calibrated probabilities.
`DELETE /v1/jobs/{job_id}` cancels a queued job; an inference already in progress is not
interrupted, so PaddleOCR is not left in an inconsistent state.

### Operational endpoints

| Endpoint | Authentication | Purpose |
| --- | --- | --- |
| `GET /health/live` | none | The HTTP process responds |
| `GET /health/ready` | none | Redis and the OCR worker are ready |
| `GET /metrics` | Bearer | Prometheus metrics; private network only |

## Idempotency, retries, and recovery

The work key combines the content SHA-256, requested pages, OCR settings, and model version.
If the client sends `Idempotency-Key`, it becomes the deduplication key: therefore use a
unique key for every business request.

Redis uses an atomic Lua operation to prevent concurrent submissions from creating two jobs.
The worker holds a lease while processing a job. After a restart, expired leases are requeued
up to twice; the third failure produces the stable `worker_lease_expired` code.

## Configuration

Copy [`.env.example`](.env.example) to `.env` in development. In production, declare these
values as Coolify secrets or variables, and never commit `.env`.

| Variable | Default | Purpose |
| --- | --- | --- |
| `APP_ENV` | `development` | Application environment |
| `LOG_LEVEL` | `INFO` | JSON log level |
| `API_TOKEN` | — | Bearer secret, at least 16 characters |
| `REDIS_URL` | `redis://redis:6379/2` | Redis for jobs and results |
| `JOB_BACKEND` | `redis` | `redis` in production; `memory` for tests |
| `OCR_MODEL_PROFILE` | `mobile` | Public CPU profile; engine intentionally fixed |
| `OCR_MAX_CONCURRENT_JOBS` | `1` | A worker processes sequentially |
| `OCR_MAX_UPLOAD_MB` | `50` | Maximum upload size |
| `OCR_MAX_PAGES_PER_JOB` | `30` | Maximum pages per PDF/range |
| `OCR_RENDER_DPI` | `250` | PDF DPI, between 72 and 400 |
| `OCR_MAX_IMAGE_PIXELS` | `30000000` | Protection from decompressed images |
| `OCR_JOB_TIMEOUT_SECONDS` | `600` | Maximum job duration |
| `OCR_RESULT_TTL_HOURS` | `72` | Temporary result retention |
| `OCR_TEMP_DIR` | `/tmp/ocr` | Shared temporary directory |
| `OCR_MAX_QUEUED_JOBS` | `100` | Queue capacity before a `429` |
| `OCR_ALLOWED_OBJECT_PREFIX` | `archives/` | Allowed object-reference prefix |
| `OCR_OBJECT_STORE_DIR` | `/tmp/ocr-objects` | Root of the local object adapter |
| `PADDLE_NUM_THREADS` | `2` | Paddle OpenMP/MKL threads |

## Coolify deployment

[`compose.yaml`](compose.yaml) defines three services:

1. **api**: FastAPI/Uvicorn; does not initialize PaddleOCR.
2. **worker**: initializes PaddleOCR once and processes jobs one at a time.
3. **redis**: queue, states, leases, and temporary results.

Recommended procedure:

1. Connect the GitHub repository and deploy the `main` branch with Docker Compose.
2. Set at least `API_TOKEN`, `REDIS_URL`, `APP_ENV=production`, and `JOB_BACKEND=redis`.
3. Put Redis, the API, and the worker on an internal network.
4. Do not expose Redis or `/metrics`. If NestJS is the only caller, do not make the API public.
5. Start with one worker and set CPU/RAM limits consistent with your VPS.
6. Use `/health/live` for the process and `/health/ready` for application readiness.

The first build requires outbound access to PaddleOCR resources in order to preload weights.
Startup does not download them. If the build server has no outbound access, build the image in
an authorized CI environment and push it to a private registry.

## Security and operations

- Never store `API_TOKEN` in Git or logs.
- Files are limited and inspected by signature, dimensions, and page count.
- PDFs are rendered one page at a time in an isolated process with a timeout.
- Client URLs are rejected; object references remain under a controlled root.
- Redis results expire: archive them in the application system if retention must be durable.
- Application containers run as non-root with a read-only application filesystem.
- Logs contain neither document text nor access tokens.

| HTTP | Code | Context |
| --- | --- | --- |
| `401` | `unauthorized` | Missing or invalid token |
| `413` | `payload_too_large` | Upload too large |
| `415` | `unsupported_media_type` | Unsupported file |
| `422` | `validation_error` / `invalid_input` | Invalid parameters or document |
| `429` | `queue_saturated` | OCR queue full |
| `503` | `ocr_not_ready` / `service_unavailable` | Dependency or worker unavailable |

## OCR quality and benchmarks

Evaluate the service on your own newspapers: small text, columns, headlines, ads, skewed pages,
yellowed backgrounds, and photos. Keep manual transcriptions and measure:

- **CER** — Character Error Rate.
- **WER** — Word Error Rate.
- Recall of proper nouns, dates, and critical keywords.
- Multi-column reading order.
- p50/p95, pages per minute, and RSS for 20, 100, then 1,000 pages.

The following script loads the engine once and produces a JSON report:

```bash
python scripts/benchmark.py /path/to/corpus --output benchmark-report.json
```

The report contains `pages`, `p50_ms`, `p95_ms`, `pages_per_minute`, and `max_rss_kb`.
Keep it with the CER/WER measurements; do not present throughput as a universal guarantee.

## Development and contributing

### Quality commands

```bash
uv run pytest
uv run ruff format --check .
uv run ruff check .
uv run mypy src
```

Tests cover HTTP contracts, authentication, file limits, idempotency, and PaddleOCR result
mapping. Add representative fixtures before running OCR integration and load tests.

### Reproducible dependencies

[`uv.lock`](uv.lock) locks dependency resolution. [`requirements.lock`](requirements.lock)
is exported with hashes and used by the Docker image.

```bash
uv lock
uv export --frozen --no-dev --no-emit-project --format requirements-txt --output-file requirements.lock
```

Ruff hooks are declared in [`.pre-commit-config.yaml`](.pre-commit-config.yaml).

### Contributing

1. Open an issue describing the need or bug.
2. Create a focused branch and add the required tests.
3. Run the quality commands.
4. Open a concise pull request and document any operational impact.

Natural next improvements are a signed S3 adapter, durable result storage, an OCR integration
corpus, a load-test campaign, and column segmentation validated on real data.

## License

This repository does not yet include a license. Before reuse, package publication, or external
contribution, the maintainer must add an explicit license — for example MIT, Apache-2.0, or
GPL-3.0, depending on the project's intended use.

