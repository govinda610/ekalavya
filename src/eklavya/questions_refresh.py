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
import threading
from datetime import datetime, timedelta, timezone

from . import config, tools

# --- automatic background refresh at session start -------------------------
#
# `maybe_autorefresh()` is called every time a practice/mock/take-home session starts
# (CLI, TUI, and the web app). It NEVER blocks the caller and NEVER raises: it does a
# cheap throttle + offline check on the calling thread, then hands the actual searching
# to a daemon thread so the learner's first response is never delayed.

# How long to wait between automatic refreshes for a given user (their own throttle
# stamp lives in their own db, so users refresh independently). Kept modest so the bank
# bends toward the learner's targets over time without hammering the search provider.
REFRESH_INTERVAL_HOURS = 24

# meta key holding the last successful-start-of-refresh timestamp (per user db).
_REFRESHED_AT_KEY = "questions_refreshed_at"

# How many distinct (company × role × level) targets to pull per refresh, on top of the
# general screening canon the seed already provides.
_MAX_TARGETS = 3

# Guard so repeated session starts (or two sessions racing) don't pile up threads for the
# same user db. Keyed by resolved db path; the throttle stamp is the durable guard, this
# only prevents a burst within one process.
_inflight_lock = threading.Lock()
_inflight: set[str] = set()

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


# --- target derivation ------------------------------------------------------

# Seniority words we recognise in the learner's goals/profile so refreshed questions can
# be honestly LEVEL-tagged (encoded into the role tag, e.g. "AI engineer (senior)").
_LEVELS = re.compile(
    r"\b(intern|junior|jr|entry[- ]?level|new[- ]?grad|associate|mid[- ]?level|"
    r"senior|sr|staff|principal|lead|distinguished|l[3-8]|e[3-8])\b",
    re.IGNORECASE,
)

# Role phrases we care about — matched inside free-form goal/profile text.
_ROLES = re.compile(
    r"\b(research engineer|research scientist|ml engineer|machine learning engineer|"
    r"ai engineer|ai scientist|data scientist|software engineer|swe|quant|"
    r"quantitative researcher|mle|applied scientist)\b",
    re.IGNORECASE,
)

# A curated set of target employers/orgs the learners in this product commonly aim at.
# We only match these as whole words so we don't mis-tag arbitrary capitalised nouns; the
# refresh itself still only tags `company` when the SOURCE attributes it (see `refresh`).
_COMPANIES = re.compile(
    r"\b(anthropic|deepmind|openai|google|deepseek|meta|microsoft|nvidia|apple|amazon|"
    r"netflix|jane street|two sigma|citadel|hudson river|hrt|de shaw|jump trading|"
    r"gartner|eli lilly|citigroup|databricks|scale ai|cohere|mistral|hugging ?face|xai)\b",
    re.IGNORECASE,
)


def _target_sources() -> tuple[str, list[str]]:
    """Gather the learner's stated ambitions as text: (profile_markdown, active_goal_texts).

    Best-effort and offline — reads the current user's profile.md + goals table. Any
    failure yields empties so the caller falls back to a generic pull.
    """
    profile = ""
    try:
        profile = tools.read_profile()
    except Exception:
        profile = ""
    goals: list[str] = []
    try:
        from .db import connect

        conn = connect()
        try:
            goals = [r["text"] for r in conn.execute(
                "SELECT text FROM goals WHERE status = 'active'"
            ).fetchall()]
        finally:
            conn.close()
    except Exception:
        goals = []
    return profile, goals


def _weak_topics(limit: int = 3) -> list[str]:
    """The learner's weakest pillars (lowest ratings) — best-effort, offline."""
    try:
        from .db import connect

        conn = connect()
        try:
            rows = conn.execute(
                "SELECT p.name AS name FROM ratings r JOIN pillars p ON p.id = r.pillar_id "
                "ORDER BY r.rating ASC LIMIT ?", (limit,)
            ).fetchall()
        finally:
            conn.close()
        # de-dup while preserving weakest-first order
        seen, out = set(), []
        for r in rows:
            n = (r["name"] or "").strip()
            if n and n.lower() not in seen:
                seen.add(n.lower())
                out.append(n)
        return out
    except Exception:
        return []


