"""Deterministic, ground-truth graders — the tamper-proof path for non-code answers.

docs/UNIFIED_SUBJECT_FRAMEWORK_PLAN.md §5. These extend the tamper-proof guarantee of
the code sandbox (tools.grade_and_record) to maths and stats: each grader does ONE
deterministic thing with NO LLM in the loop, so the model can't fake the outcome — the
grader decides truth, not the tutor. Every grader returns a `GradeResult` with a
`score ∈ [0,1]` (partial credit is first-class) plus a short human-readable `detail`.

The one runtime dependency is SymPy (a real dependency, small + pure-Python) for
symbolic/dimensional equivalence; numeric/choice are stdlib-only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Resource guards for the SymPy path (symbolic answers are untrusted LLM/learner input, so a
# crafted "symbolic bomb" — a huge or deeply-nested expression — could stall the process).
# Two cheap caps: refuse over-long input outright, and run each parse/simplify under a wall-time
# limit in a worker thread so a pathological expression can't block the caller indefinitely.
_MAX_EXPR_LEN = 400  # a real maths answer is short; anything longer is refused before parsing
_SYMPY_TIMEOUT = 3.0  # seconds of wall-time any single parse/simplify may take


class _GraderTimeout(Exception):
    """Raised when a SymPy operation exceeds _SYMPY_TIMEOUT."""


def _with_timeout(fn, *args, seconds: float = _SYMPY_TIMEOUT):
    """Run `fn(*args)` in a daemon thread, raising _GraderTimeout if it runs past `seconds`.

    Works off the main thread (unlike signal.alarm), so it's safe in the web workers. It cannot
    force-kill the runaway thread, but it returns control to the caller so one bad expression
    can't hang a request; combined with the length cap this keeps the graders bounded in practice.
    """
    import threading

    box: dict = {}

    def _run():
        try:
            box["v"] = fn(*args)
        except BaseException as e:  # noqa: BLE001 — propagate the real error to the caller
            box["e"] = e

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(seconds)
    if t.is_alive():
        raise _GraderTimeout(f"symbolic grading exceeded {seconds:g}s")
    if "e" in box:
        raise box["e"]
    return box.get("v")


@dataclass
class GradeResult:
    """The outcome of one deterministic grading. `score` is the partial-credit fraction;
    `correct` is thresholded at τ by the recording path, not here."""
    score: float
    detail: str = ""
    grader: str = ""
    criteria: list[dict] = field(default_factory=list)  # populated by the rubric judge (P4)


# --- numeric --------------------------------------------------------------

_NUM_RE = re.compile(r"[-+]?(?:\d[\d,]*\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def _parse_number(text: str) -> float | None:
    """Pull the first numeric literal out of a free-form answer, tolerant of %, commas,
    scientific notation, and surrounding words. Returns None when there's no number."""
    if text is None:
        return None
    s = str(text).strip().replace(",", "")
    is_pct = s.rstrip().endswith("%")
    m = _NUM_RE.search(s)
    if not m:
        return None
    try:
        val = float(m.group(0))
    except ValueError:
        return None
    return val / 100.0 if is_pct else val


def grade_numeric(answer: str, key: str, tol: float = 0.0, rel: float = 0.0) -> GradeResult:
    """Grade a numeric answer against a key with absolute (`tol`) and/or relative (`rel`)
    tolerance. Exact match when both are 0. Deterministic → as trustworthy as code tests.

    - tol: absolute tolerance (|a - key| ≤ tol).
    - rel: relative tolerance (|a - key| ≤ rel * |key|).
    An answer passes if EITHER tolerance is satisfied. `%` and scientific notation are parsed.
    """
    a = _parse_number(answer)
    k = _parse_number(key)
    if a is None or k is None:
        return GradeResult(0.0, "could not parse a number", "numeric")
    diff = abs(a - k)
    ok = (diff == 0) or (tol > 0 and diff <= tol) or (rel > 0 and diff <= rel * abs(k))
    detail = f"{a} vs key {k} (Δ={diff:g}" + (f", tol={tol:g}" if tol else "") + (f", rel={rel:g}" if rel else "") + ")"
    return GradeResult(1.0 if ok else 0.0, detail, "numeric")


# --- symbolic (SymPy equivalence) -----------------------------------------

def _sympify(expr: str):
    """Parse an expression string into a SymPy object (implicit multiplication + ^ as
    power, like a human writes maths). Returns None on any parse failure, on over-long input
    (a symbolic-bomb guard), or on a parse that runs past the wall-time limit."""
    from sympy.parsing.sympy_parser import (  # local import: sympy is a real but heavy dep
        convert_xor, implicit_multiplication_application, parse_expr, standard_transformations)
    s = str(expr).strip()
    if len(s) > _MAX_EXPR_LEN:
        return None
    try:
        transforms = standard_transformations + (
            implicit_multiplication_application, convert_xor)
        return _with_timeout(lambda: parse_expr(s, transformations=transforms, evaluate=True))
    except Exception:
        return None


