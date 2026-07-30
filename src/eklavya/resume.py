"""Résumé / LinkedIn-PDF intake — extract untrusted text, store it per-user.

The learner can hand Ekalavya a real résumé (or their LinkedIn profile, exported via
LinkedIn's "Save to PDF") so onboarding grounds the background + competency map in their
actual experience instead of self-report alone.

Everything here treats the PDF as UNTRUSTED input: we only ever pull *text* out of it
(never execute anything), cap the length so a giant/adversarial PDF can't flood the
model's context, and strip control characters. Bad/encrypted/empty PDFs return a clear
error string rather than raising, so callers (the web endpoint, the CLI, the agent tool)
stay simple and offline-safe. The extracted text is stored in the *current* user's
workspace, so multi-user isolation comes for free via ``config.paths()``.
"""

from __future__ import annotations

import io
import re

from . import config
from .config import ensure_home

# Cap the stored/extracted text so a huge (or hostile) résumé can't blow the context
# window. ~20k chars comfortably covers a long multi-page CV.
_MAX_CHARS = 20_000

# Drop ASCII control chars except tab/newline/carriage-return — PDFs can carry stray
# control bytes we don't want reaching the model or the DOM.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

_RESUME_FILENAME = "resume.txt"


def _resume_path():
    return config.paths().workspace / _RESUME_FILENAME


def extract_pdf_text(data: bytes) -> str:
    """Extract text from a PDF's bytes as untrusted plain text.

    Returns the extracted text (capped at ~20k chars, control chars stripped). On any
    problem — not a PDF, encrypted, corrupt, or empty — returns a short human-readable
    error string beginning with "error:" and NEVER raises.
    """
    if not data:
        return "error: empty file (no PDF data)."
    try:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
    except ImportError:  # pragma: no cover - web extra always provides pypdf
        return "error: PDF support is not installed."

    try:
        reader = PdfReader(io.BytesIO(data))
    except (PdfReadError, OSError, ValueError, Exception):  # noqa: BLE001 - untrusted input
        return "error: could not read this file as a PDF (it may be corrupt or not a PDF)."

    if getattr(reader, "is_encrypted", False):
        # Try an empty-password decrypt (common for "protected" but not passworded PDFs).
        try:
            if reader.decrypt("") == 0:
                return "error: this PDF is password-protected; please upload an unlocked copy."
        except Exception:  # noqa: BLE001
            return "error: this PDF is password-protected; please upload an unlocked copy."

    parts: list[str] = []
    try:
        for page in reader.pages:
            try:
                parts.append(page.extract_text() or "")
            except Exception:  # noqa: BLE001 - skip a bad page, keep the rest
                continue
    except Exception:  # noqa: BLE001 - pages iterator itself blew up
        return "error: could not extract text from this PDF."

    text = _CONTROL.sub("", "\n".join(parts)).strip()
    if not text:
        return ("error: no text found in this PDF — it may be a scanned image. "
                "Please upload a text-based résumé.")
    return text[:_MAX_CHARS]


def save_resume(text: str) -> str:
    """Store the extracted résumé text in the current user's workspace. Returns the path."""
    ensure_home()
    path = _resume_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text((text or "")[:_MAX_CHARS], encoding="utf-8")
    return str(path)


def read_resume() -> str:
    """Return the learner's uploaded résumé / LinkedIn text, or a note if none exists yet.

    Onboarding calls this early: if the learner uploaded a résumé or LinkedIn PDF, ground
    the background and competency map in their REAL experience — and probe depth on the
    things they list rather than taking them at face value.
    """
    path = _resume_path()
    if path.exists():
        return path.read_text(encoding="utf-8")
    return "(no résumé uploaded — the learner has not provided a résumé or LinkedIn PDF)"
