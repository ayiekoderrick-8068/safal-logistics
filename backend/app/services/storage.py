"""Local storage for compliance document files.

- File type is detected from magic bytes; the client-supplied content type is ignored.
- Files are stored under a random key, never a user-supplied path.
- Size is limited while streaming, so oversized uploads are never fully buffered.
"""

import hashlib
import re
import secrets
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException, UploadFile, status

from ..config import get_settings

SIGNATURES: dict[str, tuple[bytes, ...]] = {
    "application/pdf": (b"%PDF-",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
}
EXTENSIONS = {"application/pdf": ".pdf", "image/png": ".png", "image/jpeg": ".jpg"}
CHUNK = 64 * 1024


@dataclass(frozen=True)
class StoredFile:
    key: str
    name: str
    content_type: str
    size: int
    sha256: str


def _root() -> Path:
    root = get_settings().upload_dir
    root.mkdir(parents=True, exist_ok=True)
    return root


def path_for(key: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}", key):
        raise ValueError("invalid storage key")
    return _root() / key[:2] / key


def _detect(head: bytes) -> str | None:
    for content_type, signatures in SIGNATURES.items():
        if any(head.startswith(sig) for sig in signatures):
            return content_type
    return None


def _safe_name(name: str | None, content_type: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._ -]", "_", Path(name or "document").name).strip(" .") or "document"
    stem = stem[:120]
    ext = EXTENSIONS[content_type]
    return (
        stem
        if stem.lower().endswith(ext) or (ext == ".jpg" and stem.lower().endswith(".jpeg"))
        else stem + ext
    )


async def save_upload(upload: UploadFile) -> StoredFile:
    limit = get_settings().max_upload_bytes
    key = secrets.token_hex(16)
    target = path_for(key)
    target.parent.mkdir(parents=True, exist_ok=True)
    digest, size, content_type = hashlib.sha256(), 0, None
    try:
        with target.open("xb") as out:
            while chunk := await upload.read(CHUNK):
                if content_type is None:
                    content_type = _detect(chunk)
                    if content_type is None:
                        raise HTTPException(
                            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                            "Only PDF, PNG or JPEG files are accepted.",
                        )
                size += len(chunk)
                if size > limit:
                    raise HTTPException(
                        status.HTTP_413_CONTENT_TOO_LARGE,
                        f"File is larger than {limit // (1024 * 1024)} MB.",
                    )
                digest.update(chunk)
                out.write(chunk)
        if size == 0 or content_type is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The file is empty.")
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return StoredFile(
        key=key,
        name=_safe_name(upload.filename, content_type),
        content_type=content_type,
        size=size,
        sha256=digest.hexdigest(),
    )


def delete(key: str | None) -> None:
    if key:
        path_for(key).unlink(missing_ok=True)
