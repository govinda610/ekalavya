"""Read a learner's real GitHub code/stack to ground practice in their actual work.

This is the DEPLOYED-server counterpart to `eklavya scan PATH`: on a hosted server the
learner's code isn't on the box, so they hand us a GitHub link instead of a local path.

Two ingesters + a dispatcher:
  - `ingest_repo(url)`   → shallow-clones a REPO into the confined workspace (depth 1,
    size + time caps), summarises stacks/structure via the existing `repos.detect`, then
    deletes the clone. We NEVER execute anything we fetched — we only read text.
  - `ingest_profile(url)`→ hits the public GitHub REST API to list a USER's public repos,
    primary languages, and notable/most-starred projects, and infers their stack.
  - `read_github(url)`   → detects repo-vs-profile and calls the right one.

Everything fetched is UNTRUSTED text: we clone with `git -c core.hooksPath=/dev/null` so a
malicious repo can't run hooks, cap the checkout size, and read only dependency files and
sampled imports (via `repos.detect`). Fails gracefully offline / on private / 404.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import requests

from . import repos
from .workspace import workspace_dir

# --- caps (defence-in-depth against a hostile/huge repo) --------------------
_CLONE_TIMEOUT = 60          # wall-clock seconds for the clone
_MAX_CLONE_MB = 80           # hard cap on the checked-out tree; abort past this
_API_TIMEOUT = 20            # seconds per GitHub API call
_MAX_OUT = 2500              # cap the summary we hand back to the model

# github.com/<owner>/<repo>  vs  github.com/<user> (scheme optional — learners paste bare)
_GH_HOST = re.compile(r"^(?:https?://)?(?:www\.)?github\.com/", re.IGNORECASE)


def _clip(text: str) -> str:
    return text if len(text) <= _MAX_OUT else text[:_MAX_OUT] + "\n…(truncated)"


def _parse(url: str) -> tuple[str, list[str]]:
    """Return ("repo"|"profile"|"invalid", [path segments]) for a github.com URL."""
    url = (url or "").strip()
    if not _GH_HOST.match(url):
        return "invalid", []
    rest = _GH_HOST.sub("", url).strip("/")
    # drop query/fragment and a trailing .git
    rest = rest.split("?", 1)[0].split("#", 1)[0]
    segs = [s for s in rest.split("/") if s]
    if not segs:
        return "invalid", []
    if segs[0] in ("orgs", "sponsors", "settings", "topics", "search"):
        return "invalid", []
    if len(segs) == 1:
        return "profile", segs
    # owner/repo (ignore deeper paths like /tree/main/...) — treat as a repo
    repo = segs[1][:-4] if segs[1].endswith(".git") else segs[1]
    return "repo", [segs[0], repo]


def _dir_size_mb(path: Path) -> float:
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += (Path(root) / f).stat().st_size
            except OSError:
                continue
    return total / (1024 * 1024)


def _notable_files(root: Path) -> list[str]:
    """A few structure signals: top-level entrypoints/config that hint at project type."""
    markers = ("pyproject.toml", "requirements.txt", "package.json", "Dockerfile",
               "docker-compose.yml", "Makefile", "README.md", "setup.py", "pom.xml",
               "go.mod", "Cargo.toml", "tsconfig.json", ".github")
    return sorted(m for m in markers if (root / m).exists())


def ingest_repo(url: str) -> str:
    """Shallow-clone a GitHub REPO into the confined workspace and summarise it.

    depth-1 clone into a temp dir under the workspace, with a size cap + timeout, hooks
    disabled, and the credential helper turned off (no auth prompt on private repos —
    it just fails). Reuses `repos.detect` for the stack/pillar mapping, then deletes the
    clone. Returns a concise text summary for the tutor. Never runs fetched code.
    """
    kind, segs = _parse(url)
    if kind != "repo":
        return f"'{url}' is not a GitHub repo URL (expected github.com/<owner>/<repo>)."

    if shutil.which("git") is None:
        return "Cannot ingest repo: git is not installed on the server."

    clone_url = f"https://github.com/{segs[0]}/{segs[1]}.git"
    parent = workspace_dir() / ".gh-clones"
    parent.mkdir(parents=True, exist_ok=True)
    dest = Path(tempfile.mkdtemp(prefix="repo-", dir=str(parent)))

    # Clean env: no inherited creds, no auth prompt, no hooks. Treat the repo as hostile.
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/local/bin"),
        "HOME": str(dest),
        "GIT_TERMINAL_PROMPT": "0",           # never block on a credential prompt
        "GIT_ASKPASS": "true",
        "GCM_INTERACTIVE": "never",
    }
    try:
        proc = subprocess.run(
            ["git", "-c", "core.hooksPath=/dev/null", "-c", "credential.helper=",
             "clone", "--depth", "1", "--no-tags", "--single-branch",
             clone_url, str(dest)],
            capture_output=True, text=True, timeout=_CLONE_TIMEOUT, env=env,
        )
        if proc.returncode != 0:
            err = (proc.stderr or "").strip().splitlines()
            tail = err[-1] if err else "unknown error"
            if "not found" in tail.lower() or "authentication" in tail.lower():
                return (f"Could not clone {segs[0]}/{segs[1]}: repo is private or does "
                        "not exist. Ask the learner for a public repo URL.")
            return f"Could not clone {segs[0]}/{segs[1]}: {tail}"

        size = _dir_size_mb(dest)
        if size > _MAX_CLONE_MB:
            return (f"Repo {segs[0]}/{segs[1]} is too large to analyse "
                    f"({size:.0f} MB > {_MAX_CLONE_MB} MB cap); skipped for safety.")

        found = repos.detect(dest)
        structure = _notable_files(dest)
        # record the ingest so pillars can be traced back to it (path is the URL here)
        repos.grant(clone_url, ",".join(found["stacks"]), ",".join(found["pillars"]))
    except subprocess.TimeoutExpired:
        return f"Cloning {segs[0]}/{segs[1]} timed out ({_CLONE_TIMEOUT}s) — try a smaller repo."
    except FileNotFoundError:
        return "Cannot ingest repo: git is not installed on the server."
    except Exception as exc:  # offline / DNS / disk — fail gracefully
        return f"Could not ingest repo {segs[0]}/{segs[1]}: {exc}"
    finally:
        shutil.rmtree(dest, ignore_errors=True)

    lines = [f"GitHub repo: {segs[0]}/{segs[1]}"]
    lines.append("Detected stacks: " + (", ".join(found["stacks"]) or "none recognised"))
    lines.append("Suggested pillars: " + (", ".join(found["pillars"]) or "none"))
    lines.append("Notable files: " + (", ".join(structure) or "none at top level"))
    lines.append("(Read-only shallow clone; code was not executed and has been deleted.)")
    return _clip("\n".join(lines))


def ingest_profile(url: str) -> str:
    """Summarise a GitHub USER's public work via the public REST API (no auth).

    Lists public repos, ranks by stars, reports primary languages and notable projects,
    and infers the user's stack. Handles rate-limits / offline gracefully. Untrusted text.
    """
    kind, segs = _parse(url)
    if kind != "profile":
        return f"'{url}' is not a GitHub profile URL (expected github.com/<user>)."
    user = segs[0]

    api = f"https://api.github.com/users/{user}/repos"
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "eklavya-tutor"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("EKLAVYA_GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        resp = requests.get(
            api, headers=headers,
            params={"per_page": 100, "sort": "pushed", "type": "owner"},
            timeout=_API_TIMEOUT,
        )
    except Exception as exc:  # offline / DNS
        return f"Could not reach GitHub for '{user}': {exc}. Check the URL or try again."

    if resp.status_code == 404:
        return f"GitHub user '{user}' not found (404). Check the profile URL."
    if resp.status_code == 403 and "rate limit" in resp.text.lower():
        return ("GitHub API rate limit hit (unauthenticated). Try again later, or set "
                "GITHUB_TOKEN on the server for a higher limit.")
    if resp.status_code != 200:
        return f"GitHub API error for '{user}' (HTTP {resp.status_code})."

    try:
        reposdata = resp.json()
    except ValueError:
        return f"GitHub returned an unexpected response for '{user}'."
    if not isinstance(reposdata, list) or not reposdata:
        return f"'{user}' has no public repositories to learn from."

    # count languages, collect stacks, find the most-starred notable projects
    lang_count: dict[str, int] = {}
    stacks: set[str] = set()
    for r in reposdata:
        if r.get("fork"):
            continue
        lang = r.get("language")
        if lang:
            lang_count[lang] = lang_count.get(lang, 0) + 1
            key = lang.lower()
            if key in repos.PILLAR_MAP:
                stacks.add(key)
    top_langs = sorted(lang_count, key=lambda k: -lang_count[k])[:6]

    non_forks = [r for r in reposdata if not r.get("fork")]
    notable = sorted(non_forks, key=lambda r: r.get("stargazers_count", 0) or 0, reverse=True)[:6]

    pillars = sorted({repos.PILLAR_MAP[s] for s in stacks})
    lines = [f"GitHub profile: {user} ({len(non_forks)} public non-fork repos)"]
    lines.append("Primary languages: " + (", ".join(top_langs) or "unknown"))
    if pillars:
        lines.append("Suggested pillars (from languages): " + ", ".join(pillars))
    if notable:
        lines.append("Notable projects:")
        for r in notable:
            stars = r.get("stargazers_count", 0) or 0
            desc = (r.get("description") or "").strip().replace("\n", " ")[:90]
            lang = r.get("language") or "?"
            lines.append(f"  - {r.get('name', '?')} [{lang}, ★{stars}]"
                         + (f" — {desc}" if desc else ""))
    lines.append("(Public metadata only; no code was cloned or executed.)")
    return _clip("\n".join(lines))


def read_github(url: str) -> str:
    """Read a learner's real GitHub code/stack to ground practice in their actual work.

    Pass EITHER a repo URL (github.com/<owner>/<repo>) — shallow-clones it read-only and
    summarises its languages, dependencies, structure, and suggested pillars — OR a profile
    URL (github.com/<user>) — lists their public repos, primary languages, and notable
    projects to infer their stack. Detects which kind it is automatically. Fetched code is
    never executed; fails gracefully on private/404 repos or when offline.
    """
    kind, _segs = _parse(url)
    if kind == "repo":
        return ingest_repo(url)
    if kind == "profile":
        return ingest_profile(url)
    return (f"'{url}' is not a recognised GitHub URL. Give me a repo "
            "(github.com/<owner>/<repo>) or a profile (github.com/<user>) link.")