def grade_symbolic(answer: str, reference: str) -> GradeResult:
    """Grade an algebraic/symbolic answer by SymPy EQUIVALENCE, not string match — so
    `(x+1)^2` == `x^2+2x+1` and `sin^2+cos^2` == `1`. Verdict = simplify(a - ref) == 0,
    with a `.equals()` fallback for transcendental cases and a random-point numeric
    spot-check to catch SymPy false-negatives (plan §9). Accepts equivalent forms."""
    import sympy as sp

    a = _sympify(answer)
    r = _sympify(reference)
    if a is None or r is None:
        return GradeResult(0.0, "could not parse an expression", "symbolic")
    try:
        if _with_timeout(lambda: sp.simplify(a - r)) == 0:
            return GradeResult(1.0, "symbolically equal", "symbolic")
    except Exception:
        pass
    try:
        if _with_timeout(lambda: a.equals(r)):  # slower, handles some transcendental identities
            return GradeResult(1.0, "equal (equals())", "symbolic")
    except Exception:
        pass
    # numeric spot-check: evaluate both at a few random points; equal everywhere ⇒ equal.
    def _spot_check() -> bool:
        syms = sorted(a.free_symbols | r.free_symbols, key=str)
        import random
        rng = random.Random(0)
        for _ in range(5):
            subs = {s: rng.uniform(0.1, 2.0) for s in syms}
            va, vr = complex(a.subs(subs)), complex(r.subs(subs))
            if abs(va - vr) > 1e-6:
                return False
        return True

    try:
        if _with_timeout(_spot_check):
            return GradeResult(1.0, "numerically equivalent at sampled points", "symbolic")
        return GradeResult(0.0, "not equivalent", "symbolic")
    except Exception:
        return GradeResult(0.0, "not equivalent", "symbolic")


# --- units / dimensional --------------------------------------------------

def grade_units(answer: str, reference: str) -> GradeResult:
    """Grade a physical quantity for BOTH dimension and magnitude via SymPy's units system
    (e.g. `3 m/s` vs `3 meter/second`, or `300 cm` vs `3 m`). Returns 0 on a dimension
    mismatch even if the number matches. Best-effort: unparseable input → 0 with a note."""
    from sympy.physics.units import convert_to
    from sympy.physics.units.systems.si import SI

    a = _sympify_units(answer)
    r = _sympify_units(reference)
    if a is None or r is None:
        return GradeResult(0.0, "could not parse a quantity/units", "units")
    try:
        import sympy as sp

        def _compare():
            da = SI.get_dimensional_expr(a)
            dr = SI.get_dimensional_expr(r)
            if sp.simplify(da - dr) != 0:
                return None  # dimension mismatch
            # same dimension → compare magnitudes by converting a into r's units.
            conv = convert_to(a, r)
            ratio = sp.simplify(conv / r)
            return abs(complex(ratio) - 1.0) < 1e-6

        ok = _with_timeout(_compare)
        if ok is None:
            return GradeResult(0.0, "dimension mismatch", "units")
        return GradeResult(1.0 if ok else 0.0,
                           "dimension + magnitude match" if ok else "magnitude mismatch", "units")
    except Exception:
        return GradeResult(0.0, "could not compare quantities", "units")


def _sympify_units(text: str):
    """Parse `<number> <unit-expr>` using SymPy's SI unit symbols in scope. Refuses over-long
    input (symbolic-bomb guard) and bounds the parse with the wall-time limit."""
    from sympy.physics import units as u
    from sympy.parsing.sympy_parser import (
        implicit_multiplication_application, parse_expr, standard_transformations)
    s = str(text).strip()
    if len(s) > _MAX_EXPR_LEN:
        return None
    try:
        local = {name: getattr(u, name) for name in dir(u) if not name.startswith("_")}
        transforms = standard_transformations + (implicit_multiplication_application,)
        return _with_timeout(
            lambda: parse_expr(s, transformations=transforms, local_dict=local, evaluate=True))
    except Exception:
        return None


# --- choice / cloze / canonical short-answer key --------------------------

def _normalise(s: str) -> str:
    """Lower-case, collapse whitespace, strip surrounding punctuation — a lenient
    normalisation for MCQ letters, cloze fills, and canonical short answers."""
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s.strip(" .,:;!?\"'()[]{}")


def grade_choice(answer: str, key: str) -> GradeResult:
    """Grade an MCQ / true-false / cloze / canonical short-answer by normalised key match.
    The key may be a pipe-list of accepted answers (`b|B|beta`), any of which passes."""
    ans = _normalise(answer)
    accepted = {_normalise(k) for k in str(key).split("|") if k.strip()}
    ok = ans in accepted and ans != ""
    return GradeResult(1.0 if ok else 0.0,
                       f"'{answer}' " + ("matches key" if ok else f"≠ {sorted(accepted)}"), "choice")


# --- the dispatcher -------------------------------------------------------

def grade(answer: str, item: dict) -> GradeResult:
    """Pick a deterministic grader from the item's `answer_type` and run it.

    `item` carries {answer_type, answer (the key/reference), tolerance (JSON for numeric)}.
    Only the DETERMINISTIC answer types are handled here (code is graded by the sandbox
    path; proof/interpretation/explanation/essay go to the constrained rubric judge in P4).
    Raises ValueError for a non-deterministic type so the caller routes it to the judge.
    """
    import json

    atype = (item.get("answer_type") or "code").strip()
    key = item.get("answer", "")
    if atype == "numeric":
        tol_raw = item.get("tolerance")
        tol = json.loads(tol_raw) if isinstance(tol_raw, str) and tol_raw.strip() else (tol_raw or {})
        return grade_numeric(answer, key, float(tol.get("abs", 0) or 0), float(tol.get("rel", 0) or 0))
    if atype == "symbolic":
        return grade_symbolic(answer, key)
    if atype == "units":
        return grade_units(answer, key)
    if atype == "choice":
        return grade_choice(answer, key)
    raise ValueError(f"answer_type '{atype}' is not deterministically gradable here")


DETERMINISTIC_TYPES = frozenset({"numeric", "symbolic", "units", "choice"})
