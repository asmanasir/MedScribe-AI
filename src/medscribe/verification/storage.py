from __future__ import annotations

"""
File storage abstraction for verification documents.

Keeps file I/O behind an interface so swapping local → S3/Azure Blob
is a single-line config change with no route or service changes.

Current implementation: local filesystem (suitable for dev/demo).
Production: swap to AzureBlobStorage or S3Storage by changing VERIFICATION_STORAGE_BACKEND env var.
"""

import os
from pathlib import Path
from uuid import UUID

STORAGE_ROOT = Path(os.getenv("VERIFICATION_STORAGE_PATH", "./verification_uploads"))


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def save_document(verification_id: UUID, document_id: UUID, content: bytes, file_name: str) -> str:
    """
    Persist raw file bytes. Returns the storage path (opaque handle).
    In production this would return a signed URL or blob path.
    """
    folder = STORAGE_ROOT / str(verification_id)
    _ensure_dir(folder)
    dest = folder / f"{document_id}_{file_name}"
    dest.write_bytes(content)
    return str(dest)


def load_document(path: str) -> bytes:
    """Load file bytes by storage path. Raises FileNotFoundError if missing."""
    return Path(path).read_bytes()


def delete_verification_files(verification_id: UUID) -> None:
    """GDPR purge — delete all files for a verification case."""
    import shutil
    folder = STORAGE_ROOT / str(verification_id)
    if folder.exists():
        shutil.rmtree(folder)
