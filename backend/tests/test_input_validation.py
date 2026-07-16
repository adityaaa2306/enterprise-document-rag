"""Strict input validation / upload sanitization at HTTP boundaries."""
from __future__ import annotations

import io
import uuid
import zipfile

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from src.api.input_validation import (
    require_dashboard_range,
    require_routing_mode,
    require_uuid,
    safe_filename,
    sanitize_user_text,
    validate_upload_bytes,
)
from src.api.schemas import ChatRequest, RagQueryRequest, UserLogin, UserRegister


def test_require_uuid_accepts_canonical():
    uid = str(uuid.uuid4())
    assert require_uuid(uid) == uid


def test_require_uuid_rejects_injection():
    with pytest.raises(ValueError):
        require_uuid("'; OR 1=1 --")
    with pytest.raises(ValueError):
        require_uuid("../../etc/passwd")
    with pytest.raises(ValueError):
        require_uuid("abc; rm -rf /")


def test_sanitize_user_text_strips_controls_and_scripts():
    assert sanitize_user_text("hello\x00world") == "helloworld"
    with pytest.raises(ValueError):
        sanitize_user_text("<script>alert(1)</script>")
    with pytest.raises(ValueError):
        sanitize_user_text("x" * 9000)


def test_rag_query_schema_rejects_bad_ids_and_empty_query():
    good = str(uuid.uuid4())
    RagQueryRequest(document_id=good, query="What is the summary?")
    with pytest.raises(ValidationError):
        RagQueryRequest(document_id="not-a-uuid", query="hi")
    with pytest.raises(ValidationError):
        RagQueryRequest(document_id=good, query="")
    with pytest.raises(ValidationError):
        RagQueryRequest(document_id=good, query="<script>x</script>")
    with pytest.raises(ValidationError):
        ChatRequest(document_id="'; DROP TABLE users; --", query="hi")
    # Null bytes are stripped; remaining empty after controls-only → reject
    with pytest.raises(ValidationError):
        ChatRequest(document_id=good, query="\x00\x00")


def test_auth_schemas_reject_invalid_email_and_name():
    with pytest.raises(ValidationError):
        UserRegister(email="not-an-email", password="Password1", full_name="Ada")
    with pytest.raises(ValidationError):
        UserLogin(email="x", password="Password1")
    with pytest.raises(ValidationError):
        UserRegister(
            email="a@b.co",
            password="Password1",
            full_name="<script>x</script>",
        )


def test_routing_mode_and_dashboard_range():
    assert require_routing_mode("fastest") == "fastest"
    with pytest.raises(ValueError):
        require_routing_mode("'; DROP TABLE; --")
    with pytest.raises(ValueError):
        require_routing_mode("../../../etc")
    assert require_dashboard_range("7d") == "7d"
    with pytest.raises(ValueError):
        require_dashboard_range("forever")


def test_safe_filename_strips_path_and_shell_chars():
    assert ".." not in safe_filename("../../evil.pdf")
    assert "/" not in safe_filename("a/b/c.pdf")
    assert ";" not in safe_filename("x;rm.pdf")


def _minimal_pdf() -> bytes:
    return b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def _minimal_docx() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", "<w:document/>")
    return buf.getvalue()


def test_validate_upload_pdf_and_docx_ok():
    assert validate_upload_bytes("report.pdf", "application/pdf", _minimal_pdf()) == (
        "application/pdf"
    )
    ct = validate_upload_bytes(
        "doc.docx",
        "application/octet-stream",
        _minimal_docx(),
    )
    assert "wordprocessingml" in ct


def test_validate_upload_rejects_polyglot_and_exe():
    with pytest.raises(HTTPException) as exe:
        validate_upload_bytes("x.exe", "application/octet-stream", b"MZ\x90\x00")
    assert exe.value.status_code == 415
    with pytest.raises(HTTPException) as exe2:
        validate_upload_bytes("fake.pdf", "application/pdf", b"not a pdf")
    assert exe2.value.status_code == 415
    with pytest.raises(HTTPException) as exe3:
        validate_upload_bytes(
            "evil.txt",
            "text/plain",
            b"<html><script>alert(1)</script></html>",
        )
    assert exe3.value.status_code == 415
