"""Backups for the user-data store (``app.sqlite``).

The two databases are separate precisely so a full price rebuild cannot put
the watchlist or the journal at risk. That separation only means something if
the irreplaceable half is actually copied somewhere: ``alpha500.duckdb`` is
rebuildable from a backfill, ``app.sqlite`` is not. Its weight profiles, saved
screens, journal and watchlist exist nowhere else.

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
