"""Shared test isolation.

The account model binds the *current* account's home into a ``ContextVar``
(``config._current_home``) — the CLI callback does it via ``_bind_account`` and the web
middleware does it per request. Tests that drive those paths (``CliRunner().invoke`` /
``TestClient``) run in-process, so a binding set during one test would otherwise linger in
the interpreter's context and leak into unrelated later tests — e.g. ``test_migrate``, which
expects NO account bound so ``paths()`` falls back to its ``EKLAVYA_HOME`` override.

This autouse fixture snapshots the contextvars before each test and restores them after, so
every test starts from a clean, unbound context regardless of what ran before it.
"""

import pytest

from eklavya import config


@pytest.fixture(autouse=True)
def _reset_bound_context():
    home_token = config._current_home.set(None)
    thread_token = config._current_thread.set(None)
    # Rate-limit / login-throttle state is module-level and per-process; clear it so a bucket
    # drained by one test (all TestClient requests share one client IP) can't leak into another.
    try:
        from eklavya import ratelimit
        ratelimit._buckets.clear()
    except Exception:
        pass
    try:
        from eklavya import auth
        auth._fails.clear()
    except Exception:
        pass
    try:
        yield
    finally:
        config._current_home.reset(home_token)
        config._current_thread.reset(thread_token)
