"""The subject registry — the single source of truth for what subjects exist, which
axes each measures, and what answer types (graders) each admits.

Design: docs/UNIFIED_SUBJECT_FRAMEWORK_PLAN.md (Option C — a universal competency
CORE every subject shares, PLUS per-subject extension axes). This module is pure,
in-code data + small helpers — no DB, no LLM — so it's trivially testable and imported
freely. The `subjects`/`axes` tables (db/schema.sql) are SEEDED from this registry
idempotently; this module stays the authoritative definition.

Nothing here forces coding axes onto econometrics, and nothing throws away the
cross-subject "where should I invest?" comparability the effectiveness view needs: the
6 CORE axes are always comparable across subjects; extensions capture subject fidelity.
"""

from __future__ import annotations

# --- the universal competency CORE (shared vocabulary, always comparable) ---
# Definitions live in the plan §4.1. Order is the canonical grid column order.
CORE_AXES: tuple[str, ...] = (
    "recall",           # retrieve a fact/definition/formula/API from memory
    "application",      # apply a known method to a standard problem
    "derivation_proof", # derive a result / construct or critique a proof rigorously
    "interpretation",   # read a result/output/model and say what it MEANS
    "synthesis",        # combine multiple ideas into a novel solution / design
    "transfer",         # apply a skill in an unfamiliar context (anti-atrophy signal)
)

# --- legacy coding axes → new world (lossless migration mapping, plan §4.1/§6) ---
# syntax_recall→recall and decomposition→synthesis land on the CORE (so coding is
# comparable there); debugging/code_reading/api_memory stay as coding EXTENSIONS.
LEGACY_AXIS_REMAP: dict[str, str] = {
    "syntax_recall": "recall",
    "decomposition": "synthesis",
}


def remap_axis(axis: str) -> str:
    """Map a legacy coding axis label to its new-world equivalent (identity otherwise)."""
    return LEGACY_AXIS_REMAP.get(axis, axis)


# --- answer types (which grader path an item takes; plan §5.1) ---
ANSWER_TYPES: tuple[str, ...] = (
    "code",       # execution / hidden tests (the existing tamper-proof path)
    "numeric",    # numeric answer with abs/rel tolerance
    "symbolic",   # algebraic equivalence via SymPy
    "units",      # dimensional + magnitude check
    "choice",     # MCQ / true-false / cloze / canonical short-answer key
    "proof",      # rubric-judged (reference + rubric)
    "interpretation",  # rubric-judged statistical/econometric reading
    "explanation",     # rubric-judged conceptual explanation
    "essay",      # rubric-judged, lower-stakes; EXCLUDED from the frozen θ ruler
)

# Answer types that are graded deterministically (ground-truth, tamper-proof).
DETERMINISTIC_TYPES: frozenset[str] = frozenset({"code", "numeric", "symbolic", "units", "choice"})

# Answer types excluded from the frozen Tier-1 benchmark / θ (practice only).
THETA_EXCLUDED_TYPES: frozenset[str] = frozenset({"essay"})


class Subject:
    """One subject's declaration: its CORE-axis subset, its extension axes, and the
    answer types it admits. `axes` is the full ordered list the grid renders for it."""

    __slots__ = ("key", "name", "core_axes", "ext_axes", "answer_types", "is_custom")

    def __init__(self, key: str, name: str, core_axes: tuple[str, ...],
                 ext_axes: tuple[str, ...] = (), answer_types: tuple[str, ...] = (),
                 is_custom: bool = False):
        self.key = key
        self.name = name
        self.core_axes = core_axes
        self.ext_axes = ext_axes
        self.answer_types = answer_types
        self.is_custom = is_custom

    @property
    def axes(self) -> tuple[str, ...]:
        """The full ordered axis set for this subject: its CORE subset then extensions."""
        return tuple(self.core_axes) + tuple(self.ext_axes)


# --- the built-in subject registry (plan §4.1) -----------------------------
# Stats & Econometrics are ONE subject (locked decision). Coding keeps its three
# extension axes verbatim; syntax_recall→recall & decomposition→synthesis fold into CORE.
_SUBJECTS: tuple[Subject, ...] = (
    Subject(
        # Core: recall/application/transfer (plan §4.1) + synthesis, because the legacy
        # `decomposition` axis remaps onto `synthesis` (plan §4.1/§6) and its historical
        # ratings must stay valid for coding, not just readable — otherwise the port isn't
        # lossless for *future* practice on that cell.
        "coding", "Coding",
        core_axes=("recall", "application", "synthesis", "transfer"),
        ext_axes=("debugging", "code_reading", "api_memory"),
        answer_types=("code", "choice", "explanation"),
    ),
    Subject(
        "maths", "Mathematics",
        core_axes=("recall", "application", "derivation_proof", "transfer"),
        ext_axes=("symbolic_manipulation", "counterexample_construction"),
        answer_types=("numeric", "symbolic", "proof", "choice"),
    ),
    Subject(
        "stats", "Statistics & Econometrics",
        core_axes=("recall", "application", "derivation_proof", "interpretation", "transfer"),
        ext_axes=("assumption_checking", "model_specification", "inference_validity"),
        answer_types=("numeric", "interpretation", "proof", "choice"),
    ),
    Subject(
        "ml", "Machine Learning & DS Theory",
        core_axes=("recall", "application", "derivation_proof", "interpretation",
                   "synthesis", "transfer"),
        ext_axes=("experimental_design", "failure_diagnosis", "metric_selection"),
        answer_types=("numeric", "symbolic", "explanation", "code", "choice"),
    ),
    Subject(
        "cs_theory", "CS Theory",
        core_axes=("recall", "application", "derivation_proof", "transfer"),
        ext_axes=("complexity_analysis", "reduction_construction"),
        answer_types=("proof", "choice", "explanation"),
    ),
)

_BY_KEY: dict[str, Subject] = {s.key: s for s in _SUBJECTS}

# The default subject every legacy row backfills to.
DEFAULT_SUBJECT = "coding"


def all_subjects() -> tuple[Subject, ...]:
    return _SUBJECTS


def get(key: str) -> Subject | None:
    return _BY_KEY.get((key or "").strip())


def exists(key: str) -> bool:
    return (key or "").strip() in _BY_KEY


def axes_for(subject: str) -> tuple[str, ...]:
    """The valid axis set for a subject (CORE subset + extensions), or the coding set
    as a safe default for an unknown key."""
    s = get(subject) or _BY_KEY[DEFAULT_SUBJECT]
    return s.axes


def valid_axis(subject: str, axis: str) -> bool:
    return axis in axes_for(subject)


def all_axis_catalog() -> list[tuple[str, str, str]]:
    """(key, kind, label) rows for the `axes` catalog table: every CORE axis once, then
    each subject's extension axes (deduped). `kind` is 'core' or 'ext'."""
    seen: set[str] = set()
    out: list[tuple[str, str, str]] = []
    for ax in CORE_AXES:
        out.append((ax, "core", ax.replace("_", " ")))
        seen.add(ax)
    for s in _SUBJECTS:
        for ax in s.ext_axes:
            if ax not in seen:
                out.append((ax, "ext", ax.replace("_", " ")))
                seen.add(ax)
    return out
