"""Run the learner's Python safely, and grade it against hidden tests.

A local subprocess is enough here — it's the learner's own code on their own
machine, so we just need isolation from our process, a timeout, and captured
output (which also gives us honest timing). No cloud sandbox needed.
"""

from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass

_PASS_MARKER = "__EKLAVYA_TESTS_PASSED__"


@dataclass
class RunResult:
    ok: bool
    stdout: str
    stderr: str
    exit_code: int
    seconds: float


def run_python(code: str, stdin: str = "", timeout: float = 8.0) -> RunResult:
    """Execute a snippet in an isolated subprocess; capture output and timing."""
    start = time.monotonic()
    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-c", code],
            input=stdin,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return RunResult(False, "", f"Timed out after {timeout:.0f}s.", -1, timeout)
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
    # Hide the marker from the learner-facing output.
    clean_stdout = result.stdout.replace(_PASS_MARKER + "\n", "").replace(_PASS_MARKER, "")
    return RunResult(passed, clean_stdout, result.stderr, result.exit_code, result.seconds)
