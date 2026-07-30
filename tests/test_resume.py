"""Résumé / LinkedIn PDF intake: extraction, storage, agent tool, upload endpoint."""

import io
import os
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="eklavya-resume-")
os.environ["EKLAVYA_HOME"] = _TMP
os.environ["EKLAVYA_PROFILE"] = str(Path(_TMP) / "profile.md")

import pytest  # noqa: E402

from eklavya import resume  # noqa: E402
from eklavya.db import init_db  # noqa: E402


def _make_pdf(text: str) -> bytes:
    """Build a one-page PDF containing `text` using pypdf + reportlab-free drawing.

    pypdf can't author page content streams on its own, so we hand-write a minimal
    single-page PDF with a text-showing content stream. Kept tiny and standards-valid so
    pypdf's own extractor reads it back."""
    # A minimal but valid PDF with one page whose content stream draws `text`.
    esc = text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
    stream = f"BT /F1 24 Tf 72 700 Td ({esc}) Tj ET".encode("latin-1")
    objs = []
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    objs.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>")
    objs.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % i + body + b"\nendobj\n")
    xref_pos = out.tell()
    out.write(b"xref\n0 %d\n" % (len(objs) + 1))
    out.write(b"0000000000 65535 f \n")
    for off in offsets:
        out.write(b"%010d 00000 n \n" % off)
    out.write(b"trailer\n<< /Size %d /Root 1 0 R >>\n" % (len(objs) + 1))
    out.write(b"startxref\n%d\n%%%%EOF" % xref_pos)
    return out.getvalue()


@pytest.fixture(autouse=True)
def fresh():
    init_db()
    r = resume._resume_path()  # the real per-context path, whatever the env resolves to
    if r.exists():
        r.unlink()
    yield


def test_extract_pdf_text_reads_text():
    data = _make_pdf("Govind Mittal Senior Data Scientist")
    text = resume.extract_pdf_text(data)
    assert not text.startswith("error:")
    assert "Govind Mittal" in text
    assert "Senior Data Scientist" in text


def test_extract_empty_bytes():
    out = resume.extract_pdf_text(b"")
    assert out.startswith("error:")


def test_extract_non_pdf_bytes():
    out = resume.extract_pdf_text(b"this is definitely not a pdf, just plain text")
    assert out.startswith("error:")


def test_extract_caps_length():
    big = "SKILLS " * 10000  # ~70k chars pre-extraction
    data = _make_pdf(big)
    text = resume.extract_pdf_text(data)
    assert not text.startswith("error:")
    assert len(text) <= 20_000


def test_save_and_read_roundtrip():
    resume.save_resume("Experienced ML engineer, 5y Python.")
    assert "ML engineer" in resume.read_resume()


def test_read_resume_when_absent():
    out = resume.read_resume()
    assert "no résumé" in out.lower()


def test_read_resume_is_an_agent_tool():
    from eklavya.tools import AGENT_TOOLS

    assert resume.read_resume in AGENT_TOOLS


def test_upload_endpoint_stores_and_read_resume_returns_it():
    from starlette.testclient import TestClient

    from eklavya.webapp import create_app

    c = TestClient(create_app())
    data = _make_pdf("Uploaded resume of a quant researcher")
    r = c.post("/api/upload-resume",
               files={"file": ("cv.pdf", data, "application/pdf")})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["chars"] > 0
    assert "quant researcher" in resume.read_resume()


def test_upload_rejects_non_pdf_content_type():
    from starlette.testclient import TestClient

    from eklavya.webapp import create_app

    c = TestClient(create_app())
    r = c.post("/api/upload-resume",
               files={"file": ("notes.txt", b"hello", "text/plain")})
    assert r.status_code == 415
    assert r.json()["ok"] is False


def test_upload_rejects_oversized_file():
    from starlette.testclient import TestClient

    from eklavya.webapp import create_app

    c = TestClient(create_app())
    big = b"%PDF-1.4\n" + b"0" * (8 * 1024 * 1024 + 100)
    r = c.post("/api/upload-resume",
               files={"file": ("huge.pdf", big, "application/pdf")})
    assert r.status_code == 413
    assert r.json()["ok"] is False


def test_upload_rejects_unreadable_pdf():
    from starlette.testclient import TestClient

    from eklavya.webapp import create_app

    c = TestClient(create_app())
    r = c.post("/api/upload-resume",
               files={"file": ("bad.pdf", b"%PDF-1.4 not really a pdf", "application/pdf")})
    assert r.status_code == 422
    assert r.json()["ok"] is False
