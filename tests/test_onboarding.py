"""Onboarding-completion gate — report.is_first_run().

Onboarding is done only when BOTH exist: a graded rating AND the profile.md the
tutor writes at the end. A partially-onboarded learner (one rating, no profile)
must still be treated as first-run so they get sent through onboarding.
"""

import os
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="eklavya-onb-")
os.environ["EKLAVYA_HOME"] = _TMP
os.environ["EKLAVYA_PROFILE"] = str(Path(_TMP) / "profile.md")

import pytest  # noqa: E402

from eklavya import config, report, tools  # noqa: E402
from eklavya.db import init_db  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_state():
    from eklavya import config as _cfg
    db = _cfg.DB_PATH
    if db.exists():
        db.unlink()
    profile = config.paths().profile
    if profile.exists():
        profile.unlink()
    init_db()
    yield
    if profile.exists():
        profile.unlink()


def test_first_run_when_no_ratings_and_no_profile():
    assert report.is_first_run() is True


def test_first_run_with_one_rating_but_no_profile():
    # The onboarding hole: a graded rating landed but onboarding never finished
    # (no profile.md was written) → the learner must STILL be first-run.
    tools.set_baseline_rating("Python", "syntax_recall", "familiar")
    assert not config.paths().profile.exists()
    assert report.is_first_run() is True


def test_not_first_run_only_when_rating_and_profile_both_present():
    tools.set_baseline_rating("Python", "syntax_recall", "familiar")
    tools.save_profile("# Profile\nonboarded")
    assert report.is_first_run() is False


def test_profile_without_any_rating_is_still_first_run():
    tools.save_profile("# Profile\nno ratings yet")
    assert report.is_first_run() is True
