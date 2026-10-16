import secrets

from fastapi import Header, HTTPException, status

from ocr_service.core.config import get_settings


def require_api_token(authorization: str | None = Header(default=None)) -> None:
    expected = f"Bearer {get_settings().api_token}"
    if authorization is None or not secrets.compare_digest(authorization, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
