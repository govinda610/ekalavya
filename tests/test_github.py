"""GitHub code-context ingestion — URL parsing, repo summariser (mocked clone),
profile summariser (mocked API), and the dispatcher. Offline-safe: the network is
always mocked; the suite never makes a real request.
"""

import os
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="eklavya-github-")
os.environ["EKLAVYA_HOME"] = _TMP
os.environ["EKLAVYA_PROFILE"] = str(Path(_TMP) / "profile.md")

import pytest  # noqa: E402

from eklavya import github  # noqa: E402
from eklavya.db import init_db  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    from eklavya import config as _cfg
    db = _cfg.DB_PATH
    if db.exists():
        db.unlink()
    init_db()
    yield


# --- URL parsing ------------------------------------------------------------

@pytest.mark.parametrize("url,kind,segs", [
    ("https://github.com/octocat/hello", "repo", ["octocat", "hello"]),
    ("http://github.com/octocat/hello.git", "repo", ["octocat", "hello"]),
    ("github.com/octocat", "profile", ["octocat"]),
    ("https://www.github.com/octocat/", "profile", ["octocat"]),
    ("https://github.com/o/r/tree/main/src", "repo", ["o", "r"]),
    ("https://github.com/octocat/hello?tab=readme", "repo", ["octocat", "hello"]),
    ("https://gitlab.com/x/y", "invalid", []),
    ("not a url", "invalid", []),
    ("https://github.com/orgs/anthropics", "invalid", []),
    ("", "invalid", []),
])
def test_parse(url, kind, segs):
    assert github._parse(url) == (kind, segs)


# --- ingest_repo (clone mocked) ---------------------------------------------

def _fake_repo(dest: Path):
    """Write a small fixture tree into the 'cloned' dir, as a real clone would."""
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "requirements.txt").write_text("langgraph>=0.2\nfastapi==0.115\n")
    (dest / "app.py").write_text("import numpy as np\nfrom pandas import DataFrame\n")
    (dest / "README.md").write_text("# demo\n")
    (dest / "Dockerfile").write_text("FROM python\n")


def test_ingest_repo_summarises(monkeypatch):
    class OK:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, **kwargs):
        # the clone destination is the last positional arg in our git clone command
        dest = Path(cmd[-1])
        _fake_repo(dest)
        return OK()

    monkeypatch.setattr(github.shutil, "which", lambda _: "/usr/bin/git")
    monkeypatch.setattr(github.subprocess, "run", fake_run)

    out = github.ingest_repo("https://github.com/octocat/demo")
    assert "octocat/demo" in out
    assert "langgraph" in out
    assert "FastAPI / backend" in out
    assert "LangChain / LangGraph" in out
    assert "pandas / numpy / viz" in out  # from the sampled import
    assert "Dockerfile" in out and "requirements.txt" in out
    assert "not executed" in out


def test_ingest_repo_records_grant(monkeypatch):
    class OK:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, **kwargs):
        _fake_repo(Path(cmd[-1]))
        return OK()

    monkeypatch.setattr(github.shutil, "which", lambda _: "/usr/bin/git")
    monkeypatch.setattr(github.subprocess, "run", fake_run)
    github.ingest_repo("https://github.com/octocat/demo")

    from eklavya.db import connect
    c = connect()
    row = c.execute("SELECT stacks FROM repos WHERE path LIKE ?", ("%octocat/demo%",)).fetchone()
    c.close()
    assert row is not None and "langgraph" in row["stacks"]


def test_ingest_repo_private_or_missing(monkeypatch):
    class Fail:
        returncode = 128
        stdout = ""
        stderr = "remote: Repository not found.\nfatal: repository not found"

    monkeypatch.setattr(github.shutil, "which", lambda _: "/usr/bin/git")
    monkeypatch.setattr(github.subprocess, "run", lambda *a, **k: Fail())
    out = github.ingest_repo("https://github.com/ghost/nope")
    assert "private or does not exist" in out


