"""Tiny in-process, dependency-free rate limiter (token bucket).

Per-key buckets keyed by strings like ``"run:<user>"`` or ``"signup:<ip>"``. State resets on
restart and is per-process — sufficient for this single-worker deployment (the login throttle
in ``auth.py`` uses the same reasoning). Guards expensive endpoints (sandbox runs, LLM streams,
signups) against a single account/IP hammering them.
"""

from __future__ import annotations

import threading
import time

# key -> (tokens, last_refill_monotonic)
_buckets: dict[str, tuple[float, float]] = {}
_lock = threading.Lock()


def allow(key: str, rate: int, per: float = 60.0, burst: int | None = None) -> bool:
    """Consume one token for ``key``; return ``False`` if the bucket is empty.

    ``rate`` tokens refill per ``per`` seconds, up to ``burst`` (defaults to ``rate``). So
    ``allow(k, rate=30, per=60, burst=10)`` = 30/min sustained, bursts of up to 10.
    """
    cap = float(burst if burst is not None else rate)
    now = time.monotonic()
    with _lock:
        tokens, last = _buckets.get(key, (cap, now))
        tokens = min(cap, tokens + (now - last) * (rate / per))
        if tokens < 1.0:
            _buckets[key] = (tokens, now)
            ok = False
        else:
            _buckets[key] = (tokens - 1.0, now)
            ok = True
        # Opportunistic prune so the dict can't grow unbounded on a long-lived process.
        if len(_buckets) > 4096:
            for k, (_tk, ts) in list(_buckets.items()):
                if now - ts > per * 4:
                    _buckets.pop(k, None)
        return ok
