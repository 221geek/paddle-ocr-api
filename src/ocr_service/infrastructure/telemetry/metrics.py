from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

JOBS_SUBMITTED = Counter("ocr_jobs_submitted_total", "Submitted OCR jobs")
JOBS_COMPLETED = Counter("ocr_jobs_completed_total", "Completed OCR jobs")
JOBS_FAILED = Counter("ocr_jobs_failed_total", "Failed OCR jobs")
PROCESSING_SECONDS = Histogram("ocr_job_processing_seconds", "OCR job processing duration")


def prometheus_payload() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST
