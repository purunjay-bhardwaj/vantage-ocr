"""
Step 1 – Receive and validate an uploaded file.
Magic-byte check; do not trust the extension or the Content-Type header.
"""
from __future__ import annotations

import secrets
import tempfile
import uuid
from pathlib import Path

# Magic bytes → MIME
_MAGIC: list[tuple[bytes, str]] = [
    (b"%PDF", "application/pdf"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
]

_ALLOWED_MIME = {"application/pdf", "image/jpeg", "image/png"}


class UploadError(ValueError):
    pass


def detect_mime(data: bytes) -> str | None:
    for magic, mime in _MAGIC:
        if data[:len(magic)] == magic:
            return mime
    return None


def validate_upload(data: bytes, max_bytes: int) -> str:
    """
    Validate size and magic bytes.
    Returns the detected MIME type.
    Raises UploadError on problems (generic message only – no content logged).
    """
    if len(data) > max_bytes:
        raise UploadError("file_too_large")
    if len(data) == 0:
        raise UploadError("file_empty")

    mime = detect_mime(data)
    if mime not in _ALLOWED_MIME:
        raise UploadError("unsupported_format")

    return mime


def random_storage_name(mime: str) -> str:
    """Return a random storage name (no PII, no original filename)."""
    ext = {
        "application/pdf": ".pdf",
        "image/jpeg": ".jpg",
        "image/png": ".png",
    }.get(mime, ".bin")
    return f"{uuid.uuid4().hex}{ext}"
