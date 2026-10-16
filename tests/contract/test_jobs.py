from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image


def image_payload() -> bytes:
    image = Image.new("RGB", (16, 16), color="white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def submit(client: TestClient, headers: dict[str, str], key: str = "stable-key"):
    return client.post(
        "/v1/jobs",
        headers={**headers, "Idempotency-Key": key},
        data={"archive_id": "archive", "document_id": "journal", "page_number": "1"},
        files={"file": ("page.png", image_payload(), "image/png")},
    )


def test_submit_and_get_job_are_versioned_and_structured(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = submit(client, auth_headers)
    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["status_url"] == f"/v1/jobs/{payload['job_id']}"

    status_response = client.get(payload["status_url"], headers=auth_headers)
    assert status_response.status_code == 200
    assert status_response.json()["total_pages"] == 1

    result_response = client.get(f"{payload['status_url']}/result", headers=auth_headers)
    assert result_response.status_code == 202


def test_same_idempotency_key_does_not_enqueue_a_second_job(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    first = submit(client, auth_headers, "same-key")
    second = submit(client, auth_headers, "same-key")
    assert first.status_code == second.status_code == 202
    assert first.json()["job_id"] == second.json()["job_id"]


def test_authentication_error_is_structured(client: TestClient) -> None:
    response = client.get("/v1/jobs/missing")
    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"
    assert response.json()["request_id"]


def test_rejects_an_unsupported_upload(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.post(
        "/v1/jobs",
        headers=auth_headers,
        data={"archive_id": "archive", "document_id": "journal", "page_number": "1"},
        files={"file": ("unsafe.txt", b"not an image", "text/plain")},
    )
    assert response.status_code == 415
    assert response.json()["code"] == "unsupported_media_type"
