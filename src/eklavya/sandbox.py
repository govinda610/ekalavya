"""Run the learner's Python safely, and grade it against hidden tests.

The code we run is LLM-authored, so we do NOT trust it. Defences:
  - a **clean environment** — the child never inherits the parent's env, so it
    can't read the API keys that live there (this closes the obvious key-leak);
  - a **throwaway working directory** so relative paths can't touch project files;
  - a **CPU-time limit** (POSIX) plus a wall-clock timeout so it can't spin forever;
  - captured stdout/stderr and honest timing.

By default this is process-level isolation. When **bubblewrap** (`bwrap`, Linux)
is available it is used automatically to add a real *filesystem jail*: the code
runs in a namespace with a minimal read-only view of the system + Python and
*only* the throwaway workdir writable — so the learner process cannot see the home
directory, the `.env`, the codebase, or the network. If `bwrap` is absent (e.g.
macOS dev) it transparently falls back to the process-isolation path below, so
behaviour is unchanged. Control with ``EKLAVYA_SANDBOX_JAIL=auto|off`` (default
``auto``). The jail only wraps code execution — it never touches the database,
chats, ratings, artifacts, or any learner state.
"""

from __future__ import annotations

import functools
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass

_PASS_MARKER = "__EKLAVYA_TESTS_PASSED__"
# A minimal environment — deliberately without the parent's variables (API keys!).
_CLEAN_ENV = {"PATH": "/usr/bin:/bin:/usr/local/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
_CPU_SECONDS = 30  # belt-and-suspenders beyond the wall-clock timeout


def _apply_limits() -> None:  # runs in the child, before exec (POSIX only)
    import resource

    resource.setrlimit(resource.RLIMIT_CPU, (_CPU_SECONDS, _CPU_SECONDS))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))  # no core dumps


_JAIL_MODE = os.environ.get("EKLAVYA_SANDBOX_JAIL", "auto").strip().lower()  # auto | off


def _bwrap_argv(inner: list[str], workdir: str) -> list[str]:
    """Wrap `inner` in a bubblewrap jail: a read-only view of the system + Python,
    ONLY `workdir` writable, no network, and the home dir / .env / codebase simply
    absent from the mount namespace."""
    ro: list[str] = []
    seen: set[str] = set()
    for p in ("/usr", "/bin", "/sbin", "/lib", "/lib64", "/etc", "/opt", sys.prefix, sys.base_prefix):
        rp = os.path.realpath(p) if p else ""
        if rp and rp not in seen and os.path.isdir(rp):
            seen.add(rp)
            ro += ["--ro-bind", rp, rp]
    return [
        shutil.which("bwrap") or "bwrap", "--unshare-all", "--die-with-parent", "--new-session",
        "--clearenv",
        "--setenv", "PATH", _CLEAN_ENV["PATH"], "--setenv", "LANG", "C.UTF-8",
        "--setenv", "LC_ALL", "C.UTF-8", "--setenv", "HOME", workdir, "--setenv", "TMPDIR", workdir,
        *ro,
        "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
        "--bind", workdir, workdir, "--chdir", workdir,
        "--", *inner,
    ]


@functools.lru_cache(maxsize=1)
def _jail_ok() -> bool:
    """True only if bubblewrap is present AND a representative jailed run actually
    works — so we jail exactly when it won't break the run path, and otherwise fall
    back transparently to plain process isolation."""
    if _JAIL_MODE == "off" or not shutil.which("bwrap"):
        return False
    wd = tempfile.mkdtemp(prefix="eklavya-jailprobe-")
    try:
        argv = _bwrap_argv([sys.executable, "-I", "-c", "import json,os,sys;print('JAILOK')"], wd)
        r = subprocess.run(argv, capture_output=True, text=True, timeout=15)
        return r.returncode == 0 and "JAILOK" in r.stdout
    except Exception:
        return False
    finally:
        shutil.rmtree(wd, ignore_errors=True)


def jail_active() -> bool:
    """Whether learner code is currently being filesystem-jailed (for a self-test)."""
    return _jail_ok()


@dataclass
class RunResult:
    ok: bool
    stdout: str
    stderr: str
    exit_code: int
    seconds: float


def run_python(code: str, stdin: str = "", timeout: float = 8.0) -> RunResult:
    """Execute a snippet in an isolated subprocess; capture output and timing."""
    workdir = tempfile.mkdtemp(prefix="eklavya-run-")
    env = dict(_CLEAN_ENV, HOME=workdir, TMPDIR=workdir)
    inner = [sys.executable, "-I", "-c", code]
    # Real filesystem jail when bubblewrap is available (Linux); transparent
    # fallback to process isolation otherwise, so behaviour never breaks.
    cmd = _bwrap_argv(inner, workdir) if (_JAIL_MODE != "off" and _jail_ok()) else inner
    start = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            cwd=workdir,
            preexec_fn=_apply_limits if os.name == "posix" else None,
        )
    except subprocess.TimeoutExpired:
        return RunResult(False, "", f"Timed out after {timeout:.0f}s.", -1, timeout)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return RunResult(
        ok=proc.returncode == 0,
        stdout=proc.stdout,
        stderr=proc.stderr,
        exit_code=proc.returncode,
        seconds=round(time.monotonic() - start, 3),
    )


def run_tests(code: str, tests: str, timeout: float = 8.0) -> RunResult:
    """Run learner `code` followed by `tests` (which use `assert`).

    Passes only if the process exits cleanly AND the marker prints — so a test
    file that silently does nothing can't be mistaken for success.
    """
    script = f"{code}\n\n{tests}\n\nprint({_PASS_MARKER!r})"
    result = run_python(script, timeout=timeout)
    passed = result.ok and _PASS_MARKER in result.stdout
    clean_stdout = result.stdout.replace(_PASS_MARKER + "\n", "").replace(_PASS_MARKER, "")
    return RunResult(passed, clean_stdout, result.stderr, result.exit_code, result.seconds)