def derive_targets() -> list[dict]:
    """Best-effort list of {company, role, level, topic} targets from the learner's
    stated ambitions (goals + profile) and their weakest topics.

    Each dict drives one targeted `web_search`. The list is small (≤ _MAX_TARGETS) and
    always non-empty: when nothing specific is found it falls back to a single generic
    "AI engineer interview questions" pull so the bank still grows toward the field.
    LEVEL is encoded into the role tag (honest, source-independent) e.g. "ai engineer
    (senior)"; `company` is only a hint here — `refresh` tags it only if the source
    truly attributes it.
    """
    profile, goals = _target_sources()
    weak = _weak_topics()

    companies: list[str] = []
    roles: list[str] = []
    level = ""
    # Scan goals first (most explicit), then the profile, for companies / roles / a level.
    for text in [*goals, profile]:
        if not text:
            continue
        for m in _COMPANIES.findall(text):
            c = m.strip()
            if c and c.lower() not in {x.lower() for x in companies}:
                companies.append(c)
        for m in _ROLES.findall(text):
            r = m.strip()
            if r and r.lower() not in {x.lower() for x in roles}:
                roles.append(r)
        if not level:
            lv = _LEVELS.search(text)
            if lv:
                level = lv.group(0).strip()

    def _role_tag(base: str) -> str:
        base = base or "AI engineer"
        return f"{base} ({level})" if level else base

    targets: list[dict] = []
    # Pair each company with the primary role (level-encoded); these are the sharpest pulls.
    primary_role = roles[0] if roles else "AI engineer"
    for c in companies[:_MAX_TARGETS]:
        targets.append({"company": c, "role": _role_tag(primary_role),
                        "level": level, "topic": ""})
    # If we have roles but no companies, pull role×weak-topic instead.
    if not companies and roles:
        for t in (weak or [""])[:_MAX_TARGETS]:
            targets.append({"company": "", "role": _role_tag(primary_role),
                            "level": level, "topic": t})
    # Top up remaining slots with the primary role × weak topics (adds targeted questions
    # for their gaps without ever dropping the general canon already in the bank).
    for t in weak:
        if len(targets) >= _MAX_TARGETS:
            break
        targets.append({"company": "", "role": _role_tag(primary_role),
                        "level": level, "topic": t})

    if not targets:
        # No stated ambitions yet — a sensible general pull for the broad field.
        targets.append({"company": "", "role": _role_tag(primary_role),
                        "level": level, "topic": ""})
    return targets[:_MAX_TARGETS]


# --- the throttled, background, offline-safe entry point ---------------------


def _throttled(now: datetime | None = None) -> bool:
    """True if a refresh happened within REFRESH_INTERVAL_HOURS (→ skip this one)."""
    from .db import connect
    from . import progress

    now = now or datetime.now(timezone.utc)
    conn = connect()
    try:
        stamp = progress._get(conn, _REFRESHED_AT_KEY)
    finally:
        conn.close()
    if not stamp:
        return False
    try:
        last = datetime.fromisoformat(stamp)
    except ValueError:
        return False
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return now - last < timedelta(hours=REFRESH_INTERVAL_HOURS)


def _stamp_refreshed(now: datetime | None = None) -> None:
    from .db import connect
    from . import progress

    now = now or datetime.now(timezone.utc)
    conn = connect()
    try:
        progress._set(conn, _REFRESHED_AT_KEY, now.isoformat(timespec="seconds"))
        conn.commit()
    finally:
        conn.close()


def _run_refresh_for_targets() -> None:
    """The body that runs on the background thread (already inside the caller's context).

    Refreshes each derived target, then stamps the timestamp. Swallows everything — a
    background helper must never surface an error to the learner's session. The `_inflight`
    guard (keyed by db path) is released here so the next eligible session can refresh.
    """
    try:
        for target in derive_targets():
            try:
                refresh(company=target.get("company", ""), role=target.get("role", ""),
                        topic=target.get("topic", ""))
            except Exception:
                continue  # one bad target must not sink the rest
        try:
            _stamp_refreshed()
        except Exception:
            pass
    finally:
        try:
            key = str(config.paths().db)
        except Exception:
            key = ""
        with _inflight_lock:
            _inflight.discard(key)


def maybe_autorefresh() -> bool:
    """Kick off a throttled, background, offline-safe question-bank refresh for the CURRENT
    user. Call at the start of every practice/mock/take-home session.

    Contract:
      • THROTTLED — no-op if this user refreshed within REFRESH_INTERVAL_HOURS.
      • OFFLINE-SAFE — no-op if no web-search key is configured.
      • NON-BLOCKING — the actual searching runs on a daemon thread; returns immediately.
      • NEVER RAISES — all failures are swallowed so a broken refresh can't break a session.
      • MULTI-USER SAFE — the daemon thread runs in a COPY of the caller's context, so it
        reads/writes the CURRENT user's db (throttle stamp + questions), not a global one.

    Returns True if a background refresh was spawned, False if it was skipped (throttled /
    offline / already in flight). The return value is for tests/telemetry — callers ignore it.
    """
    try:
        if not tools.has_web_search_key():
            return False  # offline — clean no-op
        if _throttled():
            return False  # refreshed recently — clean no-op

        # Per-user in-flight guard: don't spawn a second thread for the same db mid-window.
        try:
            key = str(config.paths().db)
        except Exception:
            key = ""
        with _inflight_lock:
            if key in _inflight:
                return False
            _inflight.add(key)

        # Copy the CURRENT context (which carries the per-user `_current_home` contextvar)
        # so the daemon thread writes to THIS user's db, not a global one. We run the copied
        # context's `.run` as the thread target — that binds the contextvar inside the thread.
        import contextvars

        ctx = contextvars.copy_context()
        thread = threading.Thread(
            target=ctx.run, args=(_run_refresh_for_targets,),
            name="eklavya-qbank-refresh", daemon=True,
        )
        thread.start()
        return True
    except Exception:
        # Absolutely never let a refresh failure escape into the session start path.
        try:
            with _inflight_lock:
                _inflight.discard(str(config.paths().db))
        except Exception:
            pass
        return False
