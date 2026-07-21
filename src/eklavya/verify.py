"""Self-check: an LLM-as-judge reviews the tutor's teaching for technical errors
the learner can't catch.

v3 design (doc-grounding + context-aware, single judge — no voting):
  - deterministic first: code is already verified by the sandbox (see tools.py);
  - the judge is a DIFFERENT model than the tutor (GLM vs MiniMax), cutting the
    self-preference bias judges are known for;
  - CONTEXT-AWARE: the judge sees what the learner asked, so it can tell a tutor
    *asserting* a fact from the tutor asking a question or deliberately showing a
    bug — killing false alarms like flagging "list.append() returns None";
  - DOC-GROUNDED: when the reply makes a library/API claim, we pull the real docs
    via Context7 (MCP) and tell the judge to check against SOURCE, not its memory.
    Best-effort and fail-open: no docs → judge only clear, well-known facts;
  - biased hard toward PRECISION — only surface CLEAR, OBJECTIVE errors; a tutor
    that nags on false alarms is worse than one that misses a rare subtlety;
  - fail-open: any judge/tool error or timeout returns "no issues", never blocks;
  - only runs on substantive replies (code or long technical prose), to save cost.

The result is a transparent "Self-check" note appended to the reply, so the
learner sees the correction and learns that even the tutor verifies itself.
"""

from __future__ import annotations

import json
import os
import re

_JUDGE_PROMPT = """You are a meticulous technical fact-checker reviewing a CODING \
TUTOR's message to a learner who CANNOT catch mistakes themselves — so you must, \
but WITHOUT crying wolf.

CONVERSATION CONTEXT (what the learner asked / the situation):
\"\"\"
{context}
\"\"\"

TUTOR MESSAGE (what you are checking):
\"\"\"
{message}
\"\"\"

AUTHORITATIVE DOCUMENTATION (retrieved for any library/API mentioned — trust this \
over your own memory; may be empty):
\"\"\"
{docs}
\"\"\"

Flag ONLY statements the tutor ASSERTS AS TRUE that are objectively, checkably \
wrong: false claims about what code does or prints, wrong output, wrong time/space \
complexity, wrong library/API/version behaviour, incorrect definitions, or a claim \
that contradicts the CONTEXT (e.g. says a file was saved when the context shows it \
failed) or a plainly false real-world fact (e.g. a company's actual interview style).

Do NOT flag — these are NOT issues:
  - questions the tutor asks the learner;
  - code or claims the tutor deliberately presents as a BUG, a wrong example, or \
"what NOT to do";
  - anything correct. Before flagging, state the correct fact to yourself; if it \
matches what the tutor said, it is NOT an issue. (E.g. "list.append() returns None" \
is TRUE. "append is amortized O(1) but insert(0,x) is O(n)" is TRUE. Never flag these.)
  - style, phrasing, pedagogy, opinion, or anything debatable.

A statement is an ISSUE only if it is clearly false AND your correction MATERIALLY \
DIFFERS from what the tutor said. When unsure, return "ok". Precision matters far \
more than recall.

Reply with ONLY a JSON object and nothing else, either:
{{"verdict": "ok", "issues": []}}
or
{{"verdict": "issues", "issues": [{{"claim": "<the exact wrong statement>", "correction": "<the correct fact in one sentence>"}}]}}"""


# Library/framework names we'll ground against real docs. Kept to well-known
# third-party names so we never waste a resolve call on a local module or stdlib.
_KNOWN_LIBS = {
    "numpy", "pandas", "polars", "torch", "pytorch", "tensorflow", "keras", "jax",
    "sklearn", "scikit-learn", "transformers", "langchain", "langgraph", "llama-index",
    "fastapi", "flask", "django", "pydantic", "requests", "httpx", "sqlalchemy",
    "matplotlib", "seaborn", "plotly", "scipy", "statsmodels", "networkx",
    "react", "next.js", "nextjs", "vue", "svelte", "tailwind", "typescript",
    "express", "prisma", "spring", "rails",
}


