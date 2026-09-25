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
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass

# A minimal environment — deliberately without the parent's variables (API keys!).
_CLEAN_ENV = {"PATH": "/usr/bin:/bin:/usr/local/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
_CPU_SECONDS = 30  # belt-and-suspenders beyond the wall-clock timeout
_FSIZE_BYTES = 64 * 1024 * 1024  # cap file writes so a run can't fill the disk


def _apply_limits() -> None:  # runs in the child, before exec (POSIX only)
    import resource

    resource.setrlimit(resource.RLIMIT_CPU, (_CPU_SECONDS, _CPU_SECONDS))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))  # no core dumps
    # Cap total bytes any single file can grow to, so a run can't fill the host disk. (Memory
    # and process-count limits are enforced at the cgroup level by the systemd unit — RLIMIT_AS
    # would break legitimate numpy/torch virtual-memory reservations, so we don't set it here.)
    try:
        resource.setrlimit(resource.RLIMIT_FSIZE, (_FSIZE_BYTES, _FSIZE_BYTES))
    except (ValueError, OSError):
        pass


_JAIL_MODE = os.environ.get("EKLAVYA_SANDBOX_JAIL", "auto").strip().lower()  # auto | off


def _bwrap_argv(inner: list[str], workdir: str) -> list[str]:
    """Wrap `inner` in a bubblewrap jail: a read-only view of the system + Python,
    ONLY `workdir` writable, no network, and the home dir / .env / codebase simply
    absent from the mount namespace."""
    ro: list[str] = ["--ro-bind-try", "/etc/ld.so.cache", "/etc/ld.so.cache"]
    # System dirs — LITERAL paths (do NOT realpath: on usr-merged systems realpath
    # collapses /bin -> /usr/bin and produces broken nested binds). Deliberately NO
    # /etc or /opt — those hold /etc/eklavya.env and the DB/codebase, which must stay
    # invisible to jailed learner code.
    system = ["/usr", "/bin", "/sbin", "/lib", "/lib64", "/lib32", "/libx32"]
    # Python: the venv + interpreter install, incl. the uv parent dir that holds the
    # short-name symlink dir (e.g. cpython-3.12 -> cpython-3.12.14). Guarded so we
    # never bind a broad root or the app/home dir (which would re-expose the DB/.env).
    _ROOTS = {"/", "/usr", "/bin", "/sbin", "/lib", "/lib64", "/etc", "/opt", "/var", "/home", "/root", "/tmp"}
    py: list[str] = []
    for p in (sys.prefix, sys.base_prefix, os.path.dirname(sys.base_prefix),
              os.path.dirname(os.path.realpath(sys.executable))):
        rp = os.path.realpath(p) if p else ""
        if rp and rp not in _ROOTS and rp.count("/") >= 3 and os.path.isdir(rp):
            py.append(rp)
    py.sort(key=len)  # parents before children so the nesting skip below works
    bound: list[str] = []
    for src in system + py:
        if not os.path.exists(src):
            continue
        if any(src == b or src.startswith(b.rstrip("/") + "/") for b in bound):
            continue  # already covered by a bound parent — avoid broken nested binds
        bound.append(src)
        ro += ["--ro-bind", src, src]
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
    jailed = _JAIL_MODE != "off" and _jail_ok()
    if _JAIL_MODE != "off" and not jailed:
        # Fail CLOSED in a deployed / multi-user context: never execute untrusted code without
        # the filesystem+network jail (that would expose /etc/eklavya.env, every user's DB, and
        # the network). Local single-user dev keeps the process-isolation fallback below.
        from . import config
        if getattr(config, "DEPLOYED", False):
            shutil.rmtree(workdir, ignore_errors=True)
            return RunResult(
                False, "",
                "Sandbox unavailable: the code jail (bubblewrap) is not functional on this host, "
                "so running untrusted code was refused. Ask the operator to install/enable bwrap.",
                -1, 0.0,
            )
    cmd = _bwrap_argv(inner, workdir) if jailed else inner
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


def _test_harness(code: str, tests: str, token: str) -> str:
    """Build the grading harness. The learner's `code` is exec'd in a controlled namespace
    with SystemExit swallowed — so it can neither skip the tests nor exit early to fake a
    pass — then `tests` run in that same namespace (ANY exception → nonzero exit), and only
    then do WE emit `token`. `code`/`tests`/`token` are embedded via repr() (safe literals)."""
    return (
        "import sys as _s\n"
        "_ns = {}\n"
        "try:\n"
        "    exec(compile(" + repr(code) + ", 'solution', 'exec'), _ns)\n"
        "except SystemExit:\n"
        "    pass\n"
        "except BaseException as _e:\n"
        "    _s.stderr.write('error while loading your code: %r\\n' % (_e,)); _s.exit(1)\n"
        "try:\n"
        "    exec(compile(" + repr(tests) + ", 'tests', 'exec'), _ns)\n"
        "except SystemExit:\n"
        "    _s.stderr.write('the tests did not run to completion\\n'); _s.exit(1)\n"
        "except BaseException as _e:\n"
        "    _s.stderr.write('a test failed: %r\\n' % (_e,)); _s.exit(1)\n"
        "_s.stdout.write(" + repr(token) + ")\n"
    )


def run_tests(code: str, tests: str, timeout: float = 8.0) -> RunResult:
    """Run learner `code`, then `tests` (which use `assert`), and pass ONLY when the tests
    actually run to completion without raising — proven by a per-run RANDOM token our harness
    emits afterwards, which the submission cannot see or guess.

    This closes the old "print the fixed success marker and sys.exit(0) before the tests run"
    spoof: the learner code is exec'd with SystemExit swallowed (it can't skip the tests) and
    the token is random per call (it can't be printed by the submission). A learner using
    CPython frame introspection / os._exit is a far higher bar; the frozen IRT benchmark
    remains the independent credibility backstop.
    """
    token = secrets.token_hex(16)
    result = run_python(_test_harness(code, tests, token), timeout=timeout)
    passed = result.ok and token in result.stdout
    clean_stdout = result.stdout.replace(token, "")
    return RunResult(passed, clean_stdout, result.stderr, result.exit_code, result.seconds)
