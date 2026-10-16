from pathlib import Path
from typing import Protocol


class BlobStore(Protocol):
    def resolve_object_key(self, object_key: str) -> Path: ...
