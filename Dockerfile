# PaddleOCR/PaddlePaddle versions are pinned in pyproject.toml.
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PADDLE_PDX_MODEL_SOURCE=BOS

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 libglib2.0-0 libgl1 curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN useradd --create-home --uid 10001 appuser && \
    mkdir -p /tmp/ocr /tmp/ocr-objects && chown -R appuser:appuser /tmp/ocr /tmp/ocr-objects /app
COPY pyproject.toml README.md requirements.lock ./
COPY src ./src
RUN pip install --no-cache-dir --require-hashes -r requirements.lock && \
    pip install --no-cache-dir --no-deps . && \
    chown -R appuser:appuser /app
USER appuser
RUN python -c "from paddleocr import PaddleOCR; PaddleOCR(lang='fr', device='cpu', use_doc_orientation_classify=False, use_doc_unwarping=False, use_textline_orientation=False); print('PaddleOCR weights preloaded')"

EXPOSE 8000
CMD ["uvicorn", "ocr_service.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]

