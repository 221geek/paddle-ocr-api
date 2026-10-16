from __future__ import annotations

import shutil
from pathlib import Path

from ocr_service.application.ports.blob_store import BlobStore
from ocr_service.domain.errors import InvalidInputError


class LocalObjectBlobStore(BlobStore):
    def __init__(self, root: Path, allowed_prefix: str) -> None:
        self.root = root.resolve()
        self.allowed_prefix = allowed_prefix

    def resolve_object_key(self, object_key: str) -> Path:
        if not object_key.startswith(self.allowed_prefix) or "://" in object_key:
            raise InvalidInputError("Object key is not allowed")
        candidate = (self.root / object_key).resolve()
        if self.root not in candidate.parents or not candidate.is_file():
            raise InvalidInputError("Referenced object does not exist")
        return candidate


class TempFileStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def job_dir(self, job_id: str) -> Path:
        path = self.root / job_id
        path.mkdir(mode=0o700, parents=True, exist_ok=False)
        return path

    def remove_job_dir(self, job_id: str) -> None:
        path = self.root / job_id
        if path.exists():
            shutil.rmtree(path)
