"""Scan-and-import bridge: the file-based artifact drop-folder → the Scriptorium.

Anthropic-artifacts style. The tutor doesn't call a save tool — it simply WRITES a file
with its normal write_file/run_bash tools into::

    <workspace>/artifacts/<pillar-slug>/<name>.<ext>     (ext = html|svg|py|md|json|…)

After each agent turn (and on Library open) `import_new()` scans that folder and UPSERTs
every file into the artifacts table via the plain CRUD in ``artifacts`` — deriving the
title, the kind, and the pillar from the file, associating it with the current chat, and
deduping by the workspace-relative path (+ a content hash so an unchanged file is skipped
on re-scan). This keeps the existing DB-backed Library + Canvas working while making
persistence automatic.

Pure filesystem + DB; no LLM. Never deletes anything — it only inserts/updates rows.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from . import artifacts, config

# Extensions we import, mapped to the Canvas `kind` that renders them.
#   html → a self-contained page/widget · viz → an SVG/interactive visual ·
#   code → source · markdown → a written lesson.
_EXT_KIND = {
    ".html": "html", ".htm": "html",
    ".svg": "viz",
    ".md": "markdown", ".markdown": "markdown", ".txt": "markdown",
    ".py": "code", ".js": "code", ".ts": "code", ".sql": "code",
    ".json": "code", ".c": "code", ".cpp": "code", ".java": "code",
    ".go": "code", ".rs": "code", ".sh": "code",
}

_MAX_BYTES = 2_000_000  # skip anything larger than ~2MB (not a hand-authored artifact)


def _root() -> Path:
    """The artifacts drop-folder under the current user's workspace."""
    return config.paths().workspace / "artifacts"


def _title_from(content: str, kind: str, filename: str) -> str:
    """Best title: an HTML <title>/<h1>, a markdown first heading, else a prettified
    filename (dashes/underscores → spaces, title-cased)."""
    if kind in ("html", "viz"):
        m = re.search(r"<title[^>]*>(.*?)</title>", content, re.IGNORECASE | re.DOTALL)
        if m and m.group(1).strip():
            return m.group(1).strip()
        m = re.search(r"<h1[^>]*>(.*?)</h1>", content, re.IGNORECASE | re.DOTALL)
        if m:
            text = re.sub(r"<[^>]+>", "", m.group(1)).strip()
            if text:
                return text
    if kind == "markdown":
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("#"):
                heading = line.lstrip("#").strip()
                if heading:
                    return heading
            if line:  # first non-blank, non-heading line as a fallback
                break
    stem = Path(filename).stem.replace("-", " ").replace("_", " ").strip()
    return stem.title() if stem else "Untitled"


def _pillar_from(rel_to_root: str) -> str | None:
    """The pillar is the first sub-folder under artifacts/ (a slug → a readable label);
    `rel_to_root` is the file path RELATIVE TO the artifacts root. A file dropped directly
    in artifacts/ has no pillar (files under 'General' in the UI)."""
    parts = Path(rel_to_root).parts
    if len(parts) >= 2:  # <pillar-slug>/<name.ext>
        slug = parts[0].replace("-", " ").replace("_", " ").strip()
        return slug.title() if slug else None
    return None


def import_new() -> int:
    """Scan the drop-folder and upsert new/changed files into the Scriptorium.

    Returns the number of artifacts inserted or updated this pass (0 → nothing new, so the
    caller can skip signalling the frontend). Dedup by rel_path; an unchanged file (same
    content hash) is skipped. Safe to call every turn and on Library open."""
    root = _root()
    if not root.exists():
        return 0
    workspace = config.paths().workspace
    changed = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name.startswith("."):
            continue
        kind = _EXT_KIND.get(path.suffix.lower())
        if kind is None:
            continue
        try:
            if path.stat().st_size > _MAX_BYTES:
                continue
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        rel_path = str(path.relative_to(workspace))       # dedupe key (workspace-relative)
        pillar = _pillar_from(str(path.relative_to(root)))  # pillar = first folder under artifacts/
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        existing = artifacts.get_by_rel_path(rel_path)
        if existing is None:
            artifacts.create(
                _title_from(content, kind, path.name), kind, content,
                pillar=pillar, rel_path=rel_path, content_hash=digest,
            )
            changed += 1
        elif existing.get("content_hash") != digest:
            artifacts.update(
                existing["id"], title=_title_from(content, kind, path.name),
                kind=kind, content=content, pillar=pillar, content_hash=digest,
            )
            changed += 1
    return changed
