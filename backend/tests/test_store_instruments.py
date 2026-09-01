"""Tests for ``upsert_instruments`` — the universe sync's write path.

This function had no coverage until 2026-08-31, which is why a positional
INSERT with a hardcoded placeholder count survived three schema changes and
then failed the nightly run outright:

    Binder Error: table _inst_stage has 18 columns but 15 values were supplied

The whole pipeline aborts behind ``sync_instruments``, so a fault here freezes
the dashboard at the previous session. The tests below pin the two properties
that were actually violated: independence from the table's width, and leaving
columns this sync does not own alone.
"""

from __future__ import annotations

from datetime import date

import duckdb
import pytest

from alpha500.db import store
from alpha500.providers.models import Instrument

D1 = date(2026, 8, 27)
D2 = date(2026, 8, 28)


def make(token: int, symbol: str, name: str, **overrides: object) -> Instrument:
    fields = {
        "instrument_token": token,
        "exchange_token": token,
        "tradingsymbol": symbol,
        "name": name,
        "isin": f"INE{token:09d}",
        "series": "EQ",
        "exchange": "NSE",
        "industry": "Information Technology",
        "sector": "IT",
        "basic_industry": "Software",
        "lot_size": 1,
        "tick_size": 0.05,
    }
    fields.update(overrides)
    return Instrument(**fields)  # type: ignore[arg-type]


def rows(connection: duckdb.DuckDBPyConnection) -> dict[int, tuple]:
    return {
        r[0]: r
        for r in connection.execute(
            """
            SELECT instrument_token, tradingsymbol, name, series, industry,
                   is_active, first_seen_date, last_seen_date,
                   float_shares, float_shares_as_of, index_tier
              FROM instruments ORDER BY instrument_token
            """
        ).fetchall()
    }


# --- inserting -----------------------------------------------------------


def test_first_sync_inserts_every_constituent(conn):
    written = store.upsert_instruments(conn, [make(1, "AAA", "Alpha Ltd"),
                                              make(2, "BBB", "Beta Ltd")], D1)
    assert written == 2
    stored = rows(conn)
    assert set(stored) == {1, 2}
    assert stored[1][1:5] == ("AAA", "Alpha Ltd", "EQ", "Information Technology")
    assert stored[1][5] is True
    # Both dates are the session the symbol was first seen.
    assert stored[1][6] == D1 and stored[1][7] == D1


def test_empty_sync_writes_nothing(conn):
    """A provider returning nothing must not blank the universe."""
    store.upsert_instruments(conn, [make(1, "AAA", "Alpha Ltd")], D1)
    assert store.upsert_instruments(conn, [], D2) == 0
    assert set(rows(conn)) == {1}


# --- updating ------------------------------------------------------------


def test_resync_updates_existing_and_inserts_new(conn):
    store.upsert_instruments(conn, [make(1, "AAA", "Alpha Ltd"),
                                    make(2, "BBB", "Beta Ltd")], D1)
    store.upsert_instruments(conn, [make(1, "AAA", "Alpha Corporation"),
                                    make(3, "CCC", "Gamma Ltd")], D2)

    stored = rows(conn)
    assert set(stored) == {1, 2, 3}
    # Renamed and re-seen.
    assert stored[1][2] == "Alpha Corporation"
    assert stored[1][6] == D1, "first_seen_date must not move on a re-sync"
    assert stored[1][7] == D2
    # Absent from this sync, so untouched.
    assert stored[2][7] == D1
    # New arrival.
    assert stored[3][6] == D2 and stored[3][7] == D2


def test_upsert_is_idempotent(conn):
    """AR-3: re-running a sync for a session already processed adds no rows."""
    batch = [make(1, "AAA", "Alpha Ltd"), make(2, "BBB", "Beta Ltd")]
    store.upsert_instruments(conn, batch, D1)
    before = rows(conn)
    store.upsert_instruments(conn, batch, D1)
    assert rows(conn) == before


