"""Defensive migration: an OPTIONAL step failing must NOT lock a login out.

init_db runs on every launch/login. If a failing optional step (benchmark seed,
subject-framework rebuild, pillar-order backfill) threw, every deployed login would
break. These tests force each optional step to raise and assert init_db still
completes, stamps the schema version, and leaves a usable DB.
"""

import pytest

from eklavya import tools
from eklavya.db import connect, init_db, schema_version, store


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    home = tmp_path / "eklavya"
    (home / "workspace").mkdir(parents=True)
    monkeypatch.setenv("EKLAVYA_HOME", str(home))
    monkeypatch.setenv("EKLAVYA_PROFILE", str(home / "workspace" / "profile.md"))
    monkeypatch.setenv("EKLAVYA_DATA_ROOT", str(tmp_path / "data"))
    yield


def test_benchmark_seed_failure_does_not_lock_login(monkeypatch):
    from eklavya import benchmark

    def boom(conn):
        raise RuntimeError("seed exploded")

    monkeypatch.setattr(benchmark, "seed_items", boom)
    # init_db must NOT raise even though the optional benchmark seed blows up.
    init_db()
    assert schema_version() == store.SCHEMA_VERSION
    # The DB is usable — core tables are present and writable.
    tools.add_pillar("Python")
    conn = connect()
    try:
        assert conn.execute("SELECT COUNT(*) AS c FROM pillars").fetchone()["c"] == 1
    finally:
        conn.close()


def test_subject_framework_failure_serves_degraded(monkeypatch):
    def boom(conn):
        raise RuntimeError("framework rebuild exploded")

    monkeypatch.setattr(store, "_migrate_subject_framework", boom)
    init_db()  # must not raise
    assert schema_version() == store.SCHEMA_VERSION
    # Still usable despite the degraded framework migration.
    tools.add_pillar("SQL")
    conn = connect()
    try:
        assert conn.execute("SELECT COUNT(*) AS c FROM pillars").fetchone()["c"] == 1
    finally:
        conn.close()


def test_pillar_order_backfill_failure_serves_degraded(monkeypatch):
    def boom(conn):
        raise RuntimeError("pillar-order backfill exploded")

    monkeypatch.setattr(store, "_migrate_pillar_order", boom)
    init_db()  # must not raise
    assert schema_version() == store.SCHEMA_VERSION
