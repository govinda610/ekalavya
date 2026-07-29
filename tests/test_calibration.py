"""Calibration metric — the 'illusion of knowing' signal derived from attempts."""

import os
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="eklavya-calib-")
os.environ["EKLAVYA_HOME"] = _TMP
os.environ["EKLAVYA_PROFILE"] = str(Path(_TMP) / "profile.md")

import pytest  # noqa: E402

from eklavya import progress, tools  # noqa: E402
from eklavya.db import init_db  # noqa: E402


@pytest.fixture(autouse=True)
def fresh():
    from eklavya import config
    if config.DB_PATH.exists():
        config.DB_PATH.unlink()
    init_db()
    yield


def test_no_data_returns_zero():
    c = progress.calibration()
    assert c["n"] == 0 and c["confidently_wrong"] == 0 and c["brier"] is None


def test_confidently_wrong_counted_and_overconfident_bias():
    tools.add_pillar("P")
    # two 'certain' (3) attempts that are WRONG → the pure illusion of knowing
    tools.record_attempt("P", "syntax_recall", "a", 3, False, 1.0)
    tools.record_attempt("P", "syntax_recall", "b", 3, False, 1.0)
    c = progress.calibration()
    assert c["n"] == 2
    assert c["confidently_wrong"] == 2
    assert c["bias"] > 0      # certain-but-wrong ⇒ overconfident
    assert c["brier"] > 0.5   # large miscalibration


def test_well_calibrated_has_low_brier_and_is_in_stats():
    tools.add_pillar("P")
    tools.record_attempt("P", "syntax_recall", "a", 3, True, 1.0)   # certain & right
    tools.record_attempt("P", "syntax_recall", "b", 1, False, 1.0)  # guessing & wrong
    c = progress.calibration()
    assert c["confidently_wrong"] == 0
    assert c["brier"] < 0.2
    assert progress.stats()["calibration"]["n"] == 2  # surfaced in stats()
