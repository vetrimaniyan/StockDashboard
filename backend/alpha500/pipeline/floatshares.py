"""Free-float share counts, for market-capitalisation ranking (open item B-3).

The SRS left the market-cap source undecided: NSE publishes free-float caps but
not on a daily file. This resolves it by storing the *share count* rather than
the capitalisation, so market cap is ``close x float_shares`` and stays correct
every session without refetching. Share counts move on buybacks, issues and
similar events — occasionally, not daily.

Free float rather than total shares is deliberate: the NIFTY 500 is a
free-float market-cap weighted index, so free-float capitalisation is the basis
NSE itself ranks its constituents by.
"""

from __future__ import annotations

from datetime import date
from typing import Callable, Protocol

import duckdb

from alpha500.config import settings
from alpha500.providers.models import Instrument


class _FloatShareSource(Protocol):
    def get_float_shares(self, instrument: Instrument) -> int | None: ...


def sync_float_shares(
    conn: duckdb.DuckDBPyConnection,
    provider: _FloatShareSource,
    limit: int | None = None,
    force: bool = False,
    progress: Callable[[str, int, int], None] | None = None,
) -> tuple[int, list[str]]:
    """Fetch and store free-float share counts. Returns (updated, failures).

    Symbols that already carry a count are skipped unless ``force``, because
    the figure changes rarely and each fetch is a slow third-party call.
    """
    say = progress or (lambda _s, _i, _n: None)

    rows = conn.execute(
        """
        SELECT i.instrument_token, i.tradingsymbol, i.float_shares
          FROM instruments i
          JOIN index_membership m ON m.instrument_token = i.instrument_token
         WHERE m.index_name = ? AND m.valid_to IS NULL
         ORDER BY i.tradingsymbol
        """,
        [settings.index_name],
    ).fetchall()
    if limit:
        rows = rows[:limit]

    today = date.today()
    updated = 0
    failures: list[str] = []

    for position, (token, symbol, existing) in enumerate(rows, start=1):
        say(str(symbol), position, len(rows))
        if existing and not force:
            continue
        # AR-1: the SDK lives behind the provider; this module never imports it.
        shares = provider.get_float_shares(
            Instrument(instrument_token=int(token), tradingsymbol=str(symbol))
        )
        if not shares:
            failures.append(str(symbol))
            continue

        conn.execute(
            "UPDATE instruments SET float_shares = ?, float_shares_as_of = ? "
            "WHERE instrument_token = ?",
            [int(shares), today, token],
        )
        updated += 1

    return updated, failures
