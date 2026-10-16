from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    log_level: str = "INFO"
    api_token: str = Field(min_length=16)
    redis_url: str = "redis://redis:6379/2"
    job_backend: str = "redis"
    ocr_model_profile: str = "mobile"
    ocr_max_concurrent_jobs: int = Field(default=1, ge=1, le=4)
    ocr_max_upload_mb: int = Field(default=50, ge=1, le=500)
    ocr_max_pages_per_job: int = Field(default=30, ge=1, le=500)
    ocr_render_dpi: int = Field(default=250, ge=72, le=400)
    ocr_max_image_pixels: int = Field(default=30_000_000, ge=1_000_000)
    ocr_job_timeout_seconds: int = Field(default=600, ge=10, le=3600)
    ocr_result_ttl_hours: int = Field(default=72, ge=1, le=720)
    ocr_temp_dir: Path = Path("/tmp/ocr")
    ocr_max_queued_jobs: int = Field(default=100, ge=1)
    ocr_allowed_object_prefix: str = "archives/"
    ocr_object_store_dir: Path = Path("/tmp/ocr-objects")
    prometheus_metrics_token: str | None = None
    paddle_num_threads: int = Field(default=2, ge=1, le=32)

    @field_validator("job_backend")
    @classmethod
    def validate_backend(cls, value: str) -> str:
        if value not in {"redis", "memory"}:
            raise ValueError("JOB_BACKEND must be 'redis' or 'memory'")
        return value

    @property
    def result_ttl_seconds(self) -> int:
        return self.ocr_result_ttl_hours * 3600


@lru_cache
def get_settings() -> Settings:
    return Settings()
