"""Process-level connection sharing (DECISIONS.md D-6).

DuckDB permits one read-write process or many read-only ones, and refuses to
mix modes even within a single process. ``serve --with-scheduler`` runs the API
and the nightly pipeline together, so without a shared connection the 18:45 run
fails the first night — silently, in the dark, which is the failure mode
FR-11.2 exists to prevent.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from alpha500 import config
from alpha500.db import connection as dbc


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch):  # type: ignore[no-untyped-def]
    monkeypatch.setattr(config.settings, "data_dir", tmp_path)
    dbc.close_process_connection()
    yield tmp_path
    dbc.close_process_connection()


def test_reader_and_writer_coexist_in_one_process(isolated):
    """The combination that `serve --with-scheduler` depends on.

    Opening these as separate connections raises ConnectionException:
    "Can't open a connection to same database file with a different
    configuration than existing connections".
    """
    dbc.init_databases()

    with dbc.analytical() as reader:
        reader.execute("SELECT count(*) FROM metrics_daily").fetchone()

        # The scheduler's write, while the API's read is still open.
        with dbc.analytical() as writer:
            writer.execute(
                "INSERT INTO trading_calendar VALUES (DATE '2026-08-27', TRUE, NULL)"
            )

        assert reader.execute(
            "SELECT count(*) FROM trading_calendar"
        ).fetchone()[0] == 1


def test_many_concurrent_cursors_are_independent(isolated):
    dbc.init_databases()
    with dbc.analytical() as a, dbc.analytical() as b, dbc.analytical() as c:
        for i, conn in enumerate((a, b, c)):
            assert conn.execute("SELECT ?", [i]).fetchone()[0] == i


def test_read_only_mode_rejects_writes(isolated):
    """A plain `serve` should not be able to mutate the analytical store."""
    dbc.init_databases()
    dbc.close_process_connection()

    dbc.configure_process_connection(read_only=True)
    with dbc.analytical() as conn:
        with pytest.raises(duckdb.Error):
            conn.execute(
                "INSERT INTO trading_calendar VALUES (DATE '2026-08-28', TRUE, NULL)"
            )


def test_configure_rejects_a_mode_change_after_opening(isolated):
    """Silently ignoring the request would leave the caller wrongly reassured."""
    dbc.init_databases()
    with dbc.analytical():
        pass
    with pytest.raises(RuntimeError, match="already open"):
        dbc.configure_process_connection(read_only=True)


def test_init_skips_the_analytical_schema_when_read_only(isolated):
    """`serve` without the scheduler must not need write access to start."""
    dbc.configure_process_connection(read_only=True)
    duckdb.connect(str(config.settings.analytical_db)).close()  # create the file
    dbc.init_databases()  # must not raise
