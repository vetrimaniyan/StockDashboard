"""Backups for both stores.

The two databases are separate precisely so a full price rebuild cannot put
the watchlist or the journal at risk. ``app.sqlite`` is the irreplaceable half:
its weight profiles, saved screens, journal and watchlist exist nowhere else.

``alpha500.duckdb`` was left unbacked on the grounds that it is rebuildable
from a backfill. That is true and it is not the whole story. Rebuilding it
costs hours of vendor requests and depends on those vendors still serving the
same depth — Yahoo's index history reaches 2007 today and no contract says it
will tomorrow. One table is not rebuildable at all: ``quarantined_rows``
records validation events tied to the run that found them, and a rebuilt store
would simply not contain them. So it is snapshotted too, with a shorter
retention because it is a thousand times the size and its loss is expensive
rather than fatal.

``VACUUM INTO`` rather than a file copy. SQLite holds a write-ahead log and a
page cache, so copying the file byte-wise while the API has it open can
capture a torn write — a backup that restores to a corrupt database, which is
worse than none because it is silently trusted. ``VACUUM INTO`` takes a read
lock, writes a consistent and compacted snapshot, and is safe against a live
reader or writer.

Backups are deduplicated by content: an unchanged store produces no new file,
so a year of quiet days leaves one snapshot rather than 365 identical ones.
"""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from alpha500.config import settings


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _verify(path: Path) -> tuple[bool, str]:
    """Open the snapshot and check SQLite considers it sound."""
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            result = conn.execute("PRAGMA integrity_check").fetchone()
            tables = conn.execute(
                "SELECT count(*) FROM sqlite_master WHERE type = 'table'"
            ).fetchone()[0]
        finally:
            conn.close()
    except sqlite3.Error as exc:  # noqa: BLE001 - reported, not raised
        return False, f"unreadable: {exc}"
    if not result or result[0] != "ok":
        return False, f"integrity_check said {result[0] if result else 'nothing'}"
    if tables == 0:
        return False, "snapshot contains no tables"
    return True, f"ok, {tables} tables"


def backup_app_db(
    destination: Path | None = None, keep: int | None = None
) -> dict[str, object]:
    """Snapshot ``app.sqlite``, verify it, and prune old copies.

    Returns a summary rather than raising: a failed backup must be visible in
    the pipeline log without taking the night's run down with it. A missing
    backup is bad; a pipeline that aborts before computing metrics is worse.
    """
    source = settings.data_dir / "app.sqlite"
    target_dir = Path(destination) if destination else settings.backup_dir
    keep = settings.backup_keep if keep is None else keep

    if not source.exists():
        return {"status": "SKIPPED", "reason": f"no store at {source}", "path": None}

    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    # VACUUM INTO refuses to overwrite, so a second run inside the same second
    # would fail outright — which a manual backup straight after the nightly
    # one does. The sequence is always present and always two digits: with it
    # optional, "app-...-01.sqlite" sorts BEFORE "app-....sqlite" ('-' < '.'),
    # so the newest snapshot would not be last and both the dedupe comparison
    # and the rotation would act on the wrong file.
    sequence = 0
    target = target_dir / f"app-{stamp}-{sequence:02d}.sqlite"
    while target.exists():
        sequence += 1
        target = target_dir / f"app-{stamp}-{sequence:02d}.sqlite"

    conn = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        # Parameterised VACUUM INTO is not supported, so the path is quoted by
        # doubling single quotes. It is ours, not user input, but a path with
        # an apostrophe would otherwise produce a confusing syntax error.
        escaped = str(target).replace("'", "''")
        conn.execute(f"VACUUM INTO '{escaped}'")
    except sqlite3.Error as exc:  # noqa: BLE001
        return {"status": "FAILED", "reason": str(exc), "path": None}
    finally:
        conn.close()

    sound, detail = _verify(target)
    if not sound:
        target.unlink(missing_ok=True)
        return {"status": "FAILED", "reason": detail, "path": None}

    existing = sorted(target_dir.glob("app-*.sqlite"))
    # Deduplicate against the most recent previous snapshot.
    previous = [p for p in existing if p != target]
    if previous and _digest(previous[-1]) == _digest(target):
        target.unlink()
        return {
            "status": "UNCHANGED",
            "reason": f"identical to {previous[-1].name}",
            "path": str(previous[-1]),
            "kept": len(previous),
        }

    pruned = 0
    snapshots = sorted(target_dir.glob("app-*.sqlite"))
    for stale in snapshots[:-keep] if keep > 0 else []:
        stale.unlink(missing_ok=True)
        pruned += 1

    return {
        "status": "OK",
        "reason": detail,
        "path": str(target),
        "bytes": target.stat().st_size,
        "kept": len(sorted(target_dir.glob("app-*.sqlite"))),
        "pruned": pruned,
    }


