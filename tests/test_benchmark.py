"""Tier-1 frozen benchmark — seed idempotency, item selection, θ estimation, history."""

import os
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="eklavya-bench-")
os.environ["EKLAVYA_HOME"] = _TMP
os.environ["EKLAVYA_PROFILE"] = str(Path(_TMP) / "profile.md")

import pytest  # noqa: E402

from eklavya import benchmark, effectiveness  # noqa: E402
from eklavya.db import connect, init_db  # noqa: E402

# The frozen bank now spans the coding starter bank + the per-subject (maths/stats)
# deterministic starters — see benchmark.seed_items (subject framework §4.4).
_TOTAL_ITEMS = len(benchmark._STARTER_ITEMS) + len(benchmark._SUBJECT_STARTER_ITEMS)


@pytest.fixture(autouse=True)
def fresh_db():
    from eklavya import config as _cfg
    db = _cfg.DB_PATH
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(db) + suffix)
        if p.exists():
            p.unlink()
    init_db()
    yield


# --- seeding ---------------------------------------------------------------

def test_seed_populates_bank():
    conn = connect()
    try:
        n = conn.execute("SELECT COUNT(*) c FROM benchmark_items").fetchone()["c"]
    finally:
        conn.close()
    assert n == _TOTAL_ITEMS > 0


def test_seed_is_idempotent():
    conn = connect()
    try:
        before = conn.execute("SELECT COUNT(*) c FROM benchmark_items").fetchone()["c"]
        # re-seeding on the same connection inserts nothing new
        added = benchmark.seed_items(conn)
        conn.commit()
        after = conn.execute("SELECT COUNT(*) c FROM benchmark_items").fetchone()["c"]
    finally:
        conn.close()
    assert added == 0 and after == before


def test_init_db_idempotent_no_duplicate_items():
    init_db()  # second call must not double the frozen bank
    init_db()
    conn = connect()
    try:
        n = conn.execute("SELECT COUNT(*) c FROM benchmark_items").fetchone()["c"]
    finally:
        conn.close()
    assert n == _TOTAL_ITEMS


# --- item selection --------------------------------------------------------

def test_select_spreads_difficulty_and_pillar():
    conn = connect()
    try:
        items = benchmark.select_items(conn, n=8)
    finally:
        conn.close()
    assert len(items) == 8
    # a fixed-difficulty θ needs a spread of b's, not all-easy/all-hard
    diffs = {it["difficulty"] for it in items}
    assert len(diffs) >= 3
    # ordered easy→hard
    assert [it["difficulty"] for it in items] == sorted(it["difficulty"] for it in items)


def test_select_avoids_recent_items():
    # record one sitting, then the next selection should prefer unseen items
    conn = connect()
    try:
        first = benchmark.select_items(conn, n=8)
    finally:
        conn.close()
    benchmark.record_assessment(
        [{"item_id": it["id"], "difficulty": it["difficulty"], "correct": True, "seconds": 5.0}
         for it in first],
        context="s1",
    )
    conn = connect()
    try:
        second = benchmark.select_items(conn, n=8, avoid_recent=2)
    finally:
        conn.close()
    first_ids = {it["id"] for it in first}
    second_ids = {it["id"] for it in second}
    # with a 20-item bank and 8 taken, the fresh pool (12) covers a full n=8 draw
    assert not (second_ids & first_ids)


# --- θ estimation ----------------------------------------------------------

def test_theta_none_for_empty():
    assert benchmark.estimate_theta([]) is None


def test_theta_boundaries_clamped():
    # all wrong → strongly negative; all correct → strongly positive (no finite MLE)
    allwrong = [(benchmark._b_of(d), 0) for d in (1, 2, 3, 4, 5)]
    allright = [(benchmark._b_of(d), 1) for d in (1, 2, 3, 4, 5)]
    assert benchmark.estimate_theta(allwrong) < -1
    assert benchmark.estimate_theta(allright) > 1


def test_theta_rises_with_more_correct():
    b = [benchmark._b_of(d) for d in (1, 2, 3, 4, 5)]
    few = list(zip(b, (1, 1, 0, 0, 0)))     # only easy right
    many = list(zip(b, (1, 1, 1, 1, 0)))    # up to hard right
    assert benchmark.estimate_theta(many) > benchmark.estimate_theta(few)


def test_theta_is_raw_score_sufficient_but_hard_form_costs():
    # Rasch property: for a FIXED form, θ depends only on how many were right (the raw
    # score is sufficient) — WHICH of the same-count items were right doesn't change θ.
    b = [benchmark._b_of(d) for d in (1, 2, 3, 4, 5)]
    easy3 = list(zip(b, (1, 1, 1, 0, 0)))
    hard3 = list(zip(b, (0, 0, 1, 1, 1)))
    assert benchmark.estimate_theta(hard3) == benchmark.estimate_theta(easy3)

    # But the θ scale IS difficulty-aware across forms: the SAME score (2/3 correct) on a
    # HARDER set of items implies a higher ability than on an EASIER set. (One wrong answer
    # keeps the MLE finite so we're not just reading the all-correct clamp.)
    hard_form = [(benchmark._b_of(5), 1), (benchmark._b_of(5), 1), (benchmark._b_of(4), 0)]
    easy_form = [(benchmark._b_of(1), 1), (benchmark._b_of(1), 1), (benchmark._b_of(2), 0)]
    assert benchmark.estimate_theta(hard_form) > benchmark.estimate_theta(easy_form)


