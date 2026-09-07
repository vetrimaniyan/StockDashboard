"""Snapshots of the analytical store.

The store was left unbacked on the grounds that it is rebuildable. It is, at
the cost of hours of vendor requests and on the assumption those vendors still
serve the same depth — and `quarantined_rows` is not rebuildable at all, since
it records validation events tied to the run that found them.

What these tests defend is the part that makes a backup worth having: that a
snapshot which cannot be opened, or which is missing tables, is deleted and
reported rather than left on disk to be trusted later.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from alpha500.db.backup import backup_analytical_db
from alpha500.config import settings


@pytest.fixture
def store(tmp_path: Path, monkeypatch):
    """A small analytical store with the tables the verifier insists on."""
    path = tmp_path / "alpha500.duckdb"
    conn = duckdb.connect(str(path))
    conn.execute("CREATE TABLE instruments (instrument_token BIGINT, tradingsymbol VARCHAR)")
    conn.execute("CREATE TABLE ohlcv_daily (instrument_token BIGINT, trade_date DATE, close DOUBLE)")
    conn.execute("CREATE TABLE metrics_daily (instrument_token BIGINT, trade_date DATE)")
    conn.execute("CREATE TABLE quarantined_rows (instrument_token BIGINT, detail VARCHAR)")
    conn.execute("INSERT INTO instruments VALUES (1, 'RELIANCE'), (2, 'INFY')")
    conn.execute("INSERT INTO ohlcv_daily VALUES (1, DATE '2026-09-07', 100.0)")
    conn.execute("INSERT INTO metrics_daily VALUES (1, DATE '2026-09-07')")
    conn.execute("INSERT INTO quarantined_rows VALUES (1, 'V5 -62.62%')")
    conn.close()
    monkeypatch.setattr(type(settings), "analytical_db", property(lambda _self: path))
    return path


def test_a_snapshot_is_taken_verified_and_openable(store, tmp_path):
    out = backup_analytical_db(destination=tmp_path / "backups", keep=3)

    assert out["status"] == "OK", out
    snapshot = Path(str(out["path"]))
    assert snapshot.exists()

    conn = duckdb.connect(str(snapshot), read_only=True)
    try:
        assert conn.execute("SELECT count(*) FROM instruments").fetchone()[0] == 2
        # The table a rebuild could never reproduce.
        assert conn.execute(
            "SELECT detail FROM quarantined_rows"
        ).fetchone()[0] == "V5 -62.62%"
    finally:
        conn.close()


def test_the_snapshot_is_a_copy_not_a_link(store, tmp_path):
    """Later writes to the live store must not appear in a taken snapshot."""
    out = backup_analytical_db(destination=tmp_path / "backups", keep=3)
    conn = duckdb.connect(str(store))
    conn.execute("INSERT INTO instruments VALUES (3, 'TCS')")
    conn.close()

    snap = duckdb.connect(str(out["path"]), read_only=True)
    try:
        assert snap.execute("SELECT count(*) FROM instruments").fetchone()[0] == 2
    finally:
        snap.close()


def test_a_missing_store_is_skipped_not_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(
        type(settings), "analytical_db",
        property(lambda _self: tmp_path / "absent.duckdb"),
    )
    out = backup_analytical_db(destination=tmp_path / "backups")

    assert out["status"] == "SKIPPED"
    assert out["path"] is None


def test_a_snapshot_missing_its_tables_is_deleted_not_kept(store, tmp_path, monkeypatch):
    """A backup that restores to something unusable is worse than none, because
    it is trusted. It must not survive verification."""
    import alpha500.db.backup as backup

    monkeypatch.setattr(
        backup, "_verify_duckdb", lambda _p: (False, "snapshot is missing ['ohlcv_daily']")
    )
    target_dir = tmp_path / "backups"
    out = backup_analytical_db(destination=target_dir, keep=3)

    assert out["status"] == "FAILED"
    assert "missing" in str(out["reason"])
    assert list(target_dir.glob("alpha500-*.duckdb")) == [], "the bad snapshot was kept"


def test_retention_prunes_oldest_first(store, tmp_path):
    target_dir = tmp_path / "backups"
    paths = [backup_analytical_db(destination=target_dir, keep=2)["path"] for _ in range(3)]

    remaining = sorted(p.name for p in target_dir.glob("alpha500-*.duckdb"))
    assert len(remaining) == 2
    assert Path(str(paths[0])).name not in remaining, "the oldest must go first"
    assert Path(str(paths[-1])).name in remaining, "the newest must stay"


def test_it_refuses_rather_than_filling_the_disk(store, tmp_path, monkeypatch):
    """The snapshot lands on the same disk as the live store. Running that disk
    out of space to back it up would be its own outage."""
    import alpha500.db.backup as backup

    class _Tiny:
        free = 1

    monkeypatch.setattr(backup.shutil, "disk_usage", lambda _p: _Tiny)
    out = backup_analytical_db(destination=tmp_path / "backups", keep=3)

    assert out["status"] == "FAILED"
    assert "free" in str(out["reason"])
