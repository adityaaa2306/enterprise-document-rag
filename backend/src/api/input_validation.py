"""
Strict request validation / sanitization for HTTP boundaries.

Defends against:
- SQL injection (reject null bytes / oversized ids; DB layer uses ORM binds)
- Command injection (reject shell metacharacters in identifiers / filenames)
- Script injection (strip control chars and dangerous HTML from free text)
- Unsafe uploads (extension + MIME + magic-byte allowlist, size caps)
"""
from __future__ import annotations

import os
import re
import uuid
import zipfile
from io import BytesIO
from typing import Annotated, Final, Optional

from fastapi import HTTPException, Path, Query, UploadFile
from pydantic import AfterValidator

# --- Limits -----------------------------------------------------------------

MAX_QUERY_CHARS: Final[int] = 8_000
MAX_FULL_NAME_CHARS: Final[int] = 120
MAX_EMAIL_CHARS: Final[int] = 254
MAX_PASSWORD_CHARS: Final[int] = 128  # bcrypt uses first 72 bytes
MAX_REFRESH_TOKEN_CHARS: Final[int] = 512
MAX_NODE_ID_CHARS: Final[int] = 128
MAX_FILENAME_CHARS: Final[int] = 180
# Authenticated users; guests use GUEST_MAX_PDF_BYTES from owner.py
DEFAULT_MAX_UPLOAD_BYTES: Final[int] = 50 * 1024 * 1024

ALLOWED_UPLOAD_EXTENSIONS: Final[frozenset[str]] = frozenset(
    {".pdf", ".docx", ".txt", ".csv"}
)
ALLOWED_UPLOAD_CONTENT_TYPES: Final[frozenset[str]] = frozenset(
    {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword",
        "text/plain",
        "text/csv",
        "application/csv",
        "application/octet-stream",  # browsers often omit real MIME
    }
)

DASHBOARD_RANGE_KEYS: Final[frozenset[str]] = frozenset(
    {"today", "7d", "30d", "90d", "custom"}
)

ROUTING_MODES: Final[frozenset[str]] = frozenset(
    {
        "automatic",
        "fastest",
        "lowest_cost",
        "lowest_carbon",
        "highest_quality",
        "eco",
        "balanced",
        "performance",
        "quality",
        "auto",
        "smart",
        "smart_routing",
        "max_quality",
        "prefer_fastest",
        "prefer_lowest_cost",
        "prefer_lowest_carbon",
        "prefer_highest_quality",
    }
)

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_NODE_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
# Shell / path metacharacters that must never appear in identifiers
_ID_FORBIDDEN_RE = re.compile(r"[;&|`$<>\\\n\r\0]|(\.\./)")
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SCRIPT_RE = re.compile(
    r"(?is)<\s*script\b|javascript\s*:|on\w+\s*=|<\s*iframe\b|<\s*object\b|<\s*embed\b"
)


# --- Primitive sanitizers ---------------------------------------------------

def strip_controls(value: str, *, allow_newlines: bool = True) -> str:
    """Remove NUL / C0 controls (optionally keep \\t \\n \\r)."""
    if value is None:
        return ""
    text = str(value).replace("\x00", "")
    if allow_newlines:
        text = _CTRL_RE.sub("", text)
    else:
        text = re.sub(r"[\x00-\x1f\x7f]", "", text)
    return text.strip()


def sanitize_user_text(value: str, *, max_chars: int = MAX_QUERY_CHARS) -> str:
    """Sanitize free-form user text (queries, names). Rejects script payloads."""
    text = strip_controls(value, allow_newlines=True)
    if len(text) > max_chars:
        raise ValueError(f"Must be at most {max_chars} characters")
    if _SCRIPT_RE.search(text):
        raise ValueError("Input contains disallowed script content")
    return text


def require_uuid(value: str, *, field: str = "id") -> str:
    raw = strip_controls(value, allow_newlines=False)
    if not raw or _ID_FORBIDDEN_RE.search(raw):
        raise ValueError(f"Invalid {field}")
    if not _UUID_RE.match(raw):
        raise ValueError(f"Invalid {field}: expected UUID")
    # Canonical lowercase UUID string
    try:
        return str(uuid.UUID(raw))
    except ValueError as exc:
        raise ValueError(f"Invalid {field}: expected UUID") from exc


def require_node_id(value: str) -> str:
    raw = strip_controls(value, allow_newlines=False)
    if not raw or not _NODE_ID_RE.match(raw) or _ID_FORBIDDEN_RE.search(raw):
        raise ValueError("Invalid node_id")
    return raw


def require_email(value: str) -> str:
    raw = strip_controls(value, allow_newlines=False).lower()
    if not raw or len(raw) > MAX_EMAIL_CHARS:
        raise ValueError("Invalid email")
    if not _EMAIL_RE.match(raw):
        raise ValueError("Invalid email format")
    return raw


def require_dashboard_range(value: str) -> str:
    key = strip_controls(value, allow_newlines=False).lower()
    if key not in DASHBOARD_RANGE_KEYS:
        raise ValueError(
            f"Invalid range; allowed: {', '.join(sorted(DASHBOARD_RANGE_KEYS))}"
        )
    return key


def require_optional_date(value: Optional[str]) -> Optional[str]:
    if value is None or value == "":
        return None
    raw = strip_controls(value, allow_newlines=False)
    if not _DATE_RE.match(raw):
        raise ValueError("Date must be YYYY-MM-DD")
    return raw