def _verify_duckdb(path: Path) -> tuple[bool, str]:
    """Open the snapshot read-only and check the tables that matter are there."""
    import duckdb

    try:
        conn = duckdb.connect(str(path), read_only=True)
        try:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT table_name FROM information_schema.tables"
                ).fetchall()
            }
            rows = conn.execute("SELECT count(*) FROM ohlcv_daily").fetchone()[0]
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        return False, f"unreadable: {exc}"

    missing = {"ohlcv_daily", "instruments", "metrics_daily"} - tables
    if missing:
        return False, f"snapshot is missing {sorted(missing)}"
    if not rows:
        return False, "snapshot holds no price rows"
    return True, f"ok, {len(tables)} tables, {rows:,} price rows"


def backup_analytical_db(
    conn: object | None = None,
    destination: Path | None = None,
    keep: int | None = None,
) -> dict[str, object]:
    """Snapshot ``alpha500.duckdb``, verify it, and prune old copies.

    ``COPY FROM DATABASE`` rather than a file copy, for the reason the app
    store uses ``VACUUM INTO``: DuckDB buffers writes and keeps a write-ahead
    log, so copying the file byte-wise while a writer holds it can capture a
    torn state — a backup that restores to a broken database is worse than no
    backup, because it is trusted.

    Pass ``conn`` when the caller already holds the store. DuckDB permits one
    writer per file across the whole machine, so the nightly run - which holds
    it read-write for the entire pipeline - cannot have this function open a
    second connection of its own. Standalone callers omit it and get their own,
    which is also why `alpha500 backup --analytical` needs the API stopped.

    Like the app-store backup, this reports rather than raises. A pipeline that
    aborts before computing metrics is worse than a missing snapshot.
    """
    import duckdb

    source = settings.analytical_db
    target_dir = Path(destination) if destination else settings.backup_dir
    keep = settings.analytical_backup_keep if keep is None else keep

    if not source.exists():
        return {"status": "SKIPPED", "reason": f"no store at {source}", "path": None}

    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    sequence = 0
    target = target_dir / f"alpha500-{stamp}-{sequence:02d}.duckdb"
    while target.exists():
        sequence += 1
        target = target_dir / f"alpha500-{stamp}-{sequence:02d}.duckdb"

    # The snapshot lands on the same disk the live store sits on, so filling it
    # to take a backup would be its own outage.
    free = shutil.disk_usage(target_dir).free
    needed = source.stat().st_size
    if free < needed * 2:
        return {
            "status": "FAILED",
            "reason": f"needs ~{needed / 1e9:.1f} GB, {free / 1e9:.1f} GB free",
            "path": None,
        }

    owned = None
    try:
        if conn is None:
            owned = duckdb.connect(str(source))
            handle = owned
        else:
            handle = conn
        escaped = str(target).replace("'", "''")
        # DuckDB names an attached database after its file, so the source alias
        # is "alpha500" only by coincidence of the filename. Ask for it rather
        # than assume it, or renaming the store breaks backups silently and
        # only the restore finds out.
        current = handle.execute("SELECT current_database()").fetchone()[0]
        handle.execute(f"ATTACH '{escaped}' AS snapshot")
        try:
            handle.execute(f'COPY FROM DATABASE "{current}" TO snapshot')
        finally:
            handle.execute("DETACH snapshot")
    except Exception as exc:  # noqa: BLE001
        target.unlink(missing_ok=True)
        return {"status": "FAILED", "reason": str(exc), "path": None}
    finally:
        if owned is not None:
            owned.close()

    sound, detail = _verify_duckdb(target)
    if not sound:
        target.unlink(missing_ok=True)
        return {"status": "FAILED", "reason": detail, "path": None}

    # No content dedupe here. The app store is small enough to hash every
    # night; hashing a gigabyte to discover it changed - which it does every
    # session - would cost more than the copy it might save.
    pruned = 0
    for stale in sorted(target_dir.glob("alpha500-*.duckdb"))[:-keep] if keep > 0 else []:
        stale.unlink(missing_ok=True)
        pruned += 1

    return {
        "status": "OK",
        "reason": detail,
        "path": str(target),
        "bytes": target.stat().st_size,
        "kept": len(sorted(target_dir.glob("alpha500-*.duckdb"))),
        "pruned": pruned,
    }