def test_ingest_repo_timeout(monkeypatch):
    import subprocess as sp

    def boom(*a, **k):
        raise sp.TimeoutExpired(cmd="git", timeout=60)

    monkeypatch.setattr(github.shutil, "which", lambda _: "/usr/bin/git")
    monkeypatch.setattr(github.subprocess, "run", boom)
    out = github.ingest_repo("https://github.com/octocat/huge")
    assert "timed out" in out


def test_ingest_repo_size_cap(monkeypatch):
    class OK:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(github.shutil, "which", lambda _: "/usr/bin/git")
    monkeypatch.setattr(github.subprocess, "run", lambda cmd, **k: (_fake_repo(Path(cmd[-1])), OK())[1])
    monkeypatch.setattr(github, "_dir_size_mb", lambda _p: 999.0)
    out = github.ingest_repo("https://github.com/octocat/demo")
    assert "too large" in out


def test_ingest_repo_no_git(monkeypatch):
    monkeypatch.setattr(github.shutil, "which", lambda _: None)
    out = github.ingest_repo("https://github.com/octocat/demo")
    assert "git is not installed" in out


def test_ingest_repo_rejects_profile_url():
    out = github.ingest_repo("https://github.com/octocat")
    assert "not a GitHub repo URL" in out


# --- ingest_profile (API mocked) --------------------------------------------

class _Resp:
    def __init__(self, status, payload=None, text=""):
        self.status_code = status
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def test_ingest_profile_summarises(monkeypatch):
    payload = [
        {"name": "agentkit", "language": "Python", "stargazers_count": 42,
         "fork": False, "description": "langgraph agents"},
        {"name": "site", "language": "TypeScript", "stargazers_count": 3, "fork": False,
         "description": None},
        {"name": "forked-thing", "language": "Go", "stargazers_count": 999, "fork": True},
    ]
    monkeypatch.setattr(github, "requests", _fake_requests(_Resp(200, payload)))
    out = github.ingest_profile("https://github.com/octocat")
    assert "octocat" in out
    assert "2 public non-fork repos" in out
    assert "Python" in out and "TypeScript" in out
    assert "agentkit" in out and "★42" in out
    assert "forked-thing" not in out  # forks excluded
    assert "ML / data science" in out or "Python" in out


def test_ingest_profile_404(monkeypatch):
    monkeypatch.setattr(github, "requests", _fake_requests(_Resp(404, text="Not Found")))
    out = github.ingest_profile("github.com/ghostuser")
    assert "not found" in out


def test_ingest_profile_rate_limit(monkeypatch):
    monkeypatch.setattr(github, "requests",
                        _fake_requests(_Resp(403, text="API rate limit exceeded")))
    out = github.ingest_profile("github.com/octocat")
    assert "rate limit" in out


def test_ingest_profile_empty(monkeypatch):
    monkeypatch.setattr(github, "requests", _fake_requests(_Resp(200, [])))
    out = github.ingest_profile("github.com/octocat")
    assert "no public repositories" in out


def test_ingest_profile_offline(monkeypatch):
    class Boom:
        def get(self, *a, **k):
            raise OSError("no network")
    monkeypatch.setattr(github, "requests", Boom())
    out = github.ingest_profile("github.com/octocat")
    assert "Could not reach GitHub" in out


def test_ingest_profile_rejects_repo_url():
    out = github.ingest_profile("https://github.com/octocat/repo")
    assert "not a GitHub profile URL" in out


def _fake_requests(resp):
    """Return an object with a .get() that yields `resp`, standing in for `requests`."""
    class R:
        def get(self, *a, **k):
            return resp
    return R()


# --- dispatcher -------------------------------------------------------------

def test_read_github_dispatches_repo(monkeypatch):
    monkeypatch.setattr(github, "ingest_repo", lambda u: f"REPO:{u}")
    monkeypatch.setattr(github, "ingest_profile", lambda u: f"PROFILE:{u}")
    assert github.read_github("https://github.com/o/r").startswith("REPO:")
    assert github.read_github("github.com/o").startswith("PROFILE:")


def test_read_github_rejects_junk():
    out = github.read_github("https://example.com/x")
    assert "not a recognised GitHub URL" in out
