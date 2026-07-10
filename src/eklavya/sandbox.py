"""Run the learner's Python safely, and grade it against hidden tests.

The code we run is LLM-authored, so we do NOT trust it. Defences:
  - a **clean environment** — the child never inherits the parent's env, so it
    can't read the API keys that live there (this closes the obvious key-leak);
  - a **throwaway working directory** so relative paths can't touch project files;
  - a **CPU-time limit** (POSIX) plus a wall-clock timeout so it can't spin forever;
  - captured stdout/stderr and honest timing.

This is process-level isolation, not a jail. For running untrusted third-party
code we'd swap in a container/nsjail; for the learner's own code it's enough.
"""

from __future__ import annotations

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
    start = time.monotonic()
    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-c", code],
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
