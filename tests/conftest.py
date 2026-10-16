from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path) -> Generator[TestClient, None, None]:
    monkeypatch.setenv("API_TOKEN", "test-token-that-is-long-enough")
    monkeypatch.setenv("JOB_BACKEND", "memory")
    monkeypatch.setenv("OCR_TEMP_DIR", str(tmp_path / "temp"))
    monkeypatch.setenv("OCR_OBJECT_STORE_DIR", str(tmp_path / "objects"))
    from ocr_service.core.config import get_settings

    get_settings.cache_clear()
    from ocr_service.main import app

    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()


@pytest.fixture()
def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token-that-is-long-enough"}
