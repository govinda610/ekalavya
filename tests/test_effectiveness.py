"""Tier-0 effectiveness — summary() metrics, the export command, and the view."""

import csv
import json
import os
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="eklavya-effect-")
os.environ["EKLAVYA_HOME"] = _TMP
os.environ["EKLAVYA_PROFILE"] = str(Path(_TMP) / "profile.md")

import pytest  # noqa: E402

from eklavya import effectiveness, progress, tools  # noqa: E402
from eklavya.db import init_db  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    from eklavya import config as _cfg
    db = _cfg.DB_PATH
    if db.exists():
        db.unlink()
    init_db()
    yield


def _seed():
    """A small mix: two pillars, some unaided + one assisted attempt."""
    tools.add_pillar("Python")
    tools.add_pillar("SQL")
    progress.start_session(30)
    tools.record_attempt("Python", "syntax_recall", "list comprehension", 3, True, 12.0)
    tools.record_attempt("Python", "debugging", "off-by-one", 2, True, 20.0)
    tools.record_attempt("SQL", "syntax_recall", "group by", 1, False, 30.0)
    tools.record_attempt("Python", "syntax_recall", "list comprehension", 2, False, 15.0, ai_off=False)


def test_summary_shape_empty_db():
    s = effectiveness.summary()
    assert set(s) == {"generated_at", "unaided", "elo", "calibration", "retention", "dose"}
    assert s["unaided"]["unaided_n"] == 0
    assert s["elo"]["n_pillars"] == 0 and s["elo"]["overall_rating"] is None
    assert s["retention"]["n"] == 0 and s["retention"]["rate"] is None
    assert s["dose"]["attempts"] == 0


def test_summary_with_data():
    _seed()
    s = effectiveness.summary()

    # unaided: 3 AI-off attempts, 1 assisted; gap = assisted - unaided
    u = s["unaided"]
    assert u["unaided_n"] == 3 and u["assisted_n"] == 1
    assert u["unaided_rate"] == 67  # 2 of 3 unaided correct
    assert u["gap"] == u["assisted_rate"] - u["unaided_rate"]

    # elo: two pillars rated, strengths/weaknesses ordered by rating
    el = s["elo"]
    assert el["n_pillars"] == 2 and el["overall_rating"] is not None
    assert el["history_n"] == 4
    assert el["strengths"][0]["rating"] >= el["strengths"][-1]["rating"]
    assert el["weaknesses"][0]["rating"] <= el["strengths"][0]["rating"]

    # calibration reused from progress
    assert s["calibration"]["n"] == 4

    # dose counts
    d = s["dose"]
    assert d["attempts"] == 4 and d["sessions"] == 1 and d["active_days"] == 1


def test_export_csv_writes_header_and_rows():
    _seed()
    out = Path(_TMP) / "attempts.csv"
    n = effectiveness.export_attempts(out, "csv")
    assert n == 4
    with out.open() as f:
        rows = list(csv.DictReader(f))
    assert list(rows[0].keys()) == effectiveness.EXPORT_COLUMNS
    assert len(rows) == 4
    # pillar/axis recovered from rating_history pairing; ratings present
    assert rows[0]["pillar"] == "Python" and rows[0]["axis"] == "syntax_recall"
    assert rows[0]["concept"] == "list comprehension"
    assert rows[0]["rating_after"] and rows[0]["rating_before"]


def test_export_jsonl():
    _seed()
    out = Path(_TMP) / "attempts.jsonl"
    n = effectiveness.export_attempts(out, "jsonl")
    assert n == 4
    lines = out.read_text().strip().splitlines()
    assert len(lines) == 4
    first = json.loads(lines[0])
    assert set(first) == set(effectiveness.EXPORT_COLUMNS)


def test_export_empty_still_writes_header():
    out = Path(_TMP) / "empty.csv"
    n = effectiveness.export_attempts(out, "csv")
    assert n == 0
    assert out.read_text().strip() == ",".join(effectiveness.EXPORT_COLUMNS)


def test_render_and_route():
    _seed()
    html = effectiveness.render()
    assert "AM I GETTING BETTER?" in html
    assert "unaided" in html.lower()
    from starlette.testclient import TestClient

    from eklavya.webapp import create_app

    client = TestClient(create_app())
    assert client.get("/effectiveness").status_code == 200
    assert client.get("/api/effectiveness").status_code == 200


def test_export_command():
    _seed()
    from typer.testing import CliRunner

    from eklavya.cli import app

    out = Path(_TMP) / "cli_out.csv"
    result = CliRunner().invoke(app, ["export", "--out", str(out), "--format", "csv"])
    assert result.exit_code == 0, result.output
    assert out.exists()
    with out.open() as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 4
