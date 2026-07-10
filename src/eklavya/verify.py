"""Self-check: an LLM-as-judge reviews the tutor's teaching for technical errors
the learner can't catch.

Design (grounded in the 2026 hallucination-detection literature — LLM-as-judge +
chain-of-verification, cascade, precision-biased):
  - deterministic first: code is already verified by the sandbox (see tools.py);
  - the judge is a DIFFERENT model than the tutor (we have GLM + MiniMax), which
    cuts the self-preference bias judges are known for;
  - a clear categorical verdict (ok / issues), not a vague score;
  - biased toward PRECISION — a tutor that nags on false alarms is worse than one
    that misses a rare subtlety, so we only surface clear, objective errors;
  - fail-open: any judge error/timeout returns "no issues" and never blocks;
  - only runs on substantive replies (code or long technical prose), to save cost.

The result is a transparent "Self-check" note appended to the reply, so the
learner sees the correction and learns that even the tutor verifies itself.
"""

from __future__ import annotations

import json
import os
import re

_JUDGE_PROMPT = """You are a meticulous technical fact-checker reviewing a CODING \
TUTOR's message to a learner who CANNOT catch mistakes themselves — so you must.

Find only CLEAR, OBJECTIVE technical errors: false claims about what code does or \
prints, wrong output, wrong time/space complexity, wrong language/library/API \
behaviour, or incorrect definitions. IGNORE style, opinion, pedagogy, the tutor's \
questions, and anything debatable. Do NOT invent problems — if it is correct, or \
merely a matter of taste, return "ok". Precision matters far more than recall.

TUTOR MESSAGE:
\"\"\"
{message}
\"\"\"

Reply with ONLY a JSON object and nothing else, either:
{{"verdict": "ok", "issues": []}}
or
{{"verdict": "issues", "issues": [{{"claim": "<the exact wrong statement>", "correction": "<the correct fact in one sentence>"}}]}}"""


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


def format_note(issues: list[dict]) -> str:
    lines = "\n".join(
        f"- **{str(i.get('claim', '')).strip()[:160]}** — {str(i.get('correction', '')).strip()}"
        for i in issues[:3]
    )
    return (
        "\n\n> ⚠️ **Self-check** — a second model reviewed the above and flagged a "
        "point or two that may be off. Please verify:\n" + lines
    )


def selfcheck(reply: str) -> str | None:
    """Return a self-check note if the judge finds clear technical errors, else None.

    Never raises — a failed judge call just returns None (fail-open).
    """
    if not enabled() or not worth_checking(reply):
        return None
    provider_key = _judge_provider_key()
    if provider_key is None:
        return None
    try:
        from .providers import build_chat_model

        model = build_chat_model(provider_key, max_tokens=600)
        raw = model.invoke(_JUDGE_PROMPT.format(message=reply)).text
    except Exception:
        return None
    verdict = parse_verdict(raw)
    issues = verdict.get("issues") or []
    if verdict.get("verdict") != "issues" or not issues:
        return None
    return format_note(issues)
