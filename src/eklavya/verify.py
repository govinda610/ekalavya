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

LEARNER PROFILE (the tutor legitimately has this file about the learner — treat it \
as GROUND TRUTH about who the learner is; may be empty):
\"\"\"
{profile}
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
  - ANY statement about the LEARNER themselves — their background, education, job, \
employer, skills, goals, history, or plan. The tutor can see the learner's PROFILE \
and progress data (above), which is authoritative and may exceed what you know. \
NEVER flag a claim about the learner as wrong or as "unverifiable"/"no profile available";
  - ANY reference to the CONVERSATION SO FAR that you cannot see — "your 2nd/3rd attempt", \
"as we discussed", "earlier you wrote", "you tried X before", what was covered last session. \
You are shown ONLY the latest turn; the tutor has the FULL thread + progress data, so its \
account of prior turns, attempt counts, and history is authoritative. NEVER contradict it, \
and never call something the "first attempt" or say the tutor is misremembering the session;
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


def learner_profile() -> str:
    """The learner's profile.md — given to the judge so it never flags the tutor's
    legitimate, profile-grounded statements about the learner as hallucinations."""
    try:
        from . import config

        return config.PROFILE_PATH.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return ""


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


_RUBRIC_JUDGE_PROMPT = """You are a STRICT, reference-bound grader for a {subject} answer. \
You do NOT decide truth from your own memory — you grade the learner's answer ONLY against \
the REFERENCE solution and the RUBRIC below. If the reference and the answer disagree, the \
reference wins.

QUESTION:
\"\"\"
{prompt}
\"\"\"

REFERENCE SOLUTION (the ground truth you grade against):
\"\"\"
{reference}
\"\"\"

AUTHORITATIVE DOCUMENTATION (retrieved for any library/method mentioned — trust this over \
your own memory; may be empty):
\"\"\"
{docs}
\"\"\"

LEARNER'S ANSWER (what you are grading):
\"\"\"
{answer}
\"\"\"

RUBRIC — score EACH criterion independently as pass (full points), partial (half), or fail \
(zero), judging ONLY against the reference + docs:
{rubric}

Rules:
- Grade against the REFERENCE, not your own opinion. A correct-but-different valid approach \
that the reference's criteria still cover earns the points; a confident restatement of the \
reference WITHOUT the required reasoning does NOT.
- Be strict and consistent. When a criterion is not clearly met, score it fail or partial.
- Reply with ONLY a JSON object and nothing else:
{{"criteria": [{{"id": "<criterion id>", "verdict": "pass|partial|fail", "note": "<one short reason>"}}, ...]}}"""


def _verdict_fraction(verdict: str) -> float:
    return {"pass": 1.0, "partial": 0.5, "fail": 0.0}.get((verdict or "").strip().lower(), 0.0)


def rubric_judge(prompt: str, answer: str, reference: str, rubric: list[dict],
                 subject: str = "general", context: str = "") -> dict:
    """The constrained LLM-judge for genuinely non-deterministic answers (proofs,
    interpretation, explanations) — plan §5.2. Reference-bound, rubric-driven, doc-grounded,
    on a provider DIFFERENT from the tutor, k=1 (single pass — locked decision; verdicts are
    logged for optional human audit). Returns a structured, auditable result:

        {"score": <weighted fraction ∈ [0,1]>, "criteria": [{id, weight, axis, verdict,
         fraction, note}], "model": <provider key>, "raw": <judge output>, "ok": <bool>}

    Each rubric criterion is {id, weight?, axis?, description}. The per-criterion verdicts
    (pass/partial/fail → 1/0.5/0) are weight-averaged into the score. Fail-open: any judge or
    tool error returns ok=False with score=None so the caller can fall back / withhold.
    """
    provider_key = _judge_provider_key()
    weights = [float(c.get("weight", 1) or 1) for c in rubric]
    total_w = sum(weights) or 1.0
    if provider_key is None or not rubric:
        return {"score": None, "criteria": [], "model": provider_key, "raw": "",
                "ok": False, "reason": "no judge provider" if provider_key is None else "empty rubric"}

    rubric_txt = "\n".join(
        f'- id="{c.get("id", f"c{i}")}" (weight {c.get("weight", 1)}): {c.get("description", "")}'
        for i, c in enumerate(rubric)
    )
    docs = ground_docs(answer + "\n" + reference)
    judge_prompt = _RUBRIC_JUDGE_PROMPT.format(
        subject=subject, prompt=(prompt or "").strip()[:1500],
        reference=(reference or "").strip()[:3000], docs=docs or "(no documentation retrieved)",
        answer=(answer or "").strip()[:3000], rubric=rubric_txt,
    )
    try:
        from .providers import build_chat_model

        model = build_chat_model(provider_key, max_tokens=900)
        raw = model.invoke(judge_prompt).text
    except Exception as e:
        return {"score": None, "criteria": [], "model": provider_key, "raw": "",
                "ok": False, "reason": f"judge error: {e}"}

    parsed = parse_verdict(raw)
    by_id = {str(c.get("id", "")): c for c in (parsed.get("criteria") or [])}
    out_criteria: list[dict] = []
    weighted = 0.0
    for i, c in enumerate(rubric):
        cid = str(c.get("id", f"c{i}"))
        w = float(c.get("weight", 1) or 1)
        j = by_id.get(cid, {})
        frac = _verdict_fraction(j.get("verdict", "fail"))
        weighted += w * frac
        out_criteria.append({
            "id": cid, "weight": w, "axis": c.get("axis"),
            "verdict": j.get("verdict", "fail"), "fraction": frac, "note": j.get("note", ""),
        })
    return {"score": round(weighted / total_w, 3), "criteria": out_criteria,
            "model": provider_key, "raw": raw, "ok": True}


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
        profile=learner_profile().strip()[:3000] or "(no learner profile on file)",
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