def require_routing_mode(value: str) -> str:
    raw = strip_controls(value or "automatic", allow_newlines=False).lower().replace("-", "_")
    if len(raw) > 64 or _ID_FORBIDDEN_RE.search(raw):
        raise ValueError("Invalid mode")
    # Allow space alias used by clients ("max quality")
    alias = raw.replace(" ", "_") if " " in raw else raw
    if alias == "max_quality" or raw == "max quality":
        return "highest_quality"
    if raw not in ROUTING_MODES and alias not in ROUTING_MODES:
        raise ValueError(
            "Invalid mode; allowed: automatic, fastest, lowest_cost, "
            "lowest_carbon, highest_quality"
        )
    return alias if alias in ROUTING_MODES else raw


def safe_filename(name: Optional[str]) -> str:
    base = os.path.basename(name or "upload.bin")
    cleaned = "".join(c if c.isalnum() or c in "._- " else "_" for c in base).strip()
    cleaned = cleaned.lstrip(".")
    if not cleaned or cleaned in {".", ".."}:
        cleaned = "upload.bin"
    return cleaned[:MAX_FILENAME_CHARS]


def _ext(filename: str) -> str:
    return os.path.splitext(filename)[1].lower()


def validate_upload_bytes(filename: str, content_type: str, data: bytes) -> str:
    """
    Validate upload content. Returns canonical content_type to store.
    Raises HTTPException on rejection.
    """
    if not data:
        raise HTTPException(status_code=400, detail="Empty upload.")
    fname = safe_filename(filename)
    ext = _ext(fname)
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type '{ext or '(none)'}'. "
            f"Allowed: {', '.join(sorted(ALLOWED_UPLOAD_EXTENSIONS))}",
        )
    ct = (content_type or "application/octet-stream").split(";")[0].strip().lower()
    if ct and ct not in ALLOWED_UPLOAD_CONTENT_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported Content-Type '{ct}'.",
        )

    head = data[:8]
    if ext == ".pdf":
        if not data.startswith(b"%PDF"):
            raise HTTPException(status_code=415, detail="File is not a valid PDF.")
        return "application/pdf"
    if ext == ".docx":
        if head[:2] != b"PK":
            raise HTTPException(status_code=415, detail="File is not a valid DOCX.")
        try:
            with zipfile.ZipFile(BytesIO(data)) as zf:
                names = set(zf.namelist())
            if "[Content_Types].xml" not in names or not any(
                n.startswith("word/") for n in names
            ):
                raise HTTPException(status_code=415, detail="File is not a valid DOCX.")
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=415, detail="File is not a valid DOCX.") from exc
        return (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
    if ext in {".txt", ".csv"}:
        if b"\x00" in data[:8192]:
            raise HTTPException(status_code=415, detail="Text upload contains binary data.")
        # Reject HTML disguised as text (script injection via upload)
        sample = data[:4096].decode("utf-8", errors="ignore").lower()
        if _SCRIPT_RE.search(sample) or "<html" in sample:
            raise HTTPException(
                status_code=415,
                detail="Text upload must not contain HTML/script content.",
            )
        return "text/csv" if ext == ".csv" else "text/plain"
    raise HTTPException(status_code=415, detail="Unsupported file type.")


async def read_upload_limited(file: UploadFile, *, max_bytes: int) -> bytes:
    """Read upload with a hard byte cap (reject before buffering unbounded data)."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(64 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"File too large. Limit is {max_bytes // (1024 * 1024)} MB.",
            )
        chunks.append(chunk)
    return b"".join(chunks)


# --- FastAPI Path / Query annotations ---------------------------------------

ResourceIdPath = Annotated[
    str,
    Path(
        ...,
        min_length=36,
        max_length=36,
        pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$",
        description="UUID resource id",
    ),
]

NodeIdPath = Annotated[
    str,
    Path(..., min_length=1, max_length=MAX_NODE_ID_CHARS, pattern=r"^[A-Za-z0-9._:-]+$"),
]

DashboardRangeQuery = Annotated[
    str,
    Query(default="30d", min_length=2, max_length=16),
]


# --- Pydantic helpers -------------------------------------------------------

def _as_uuid(v: str) -> str:
    return require_uuid(v, field="id")


def _as_opt_uuid(v: Optional[str]) -> Optional[str]:
    if v is None or v == "":
        return None
    return require_uuid(v, field="id")


def _as_query(v: str) -> str:
    text = sanitize_user_text(v, max_chars=MAX_QUERY_CHARS)
    if not text:
        raise ValueError("query must not be empty")
    return text


def _as_full_name(v: str) -> str:
    text = sanitize_user_text(v, max_chars=MAX_FULL_NAME_CHARS)
    if len(text) < 1:
        raise ValueError("full_name is required")
    return text


def _as_email(v: str) -> str:
    return require_email(v)


def _as_password(v: str) -> str:
    if v is None or not isinstance(v, str):
        raise ValueError("password is required")
    if "\x00" in v:
        raise ValueError("Invalid password")
    if len(v) < 1 or len(v) > MAX_PASSWORD_CHARS:
        raise ValueError(f"password must be 1–{MAX_PASSWORD_CHARS} characters")
    return v


UuidStr = Annotated[str, AfterValidator(_as_uuid)]
OptionalUuidStr = Annotated[Optional[str], AfterValidator(_as_opt_uuid)]
QueryText = Annotated[str, AfterValidator(_as_query)]
FullNameStr = Annotated[str, AfterValidator(_as_full_name)]
EmailStrStrict = Annotated[str, AfterValidator(_as_email)]
PasswordStr = Annotated[str, AfterValidator(_as_password)]