def enabled() -> bool:
    return os.environ.get("EKLAVYA_VERIFY", "1").lower() not in ("0", "false", "no", "off", "")


def worth_checking(reply: str) -> bool:
    """Only spend a judge call on substantive replies (code, or long technical prose)."""
    return "```" in reply or len(reply) >= 240


def parse_verdict(raw: str) -> dict:
    """Robustly pull the JSON verdict out of the judge's reply."""
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return {"verdict": "ok", "issues": []}
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return {"verdict": "ok", "issues": []}


def _judge_provider_key():
    """Prefer a provider DIFFERENT from the tutor's default, to reduce self-bias."""
    from . import config
    from .providers import configured_providers

    configured = configured_providers()
    others = [p for p in configured if p.key != config.DEFAULT_PROVIDER]
    chosen = (others or configured)
    return chosen[0].key if chosen else None


def candidate_library(reply: str) -> str | None:
    """A groundable library name mentioned in the reply, or None. Prefers explicit
    imports, then a known-library mention. Only returns well-known third-party names."""
    for name in re.findall(r"(?:^|\n)\s*(?:import|from)\s+([A-Za-z_][\w.]*)", reply):
        base = name.split(".")[0].lower()
        if base in _KNOWN_LIBS:
            return base
    low = reply.lower()
    for lib in _KNOWN_LIBS:
        if re.search(rf"(?<![\w.]){re.escape(lib)}(?![\w])", low):
            return lib
    return None


def _first_library_id(resolve_output: str) -> str | None:
    """Pull the first Context7-style '/org/project' id out of resolve-library-id output."""
    m = re.search(r"/[\w.\-]+/[\w.\-]+", resolve_output or "")
    return m.group(0) if m else None


def ground_docs(reply: str) -> str:
    """Best-effort: fetch real docs for a library the reply mentions, via Context7 MCP.
    Returns a docs excerpt or "" (no groundable claim, tools not warmed, or any error)."""
    lib = candidate_library(reply)
    if not lib:
        return ""
    try:
        from .mcp_client import cached_mcp_tools

        tools = {t.name: t for t in cached_mcp_tools()}
        resolve = tools.get("resolve-library-id")
        query = tools.get("query-docs") or tools.get("get-library-docs")
        if not (resolve and query):
            return ""
        topic = f"{lib} core API behaviour and correctness"
        cid = _first_library_id(str(resolve.invoke({"libraryName": lib, "query": topic})))
        if not cid:
            return ""
        docs = str(query.invoke({"libraryId": cid, "query": topic}))
        return docs[:2500].strip()
    except Exception:
        return ""


def format_note(issues: list[dict]) -> str:
    lines = "\n".join(
        f"- **{str(i.get('claim', '')).strip()[:160]}** — {str(i.get('correction', '')).strip()}"
        for i in issues[:3]
    )
    return (
        "\n\n> ⚠️ **Self-check** — a second model reviewed the above and flagged a "
        "point or two that may be off. Please verify:\n" + lines
    )


def selfcheck(reply: str, context: str = "") -> str | None:
    """Return a self-check note if the judge finds clear technical errors, else None.

    `context` is the learner's message / situation this reply answers — it lets the
    judge distinguish an assertion from a question or a deliberate bug. Never raises
    (fail-open): any judge or tool error just returns None.
    """
    if not enabled() or not worth_checking(reply):
        return None
    provider_key = _judge_provider_key()
    if provider_key is None:
        return None
    docs = ground_docs(reply)
    prompt = _JUDGE_PROMPT.format(
        context=(context or "").strip()[:1500] or "(no prior context available)",
        message=reply,
        docs=docs or "(no documentation retrieved)",
    )
    try:
        from .providers import build_chat_model

        model = build_chat_model(provider_key, max_tokens=700)
        raw = model.invoke(prompt).text
    except Exception:
        return None
    verdict = parse_verdict(raw)
    issues = verdict.get("issues") or []
    if verdict.get("verdict") != "issues" or not issues:
        return None
    return format_note(issues)