def test_null_fields_do_not_overwrite_known_values(conn):
    """COALESCE in the UPDATE: a sparse feed must not erase what is stored."""
    store.upsert_instruments(conn, [make(1, "AAA", "Alpha Ltd")], D1)
    store.upsert_instruments(
        conn, [make(1, "AAA", None, isin=None, industry=None)], D2
    )
    stored = rows(conn)[1]
    assert stored[2] == "Alpha Ltd"
    assert stored[4] == "Information Technology"


# --- the regression ------------------------------------------------------


def test_survives_a_column_added_to_instruments(conn):
    """The 2026-08-28 outage, reproduced.

    ``upsert_instruments`` builds its staging table from ``instruments``, so
    the stage is always as wide as the table. When the INSERT beneath it was
    positional with a fixed placeholder count, any added column broke it —
    which is what float_shares, float_shares_as_of and index_tier did.

    Adding one here fails the old implementation and must not fail this one.
    """
    conn.execute("ALTER TABLE instruments ADD COLUMN listing_group VARCHAR")
    written = store.upsert_instruments(conn, [make(1, "AAA", "Alpha Ltd")], D1)
    assert written == 1
    # Re-sync too: the tail INSERT and the UPDATE take different paths.
    store.upsert_instruments(conn, [make(1, "AAA", "Alpha Ltd"),
                                    make(2, "BBB", "Beta Ltd")], D2)
    assert set(rows(conn)) == {1, 2}


def test_columns_owned_by_other_commands_survive_a_sync(conn):
    """float_shares and index_tier belong to `marketcap` and `indices`.

    The universe sync knows nothing about them, so it must leave them alone.
    Naming them in the stage load would null them out every night — a
    quieter failure than the binder error, and a worse one: the NIFTY 500 tab
    ranks on float-share market cap.
    """
    store.upsert_instruments(conn, [make(1, "AAA", "Alpha Ltd"),
                                    make(2, "BBB", "Beta Ltd")], D1)
    conn.execute(
        "UPDATE instruments SET float_shares = 123456, "
        "float_shares_as_of = ?, index_tier = 'NIFTY50' WHERE instrument_token = 1",
        [D1],
    )

    store.upsert_instruments(conn, [make(1, "AAA", "Alpha Corporation")], D2)

    stored = rows(conn)[1]
    assert stored[2] == "Alpha Corporation", "the sync's own column should update"
    assert stored[8] == 123456, "float_shares was clobbered by the sync"
    assert stored[9] == D1
    assert stored[10] == "NIFTY50", "index_tier was clobbered by the sync"


def test_a_new_symbol_starts_with_no_market_cap_or_tier(conn):
    """Columns the sync does not populate default to NULL, never to zero.

    A zero free float would sort a new constituent to the bottom of the
    NIFTY 500 tab as though it were tiny, rather than as unknown.
    """
    store.upsert_instruments(conn, [make(9, "NEW", "Newly Listed Ltd")], D2)
    stored = rows(conn)[9]
    assert stored[8] is None and stored[9] is None and stored[10] is None


def test_symbol_rename_keeps_the_same_row(conn):
    """D-3: the token is derived from ISIN, so a rename must not orphan history."""
    store.upsert_instruments(conn, [make(1, "OLDNAME", "Alpha Ltd")], D1)
    store.upsert_instruments(conn, [make(1, "NEWNAME", "Alpha Ltd")], D2)
    stored = rows(conn)
    assert set(stored) == {1}
    assert stored[1][1] == "NEWNAME"
    assert stored[1][6] == D1


@pytest.mark.parametrize("count", [1, 50, 500])
def test_bulk_sync_writes_every_row(conn, count):
    """The real universe is 500; the staging path must not truncate."""
    batch = [make(i, f"SYM{i}", f"Company {i}") for i in range(1, count + 1)]
    assert store.upsert_instruments(conn, batch, D1) == count
    assert len(rows(conn)) == count
