"""Tests for the app.sqlite backup (user store, not the rebuildable one).

The point of these is that a backup which cannot be restored is worse than no
backup, because it is silently trusted. So every test here checks the snapshot
is actually readable and complete, not merely that a file appeared.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from alpha500.db.backup import backup_app_db


@pytest.fixture
def store(tmp_path: Path, monkeypatch):
    """A small app.sqlite with content worth losing."""
    from alpha500.config import settings

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db = data_dir / "app.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE watchlist (symbol TEXT PRIMARY KEY, note TEXT)")
    conn.execute("CREATE TABLE journal (id INTEGER PRIMARY KEY, entry TEXT)")
    conn.executemany(
        "INSERT INTO watchlist VALUES (?,?)",
        [("RELIANCE", "waiting on the 50% level"), ("INFY", "held since June")],
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(settings, "data_dir", data_dir, raising=False)
    monkeypatch.setattr(settings, "backup_dir", tmp_path / "backups", raising=False)
    monkeypatch.setattr(settings, "backup_keep", 3, raising=False)
    return db


def snapshots(tmp_path: Path) -> list[Path]:
    return sorted((tmp_path / "backups").glob("app-*.sqlite"))


def test_backup_is_restorable_not_merely_present(store, tmp_path):
    """The file existing proves nothing; the rows surviving proves something."""
    result = backup_app_db()
    assert result["status"] == "OK"

    copies = snapshots(tmp_path)
    assert len(copies) == 1

    conn = sqlite3.connect(f"file:{copies[0]}?mode=ro", uri=True)
    rows = dict(conn.execute("SELECT symbol, note FROM watchlist").fetchall())
    conn.close()
    assert rows == {
        "RELIANCE": "waiting on the 50% level",
        "INFY": "held since June",
    }


def test_a_live_reader_does_not_block_or_corrupt_the_snapshot(store, tmp_path):
    """The API holds this database open all day, so this is the normal case.

    A byte-wise file copy here can capture a torn write; VACUUM INTO takes a
    read lock and produces a consistent page image.
    """
    holder = sqlite3.connect(store)
    holder.execute("SELECT count(*) FROM watchlist").fetchone()
    try:
        result = backup_app_db()
    finally:
        holder.close()

    assert result["status"] == "OK"
    conn = sqlite3.connect(f"file:{snapshots(tmp_path)[0]}?mode=ro", uri=True)
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert conn.execute("SELECT count(*) FROM watchlist").fetchone()[0] == 2
    conn.close()


def test_an_unchanged_store_does_not_accumulate_copies(store, tmp_path):
    """A year of quiet days should leave one snapshot, not 365 identical ones."""
    first = backup_app_db()
    second = backup_app_db()
    assert first["status"] == "OK"
    assert second["status"] == "UNCHANGED"
    assert len(snapshots(tmp_path)) == 1


def test_a_changed_store_produces_a_new_snapshot(store, tmp_path):
    backup_app_db()
    conn = sqlite3.connect(store)
    conn.execute("INSERT INTO watchlist VALUES ('TCS', 'new idea')")
    conn.commit()
    conn.close()

    assert backup_app_db()["status"] == "OK"
    copies = snapshots(tmp_path)
    assert len(copies) == 2

    newest = sqlite3.connect(f"file:{copies[-1]}?mode=ro", uri=True)
    assert newest.execute("SELECT count(*) FROM watchlist").fetchone()[0] == 3
    newest.close()


def test_rotation_keeps_the_newest_and_drops_the_oldest(store, tmp_path):
    """keep=3, so a fourth distinct snapshot evicts the first."""
    for i in range(4):
        conn = sqlite3.connect(store)
        conn.execute("INSERT INTO watchlist VALUES (?,?)", (f"SYM{i}", f"note {i}"))
        conn.commit()
        conn.close()
        assert backup_app_db()["status"] == "OK"

    copies = snapshots(tmp_path)
    assert len(copies) == 3, "rotation did not prune"
    # The survivor must be the most complete one, not an arbitrary three.
    newest = sqlite3.connect(f"file:{copies[-1]}?mode=ro", uri=True)
    assert newest.execute("SELECT count(*) FROM watchlist").fetchone()[0] == 6
    newest.close()


def test_a_missing_store_is_skipped_not_failed(store, tmp_path):
    """Nothing to back up is not an error; it is the first-run state."""
    store.unlink()
    result = backup_app_db()
    assert result["status"] == "SKIPPED"
    assert not snapshots(tmp_path)


def test_destination_can_point_off_the_repo(store, tmp_path):
    """Off-machine backup is one setting, not a code change (backup_dir)."""
    elsewhere = tmp_path / "onedrive" / "alpha500"
    result = backup_app_db(destination=elsewhere)
    assert result["status"] == "OK"
    assert list(elsewhere.glob("app-*.sqlite"))