# --- recording + history ---------------------------------------------------

def _sit(correct_of, context=""):
    conn = connect()
    try:
        items = benchmark.select_items(conn, n=8)
    finally:
        conn.close()
    outs = [{"item_id": it["id"], "difficulty": it["difficulty"],
             "correct": correct_of(it["difficulty"]), "seconds": 8.0} for it in items]
    return benchmark.record_assessment(outs, context=context)


def test_record_assessment_persists_rows_and_theta():
    r = _sit(lambda d: d <= 3, context="baseline")
    assert r["theta"] is not None and r["n_items"] == 8
    conn = connect()
    try:
        a = conn.execute("SELECT theta, n_items, context FROM assessments").fetchone()
        rn = conn.execute("SELECT COUNT(*) c FROM assessment_responses").fetchone()["c"]
    finally:
        conn.close()
    assert a["n_items"] == 8 and a["context"] == "baseline" and rn == 8


def test_history_shape_and_rising():
    empty = benchmark.history()
    assert empty["n_assessments"] == 0 and empty["current_theta"] is None
    assert empty["slope"] is None and empty["bank_size"] == _TOTAL_ITEMS

    _sit(lambda d: d <= 2, context="baseline")   # weak sitting
    _sit(lambda d: d <= 4, context="later")       # stronger sitting
    h = benchmark.history()
    assert h["n_assessments"] == 2
    assert set(h["series"][0]) == {"assessment_id", "at", "theta", "n_items", "n_correct"}
    assert h["current_theta"] > h["baseline_theta"]   # improvement shows up
    assert h["slope"] is not None and h["rising"] is True


# --- integration into the effectiveness surface ----------------------------

def test_summary_includes_benchmark():
    s = effectiveness.summary()
    assert "benchmark" in s
    assert s["benchmark"]["n_assessments"] == 0
    assert s["benchmark"]["bank_size"] == _TOTAL_ITEMS


def test_render_shows_theta_panel():
    _sit(lambda d: d <= 3, context="baseline")
    html = effectiveness.render()
    assert "Benchmark ability (θ)" in html
    assert "frozen" in html.lower()


# --- P5: per-subject benchmarks + θ ----------------------------------------

def test_select_items_is_scoped_to_subject():
    conn = connect()
    try:
        maths = benchmark.select_items(conn, n=6, subject="maths")
        stats = benchmark.select_items(conn, n=6, subject="stats")
    finally:
        conn.close()
    assert maths and all(it["subject"] == "maths" for it in maths)
    assert stats and all(it["subject"] == "stats" for it in stats)
    # answer types are the deterministic ones (never essay in the ruler)
    assert all(it["answer_type"] in {"numeric", "symbolic", "choice"} for it in maths)


def test_per_subject_theta_is_separate():
    conn = connect()
    try:
        maths = benchmark.select_items(conn, n=5, subject="maths")
    finally:
        conn.close()
    outs = [{"item_id": it["id"], "difficulty": it["difficulty"], "correct": True, "seconds": 4.0}
            for it in maths]
    benchmark.record_assessment(outs, context="m1", subject="maths")
    m = benchmark.history(subject="maths")
    c = benchmark.history(subject="coding")
    assert m["n_assessments"] == 1 and m["current_theta"] is not None
    assert c["n_assessments"] == 0  # coding ruler untouched — one ruler per subject
    # the per-subject bank size is just that subject's items
    assert m["bank_size"] == sum(1 for s, *_ in benchmark._SUBJECT_STARTER_ITEMS if s == "maths")


def test_essays_are_excluded_from_the_theta_ruler():
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO benchmark_items(subject, pillar, difficulty, prompt, answer, grader, "
            "answer_type) VALUES('maths', 'Essays', 2, 'Discuss infinity.', 'ref', 'rubric', 'essay')")
        conn.commit()
        items = benchmark.select_items(conn, n=20, subject="maths")
    finally:
        conn.close()
    assert all(it["answer_type"] != "essay" for it in items)


def test_subject_histories_and_starter_status():
    hist = benchmark.subject_histories()
    assert "coding" in hist and "maths" in hist and "stats" in hist
    status = benchmark.starter_bank_status()
    assert status["coding"] == len(benchmark._STARTER_ITEMS)
    assert status["maths"] > 0 and status["stats"] > 0
    # ml / cs_theory are documented stubs (no objective starters seeded yet)
    assert status.get("ml", 0) == 0 and status.get("cs_theory", 0) == 0
