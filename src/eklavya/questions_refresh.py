"""Best-effort refresh of the question bank from live web search.

Powers `eklavya refresh-questions`. It runs a few targeted searches for real, current
interview questions, pulls plausible question-shaped lines out of the results, and adds
the good ones via `tools.add_question` (deduped on the question text).

Honesty & safety:
  • Offline-safe — with no TAVILY/SERPER key, `_web_search_raw` returns [] and we report
    that nothing changed (never a crash).
  • Company is tagged ONLY when the caller passed one AND the result URL/title actually
    mentions that company — otherwise the question is stored with no company (the honest
    default). We never fabricate an attribution.
"""

from __future__ import annotations

import re

from . import tools

# A line looks like an interview question if it's a sensible length and reads as a prompt:
# ends in a question mark, or opens with a design/implement/explain-style verb.
_VERB = re.compile(
    r"^(design|implement|write|build|explain|describe|what|how|why|when|given|find|"
    r"reverse|merge|compute|calculate|tell me|walk me)\b",
    re.IGNORECASE,
)
_STRIP = re.compile(r"^\s*(?:[-*•\d.)\]\[(]+\s*|q[:.\d]*\s*)", re.IGNORECASE)


def _clean(line: str) -> str:
    line = _STRIP.sub("", line.strip())
    return re.sub(r"\s+", " ", line).strip(" -–—:")


def _looks_like_question(line: str) -> bool:
    if not (15 <= len(line) <= 240):
        return False
    if line.endswith("?"):
        return True
    return bool(_VERB.match(line))


def _extract(text: str) -> list[str]:
    """Pull candidate question lines out of a title/snippet blob."""
    out = []
    # Split on newlines and sentence-ish boundaries so multiple questions in one snippet
    # each get a shot.
    for chunk in re.split(r"[\n\r]+|(?<=\?)\s+|(?<=\.)\s+(?=[A-Z])", text):
        cand = _clean(chunk)
        if _looks_like_question(cand):
            out.append(cand)
    return out


def refresh(company: str = "", role: str = "", topic: str = "", per_query: int = 6) -> dict:
    """Search for fresh questions for a target and add the good ones. Returns a summary
    dict: {searched, found, added, skipped, samples}. `searched` is False when web search
    is unavailable (no key), so the caller can message the user cleanly.
    """
    company, role, topic = company.strip(), role.strip(), topic.strip()
    focus = " ".join(t for t in (company, role, topic) if t)
    queries = [
        f"{focus} interview questions".strip(),
        f"{focus} technical interview questions asked".strip(),
    ]
    if not focus:
        queries = ["common software engineering interview questions",
                   "AI engineer interview questions"]

    found, added, skipped, samples = 0, 0, 0, []
    searched = False
    seen: set[str] = set()

    for q in queries:
        results = tools._web_search_raw(q, max_results=per_query)
        if not results:
            continue
        searched = True
        for r in results:
            url_title = f"{r.get('url', '')} {r.get('title', '')}".lower()
            # Only keep the company tag when the source actually mentions it — honest attribution.
            tag_company = company if (company and company.lower() in url_title) else ""
            source = r.get("url", "") or "web_search"
            for cand in _extract(f"{r.get('title', '')}\n{r.get('content', '')}"):
                key = cand.lower()
                if key in seen:
                    continue
                seen.add(key)
                found += 1
                res = tools.add_question(
                    cand, topic=topic, role=role, company=tag_company, source=source
                )
                if res.startswith("added"):
                    added += 1
                    if len(samples) < 8:
                        samples.append(cand)
                else:
                    skipped += 1

    return {"searched": searched, "found": found, "added": added,
            "skipped": skipped, "samples": samples}
