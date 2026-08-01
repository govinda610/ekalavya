"""Tier-1 effectiveness — a FROZEN, walled benchmark the tutor never teaches from.

Why this exists (docs/EFFECTIVENESS_MEASUREMENT.md §3). Every internal metric —
Elo, FSRS, the AI-gap — moves in response to attempts on items the tutor itself
chose, generated and graded. That makes the ruler the same hand that teaches
(threat 1b, circularity): if the item generator drifts easier or the grader
loosens, every number improves with zero real skill change. This module is the
independent instrument that keeps them honest: a held-out item bank the tutor
NEVER draws teaching drills from, administered periodically AI-off, objectively
scored, yielding a **stable ability score θ** on a common scale so the "am I
really improving?" question has a non-circular answer.

Scope of THIS v1 (deliberately small, pragmatic, extensible — NOT a full IRT engine):

* A tiny **starter frozen item bank** (`seed_items`) across a few core pillars,
  each item carrying an author-assigned difficulty b ∈ {1..5}. Idempotent.
* **Item selection** (`select_items`) — a rotating subset spread across difficulty
  and pillar, avoiding items seen in the most recent sittings, so the learner sees
  fresh items each time (defeats the test–retest / memorisation confound, §1a).
* **Objective scoring** — each response is a plain correct/incorrect (0/1); the
  agent grades against the item's stored answer/tests during the sitting.
* A **1PL / Rasch θ estimate** (`estimate_theta`) from the item difficulties and
  the correct/incorrect pattern — a few Newton (MLE) steps. See its docstring for
  the model, the fixed-difficulty assumption, and why that's the right v1.
* **`history()`** — θ per assessment over time, the primary effectiveness series.

θ lives on the same logit scale as item difficulty b (0 ≈ a mid-difficulty=3
item; higher = stronger). It is drift-proof *by construction*: because the item
difficulties are fixed and known, a rotating test still reads on one ruler.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from .db import connect

# Difficulty is authored on a 1..5 scale (LeetCode-style easy→hard); we map it to a
# logit b centred on 3 so θ (also a logit) reads naturally: b(3) = 0, b(1) = -1, b(5) = +1.
_DIFF_STEP = 0.5


def _b_of(difficulty: int) -> float:
    """Logit difficulty b for an authored 1..5 difficulty (centred, ½-logit per step)."""
    return (int(difficulty) - 3) * _DIFF_STEP


# --- the frozen starter item bank -----------------------------------------
#
# A small, self-contained bank across a few core pillars. These are FROZEN: the
# tutor's teaching loops never select from `benchmark_items`, only this module does.
# `answer` is the objective key the assessment agent grades against (never shown as a
# hint). Each tuple: (pillar, difficulty 1..5, prompt, answer, grader).
_STARTER_ITEMS: list[tuple[str, int, str, str, str]] = [
    # --- Python fundamentals ---
    ("Python", 1,
     "What does `len([1, 2, 3])` evaluate to?",
     "3", "output_match"),
    ("Python", 2,
     "Write a one-line expression that returns the squares of 0..4 as a list.",
     "[x*x for x in range(5)]  →  [0, 1, 4, 9, 16]", "output_match"),
    ("Python", 3,
     "What is printed?  `d = {}; d.setdefault('a', []).append(1); print(d)`",
     "{'a': [1]}", "output_match"),
    ("Python", 4,
     "A function mutates a default list argument `def f(x, acc=[])`. Explain the bug and the fix.",
     "The default list is created once and shared across calls, so it accumulates; "
     "fix: default to None and create a fresh list inside.", "rubric"),
    ("Python", 5,
     "Write a generator `pairs(it)` yielding consecutive overlapping pairs of an iterable "
     "((a,b),(b,c),...) without materialising the whole iterable.",
     "Use two references / itertools.tee or track the previous value; yield (prev, cur) "
     "as you iterate, holding at most one extra element.", "rubric"),
    # --- Algorithms / complexity ---
    ("Algorithms", 1,
     "What is the time complexity of looking up a key in a Python dict (average case)?",
     "O(1)", "output_match"),
    ("Algorithms", 2,
     "What is the worst-case time complexity of binary search on a sorted array of n items?",
     "O(log n)", "output_match"),
    ("Algorithms", 3,
     "Given an unsorted array, describe an O(n) approach to find whether any two numbers sum to a target.",
     "One pass with a hash set: for each x, check if target - x was already seen, else add x.", "rubric"),
    ("Algorithms", 4,
     "Why does quicksort degrade to O(n^2), and what standard tactic avoids it in practice?",
     "Worst case is a consistently bad pivot (e.g. already-sorted with first/last pivot); "
     "randomised or median-of-three pivot selection avoids it.", "rubric"),
    ("Algorithms", 5,
     "Explain how to detect a cycle in a singly linked list in O(1) extra space.",
     "Floyd's tortoise-and-hare: advance one pointer by 1 and another by 2; they meet iff "
     "there is a cycle.", "rubric"),
    # --- SQL ---
    ("SQL", 1,
     "Which SQL clause filters rows BEFORE aggregation: WHERE or HAVING?",
     "WHERE", "output_match"),
    ("SQL", 2,
     "Write a query counting rows per `status` in a table `orders`.",
     "SELECT status, COUNT(*) FROM orders GROUP BY status;", "rubric"),
    ("SQL", 3,
     "What does a LEFT JOIN return that an INNER JOIN does not?",
     "Rows from the left table with no match on the right (right-side columns NULL).", "rubric"),
    ("SQL", 4,
     "Explain why `SELECT col, COUNT(*) FROM t` without GROUP BY is usually an error.",
     "col is a non-aggregated column mixed with an aggregate; without GROUP BY there is no "
     "single row per group for col, so it's ambiguous / rejected by standard SQL.", "rubric"),
    ("SQL", 5,
     "Describe a window-function query to get each employee's salary rank within their department.",
     "SELECT ..., RANK() OVER (PARTITION BY dept ORDER BY salary DESC) FROM employees.", "rubric"),
    # --- Data structures ---
    ("Data Structures", 1,
     "Which data structure gives LIFO order: stack or queue?",
     "stack", "output_match"),
    ("Data Structures", 2,
     "What is the average lookup complexity of a hash table?",
     "O(1)", "output_match"),
    ("Data Structures", 3,
     "When would you choose a heap over a sorted list?",
     "When you repeatedly need the min/max (priority queue) with cheap insert; a heap gives "
     "O(log n) push/pop without keeping everything fully sorted.", "rubric"),
    ("Data Structures", 4,
     "Explain the difference between a hash map and a balanced BST for storing keys, and one "
     "case where the BST wins.",
     "Hash map: average O(1), unordered. BST: O(log n), ordered — wins when you need range "
     "queries or in-order traversal.", "rubric"),
    ("Data Structures", 5,
     "Describe how a trie stores strings and one advantage over a hash set of strings.",
     "A trie stores strings by shared character prefixes along tree edges; advantage: "
     "efficient prefix / autocomplete queries a hash set can't do.", "rubric"),
]


def seed_items(conn) -> int:
    """Idempotently insert the starter frozen item bank; return how many were inserted.

    Only inserts items not already present (matched on `prompt`), so it is safe to call
    on every launch from ``_migrate``. Never overwrites an existing item — the bank is
    frozen once seeded. Uses the passed-in connection (does not commit; the caller does).
    """
    inserted = 0
    for pillar, diff, prompt, answer, grader in _STARTER_ITEMS:
        exists = conn.execute(
            "SELECT 1 FROM benchmark_items WHERE prompt = ?", (prompt,)
        ).fetchone()
        if exists:
            continue
        conn.execute(
            "INSERT INTO benchmark_items(pillar, difficulty, prompt, answer, grader) "
            "VALUES(?, ?, ?, ?, ?)",
            (pillar, int(diff), prompt, answer, grader),
        )
        inserted += 1
    return inserted


# --- item selection --------------------------------------------------------

def _recent_item_ids(conn, sittings: int = 2) -> set[int]:
    """Item ids used in the most recent `sittings` completed assessments — to avoid repeats."""
    rows = conn.execute(
        "SELECT DISTINCT r.item_id FROM assessment_responses r "
        "WHERE r.assessment_id IN ("
        "  SELECT id FROM assessments ORDER BY started_at DESC LIMIT ?"
        ")",
        (sittings,),
    ).fetchall()
    return {r["item_id"] for r in rows}


def select_items(conn, n: int = 8, avoid_recent: int = 2) -> list[dict]:
    """Pick a rotating subset of ~`n` frozen items, spread across difficulty and pillar.

    Strategy (simple + defensible): prefer items NOT used in the last `avoid_recent`
    sittings, then round-robin across difficulty buckets 1..5 so every sitting samples
    the whole difficulty range (a fixed θ estimate needs a spread of b's, not all-easy
    or all-hard). Within a bucket, rotate across pillars and least-recently-used items.
    Falls back to allowing recent items if the fresh pool is too small (small bank).

    Returns a list of item dicts (id, pillar, difficulty, prompt, answer, grader), ordered
    easy→hard so the sitting ramps up.
    """
    recent = _recent_item_ids(conn, avoid_recent) if avoid_recent else set()
    all_items = [dict(r) for r in conn.execute(
        "SELECT id, pillar, difficulty, prompt, answer, grader FROM benchmark_items"
    ).fetchall()]
    if not all_items:
        return []

    # per-item usage count, so ties break toward the least-often-administered item
    used = {r["item_id"]: r["c"] for r in conn.execute(
        "SELECT item_id, COUNT(*) AS c FROM assessment_responses GROUP BY item_id"
    ).fetchall()}

    def pool(exclude_recent: bool) -> dict[int, list[dict]]:
        buckets: dict[int, list[dict]] = {}
        for it in all_items:
            if exclude_recent and it["id"] in recent:
                continue
            buckets.setdefault(int(it["difficulty"]), []).append(it)
        for diff in buckets:
            buckets[diff].sort(key=lambda it: (used.get(it["id"], 0), it["id"]))
        return buckets

    buckets = pool(exclude_recent=bool(recent))
    if sum(len(v) for v in buckets.values()) < min(n, len(all_items)):
        buckets = pool(exclude_recent=False)  # bank too small to be picky — allow repeats

    chosen: list[dict] = []
    diffs = sorted(buckets)
    # round-robin across difficulty buckets so the spread is even
    while len(chosen) < n and any(buckets[d] for d in diffs):
        for d in diffs:
            if buckets[d] and len(chosen) < n:
                chosen.append(buckets[d].pop(0))
    chosen.sort(key=lambda it: int(it["difficulty"]))
    return chosen


# --- θ estimation (1PL / Rasch, fixed item difficulties) -------------------

def estimate_theta(
    responses: list[tuple[float, int]],
    max_iter: int = 50,
    tol: float = 1e-5,
) -> float | None:
    """Maximum-likelihood θ under the 1-parameter-logistic (Rasch) model — the v1 estimator.

    Model: P(correct | θ, b_i) = 1 / (1 + exp(-(θ - b_i))), i.e. the 2PL of §3 with every
    discrimination a_i fixed to 1. `responses` is a list of (b_i, correct∈{0,1}).

    Why 1PL and why fixed b's for v1 (documented, extensible):
      * With n=1 you cannot jointly identify item discrimination/difficulty AND person
        ability from one short sitting — the doc's own guidance (§3 "Calibration
        bootstrapping") is to FIX the form with provisional author difficulties and report
        θ under a fixed-item model, then upgrade to full 2PL/marginal-ML calibration once
        many users' responses accrue. So b_i is the authored difficulty; only θ is estimated.
      * Rasch θ is a sufficient-statistic model: the estimate depends only on which items
        (their b's) were right/wrong, so a ROTATING form still yields a comparable θ. That is
        exactly the drift-proof ruler we want.

    Estimation: Newton–Raphson on the log-likelihood. The score is
    U(θ) = Σ (y_i - p_i) and the (negative) information is I(θ) = Σ p_i(1-p_i); step
    θ += U/I. Guarded: all-correct → +∞ and all-wrong → -∞ have no finite MLE, so we clamp
    to a sensible bound and flag it via the caller (n and pattern are stored regardless).

    Returns θ (logit), or None if there are no responses.
    """
    if not responses:
        return None
    n_correct = sum(y for _, y in responses)
    n = len(responses)
    # boundary responses have no finite MLE; clamp to a readable bound instead of diverging.
    _BOUND = 4.0
    if n_correct == 0:
        return -_BOUND
    if n_correct == n:
        return _BOUND

    theta = 0.0  # start at the scale centre
    for _ in range(max_iter):
        score = 0.0
        info = 0.0
        for b, y in responses:
            p = 1.0 / (1.0 + math.exp(-(theta - b)))
            score += y - p
            info += p * (1.0 - p)
        if info < 1e-9:
            break
        step = score / info
        theta += step
        theta = max(-_BOUND, min(_BOUND, theta))
        if abs(step) < tol:
            break
    return round(theta, 3)


def score_response(item: dict, correct: bool) -> tuple[float, int]:
    """Turn one graded item outcome into an (b_i, y_i) pair for θ estimation.

    Objective scoring: `correct` is the verdict the assessment agent produced by matching
    the learner's answer against the item's stored `answer`/tests. We keep it a plain 0/1
    here — the θ math lives in ``estimate_theta``.
    """
    return (_b_of(item["difficulty"]), 1 if correct else 0)


# --- recording an assessment ----------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def record_assessment(items_and_outcomes: list[dict], context: str = "") -> dict:
    """Persist one completed frozen assessment + its per-item responses, and its θ.

    `items_and_outcomes` is a list of dicts: {"item_id", "difficulty", "correct", "seconds"}.
    Computes θ under the Rasch model from the item difficulties + correctness, writes one
    `assessments` row and one `assessment_responses` row per item, and returns
    {"assessment_id", "theta", "n_items", "n_correct"}.
    """
    responses = [
        (_b_of(o["difficulty"]), 1 if o["correct"] else 0) for o in items_and_outcomes
    ]
    theta = estimate_theta(responses)
    n_items = len(items_and_outcomes)
    n_correct = sum(1 for o in items_and_outcomes if o["correct"])

    conn = connect()
    try:
        cur = conn.execute(
            "INSERT INTO assessments(started_at, ended_at, theta, n_items, context) "
            "VALUES(?, ?, ?, ?, ?)",
            (context and None or _now(), _now(), theta, n_items, context or None),
        )
        assessment_id = cur.lastrowid
        for o in items_and_outcomes:
            conn.execute(
                "INSERT INTO assessment_responses(assessment_id, item_id, correct, seconds) "
                "VALUES(?, ?, ?, ?)",
                (assessment_id, o["item_id"], int(bool(o["correct"])), o.get("seconds")),
            )
        conn.commit()
    finally:
        conn.close()
    return {"assessment_id": assessment_id, "theta": theta,
            "n_items": n_items, "n_correct": n_correct}


# --- the θ-over-time series (primary effectiveness outcome) ----------------

def _slope(points: list[tuple[float, float]]) -> float | None:
    """OLS slope of y on x (or None for < 2 points). Mirrors effectiveness._slope."""
    n = len(points)
    if n < 2:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    mx = sum(xs) / n
    my = sum(ys) / n
    denom = sum((x - mx) ** 2 for x in xs)
    if denom == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom


def history() -> dict:
    """θ per completed assessment over time — the trustworthy, non-circular ability curve.

    Returns the per-sitting series (with date, θ, n_items, n_correct), the current θ, the
    baseline θ (first sitting), the θ slope across sittings (the primary §9 outcome), and
    the frozen item-bank size. Empty/one-sitting states return safe None slopes with n so a
    caller can show confidence honestly.
    """
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT a.id, a.started_at, a.ended_at, a.theta, a.n_items, "
            "  (SELECT COUNT(*) FROM assessment_responses r "
            "   WHERE r.assessment_id = a.id AND r.correct = 1) AS n_correct "
            "FROM assessments a WHERE a.theta IS NOT NULL "
            "ORDER BY a.started_at, a.id"
        ).fetchall()
        bank_n = conn.execute("SELECT COUNT(*) AS c FROM benchmark_items").fetchone()["c"]
    finally:
        conn.close()

    series = [
        {"assessment_id": r["id"],
         "at": (r["ended_at"] or r["started_at"] or "")[:19],
         "theta": round(r["theta"], 3),
         "n_items": r["n_items"],
         "n_correct": r["n_correct"]}
        for r in rows
    ]
    slope = _slope([(i, s["theta"]) for i, s in enumerate(series)])
    return {
        "n_assessments": len(series),
        "bank_size": bank_n,
        "series": series,
        "current_theta": series[-1]["theta"] if series else None,
        "baseline_theta": series[0]["theta"] if series else None,
        "slope": round(slope, 3) if slope is not None else None,
        "rising": (slope is not None and slope > 0),
    }
