"""Effectiveness Tier 2 (v1): research consent + multiple-baseline intervention starts +
pre-registration — the n=1 self-experiment support."""

import os
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="eklavya-exp-")
os.environ["EKLAVYA_HOME"] = _TMP
os.environ["EKLAVYA_PROFILE"] = str(Path(_TMP) / "profile.md")

import pytest  # noqa: E402

from eklavya import experiments as ex  # noqa: E402
from eklavya import settings  # noqa: E402
from eklavya.db import init_db  # noqa: E402


@pytest.fixture(autouse=True)
def fresh():
    from eklavya import config
    if config.DB_PATH.exists():
        config.DB_PATH.unlink()
    # reset the settings file too (consent lives there)
    sp = config.paths().home / "settings.json"
    if sp.exists():
        sp.unlink()
    init_db()
    yield


def test_consent_defaults_off_and_toggles():
    assert ex.is_consented() is False
    ex.set_consent(True)
    assert ex.is_consented() is True and settings.get_research_consent() is True
    ex.set_consent(False)
    assert ex.is_consented() is False


def test_intervention_start_is_one_row_per_pillar_and_updates_note():
    ex.log_intervention_start("Python Fundamentals", "begin basics")
    ex.log_intervention_start("RAG & Vector Retrieval")
    ex.log_intervention_start("Python Fundamentals", "revised note")  # updates, not duplicates
    starts = ex.intervention_starts()
    assert len(starts) == 2
    by = {s["pillar"]: s for s in starts}
    assert by["Python Fundamentals"]["note"] == "revised note"
    assert by["RAG & Vector Retrieval"]["note"] in ("", None)
    assert all(s["started_at"] for s in starts)


def test_preregistration_records_in_order():
    ex.prereg("unaided_accuracy_slope", "rises >0 after 4 weeks")
    ex.prereg("theta", "climbs vs baseline")
    pregs = ex.preregistrations()
    assert [p["metric"] for p in pregs] == ["unaided_accuracy_slope", "theta"]
    assert pregs[0]["hypothesis"].startswith("rises") and pregs[0]["created_at"]


def test_init_db_idempotent_with_tier2_tables():
    init_db(); init_db()  # must not raise or duplicate
    ex.log_intervention_start("X")
    assert len(ex.intervention_starts()) == 1
