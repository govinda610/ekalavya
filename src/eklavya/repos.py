"""Repo-awareness: learn from the learner's real code so practice fits their work.

Read-only and permissioned — the caller (CLI) asks before we read anything, and
we only look at dependency files and top-level imports. We map what we find to
pillars, so drills target the frameworks they actually use.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from .db import connect

# Map an imported module / dependency name to a pillar.
PILLAR_MAP = {
    "langgraph": "LangChain / LangGraph",
    "langchain": "LangChain / LangGraph",
    "deepagents": "LangChain / LangGraph",
    "fastapi": "FastAPI / backend",
    "starlette": "FastAPI / backend",
    "uvicorn": "FastAPI / backend",
    "flask": "FastAPI / backend",
    "django": "FastAPI / backend",
    "pandas": "pandas / numpy / viz",
    "numpy": "pandas / numpy / viz",
    "matplotlib": "pandas / numpy / viz",
    "polars": "pandas / numpy / viz",
    "seaborn": "pandas / numpy / viz",
    "torch": "ML / deep learning",
    "transformers": "ML / deep learning",
    "vllm": "vLLM / serving",
    "sklearn": "ML / data science",
    "scikit-learn": "ML / data science",
    "sqlalchemy": "databases / SQL",
    "pytest": "testing",
}

_IMPORT = re.compile(r"^\s*(?:from|import)\s+([a-zA-Z0-9_]+)", re.MULTILINE)
_DEP_NAME = re.compile(r"^[A-Za-z0-9_.\-]+")


def _dep_names(text: str) -> set[str]:
    names = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = _DEP_NAME.match(line)
        if m:
            names.add(m.group(0).lower())
    return names


def detect(path: str | Path) -> dict:
    """Detect stacks under `path`. Reads requirements/pyproject + sampled imports."""
    root = Path(path)
    modules: set[str] = set()

    req = root / "requirements.txt"
    if req.exists():
        modules |= _dep_names(req.read_text(errors="ignore"))

    pp = root / "pyproject.toml"
    if pp.exists():
        try:
            data = tomllib.loads(pp.read_text(errors="ignore"))
            for dep in data.get("project", {}).get("dependencies", []):
                m = _DEP_NAME.match(dep)
                if m:
                    modules.add(m.group(0).lower())
        except (tomllib.TOMLDecodeError, OSError):
            pass

    for py in list(root.rglob("*.py"))[:300]:  # sample, don't read everything
        try:
            modules |= {m.lower() for m in _IMPORT.findall(py.read_text(errors="ignore"))}
        except OSError:
            continue

    stacks = sorted(m for m in modules if m in PILLAR_MAP)
    pillars = sorted({PILLAR_MAP[m] for m in stacks})
    return {"stacks": stacks, "pillars": pillars}


def grant(path: str | Path, stacks: str = "", focus: str = "") -> None:
    """Record an allow-listed repo and what we found in it."""
    conn = connect()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO repos(path, stacks, focus) VALUES(?, ?, ?)",
            (str(path), stacks, focus),
        )
        conn.commit()
    finally:
        conn.close()
