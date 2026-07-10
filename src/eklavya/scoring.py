"""Rating maths — small, explicit, and calibration-aware.

The key idea (from teacher-mode): the most important signal is *miscalibration*.
Being confident and wrong — the illusion of knowing — should move your rating
much more than being confident and right. So the update size scales with the
surprise between what your confidence predicted and what actually happened.
"""

from __future__ import annotations

_BASE_K = 24.0
# We aim drills at ~65% success, so a correct answer at target difficulty barely
# moves the rating.
_TARGET = 0.65

# Confidence 1/2/3 → the success probability the learner is implicitly claiming.
_CONFIDENCE_P = {1: 0.25, 2: 0.6, 3: 0.9}


def update_elo(current: float, correct: bool, confidence: int = 2) -> float:
    """Return the new rating after one attempt.

    The calibration signal is confidence, not item difficulty (we don't have a
    reliable per-item difficulty): `surprise` amplifies the update when the outcome
    contradicts the learner's stated confidence — punishing confident-wrong (the
    illusion of knowing) and rewarding unsure-right.
    """
    score = 1.0 if correct else 0.0
    claimed = _CONFIDENCE_P.get(int(confidence), 0.6)
    surprise = abs(score - claimed)  # 0 = perfectly calibrated, 1 = maximally wrong
    k = _BASE_K * (1.0 + surprise)   # up to 2× on a big miscalibration
    return round(current + k * (score - _TARGET), 1)


def tighten(band: float) -> float:
    """Increase certainty (0→1) as evidence accumulates; each attempt closes 20%."""
    return round(band + (1.0 - band) * 0.2, 3)


def level_of(rating: float) -> str:
    if rating < 900:
        return "unknown"
    if rating < 1050:
        return "gap"
    if rating < 1300:
        return "familiar"
    return "strong"
