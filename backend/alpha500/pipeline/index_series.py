"""FR-18.2 — daily series for each tracked index, to the depth obtainable.

Two sources, and the split is permanent rather than a stopgap (B-10):

* Yahoo serves full OHLC for 18 of the 24 tracked indices. Depth runs from
  2007-09-17 (Bank, IT) through 2011 for most, and 2016 for Private Bank.
* The remaining six have no vendor ticker. Their close is already in this
  store, in ``index_valuation_daily``, because the FR-18 valuation sync fetches
  NSE's ``ind_close_all`` for every published index. So the fallback is a
  projection out of our own tables rather than a fetch.

NSE's own historical-index JSON endpoint is bot-blocked and is not an option.

**No index reaches its inception.** Nifty Bank launched in 2003 and the deepest
series available starts in 2007. So ``first_session`` is recorded per index and
FR-18.3 names the peak ``period_high``; ``ath_*`` is not in use. That is
FR-15.2's rule reaching its expected answer rather than being argued around.

Widening ``index_ohlcv_daily`` from one series to many is safe: all five of its
readers — the metric engine, the history materialiser, the screens' regime
banner, the store's upsert and the API's benchmark lookup — filter on
``index_name``, so rows for other indices are invisible to them. That was
checked before the first row was written, because it is the kind of assumption
that is cheap to verify and expensive to be wrong about.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Callable, Protocol, Sequence

import duckdb

from alpha500.db import store
from alpha500.pipeline.index_universe import TRACKED, TrackedIndex
from alpha500.providers.models import Candle, ProviderError

OHLC = "OHLC"
CLOSE = "CLOSE"
CLOSE_SOURCE = "NSE_IND_CLOSE_ALL"


class _IndexCandleSource(Protocol):
    name: str

    def get_index_candles(
        self, index_name: str, start: date, end: date
    ) -> Sequence[Candle]: ...


@dataclass(frozen=True, slots=True)
class IndexSyncResult:
    index_name: str
    rows: int
    basis: str
    source: str
    first_session: date | None
    last_session: date | None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def _record(
    conn: duckdb.DuckDBPyConnection, index: TrackedIndex, basis: str, source: str
) -> tuple[int, date | None, date | None]:
    """Refresh the ``indices`` row from what is actually stored.

    Read back rather than counted from the write: a row that failed to land
    should not be described as present, and the upsert's return value cannot
    tell the difference between a new row and a replaced one.
    """
    span = conn.execute(
        "SELECT min(trade_date), max(trade_date), count(*) FROM index_ohlcv_daily "
        "WHERE index_name = ?",
        [index.name],
    ).fetchone()
    first, last, sessions = span if span else (None, None, 0)
    conn.execute(
        "INSERT OR REPLACE INTO indices "
        "(index_name, category, first_session, last_session, sessions, "
        " ohlc_basis, source, refreshed_at) VALUES (?,?,?,?,?,?,?,?)",
        [
            index.name, index.category, first, last, int(sessions or 0),
            basis, source, datetime.now(timezone.utc),
        ],
    )
    return int(sessions or 0), first, last


def _project_close_only(
    conn: duckdb.DuckDBPyConnection, index: TrackedIndex, start: date, end: date
) -> int:
    """Copy close out of ``index_valuation_daily`` for an index Yahoo lacks.

    open/high/low are left NULL on purpose. Repeating close into them would
    make ``max(High)`` answerable and wrong — a 52-week high computed from
    closes would silently claim to be a high. NULL forces FR-18.3 to consult
    ``ohlc_basis`` instead of quietly producing a number.
    """
    conn.execute(
        """
        INSERT OR REPLACE INTO index_ohlcv_daily
            (index_name, trade_date, open, high, low, close, volume,
             source, ingested_at)
        SELECT index_name, trade_date, NULL, NULL, NULL, close, NULL, ?, ?
          FROM index_valuation_daily
         WHERE index_name = ? AND close IS NOT NULL
           AND trade_date BETWEEN ? AND ?
        """,
        [CLOSE_SOURCE, datetime.now(timezone.utc), index.name, start, end],
    )
    return int(
        conn.execute(
            "SELECT count(*) FROM index_valuation_daily WHERE index_name = ? "
            "AND close IS NOT NULL AND trade_date BETWEEN ? AND ?",
            [index.name, start, end],
        ).fetchone()[0]
    )


def sync_index_series(
    conn: duckdb.DuckDBPyConnection,
    provider: _IndexCandleSource,
    start: date,
    end: date,
    indices: Sequence[TrackedIndex] = TRACKED,
    progress: Callable[[str, int, int], None] | None = None,
) -> list[IndexSyncResult]:
    """Ingest each tracked index over ``start``..``end``.

    One index failing does not stop the rest: the sectoral dashboard is more
    useful with 23 of 24 series than with none, and the failure is returned per
    index so the caller can report it rather than infer it from a row count.
    """
    from alpha500.providers.yahoo import has_index_ticker

    say = progress or (lambda _s, _i, _n: None)
    out: list[IndexSyncResult] = []

    for position, index in enumerate(indices, start=1):
        say(index.name, position, len(indices))

        if has_index_ticker(index.name):
            basis, source = OHLC, provider.name
            try:
                candles = provider.get_index_candles(index.name, start, end)
                store.upsert_index_candles(conn, index.name, candles, source)
            except ProviderError as exc:
                sessions, first, last = _record(conn, index, basis, source)
                out.append(IndexSyncResult(
                    index.name, sessions, basis, source, first, last, str(exc)
                ))
                continue
        else:
            basis, source = CLOSE, CLOSE_SOURCE
            _project_close_only(conn, index, start, end)

        sessions, first, last = _record(conn, index, basis, source)
        out.append(IndexSyncResult(index.name, sessions, basis, source, first, last))

    return out


def _expected_sessions(
    conn: duckdb.DuckDBPyConnection, first: date | None, last: date | None
) -> int:
    """How many sessions the span should hold, for the density check.

    The calendar is authoritative (FR-4.3) but only where it reaches. It is
    seeded around the present, so for a series starting in 2007 it covers a
    fraction of the span and counting its rows returns a denominator smaller
    than the numerator — densities above 100%, which is how this was caught.

    So: use the calendar only when it spans the whole range, and otherwise fall
    back to counting weekdays. Weekdays overstate trading days by roughly 4%
    once holidays are removed, which understates density — the safe direction
    for a check whose job is to notice a series that is too thin.
    """
    if first is None or last is None or last < first:
        return 0

    covered = conn.execute(
        "SELECT min(trade_date), max(trade_date) FROM trading_calendar"
    ).fetchone()
    if covered and covered[0] and covered[0] <= first and covered[1] >= last:
        row = conn.execute(
            "SELECT count(*) FROM trading_calendar "
            "WHERE is_trading_day AND trade_date BETWEEN ? AND ?",
            [first, last],
        ).fetchone()
        return int(row[0]) if row and row[0] else 0

    days = (last - first).days + 1
    whole_weeks, remainder = divmod(days, 7)
    weekdays = whole_weeks * 5
    start_dow = first.weekday()
    weekdays += sum(1 for i in range(remainder) if (start_dow + i) % 7 < 5)
    return weekdays


# The longest lookback any FR-18.3/18.4 metric uses. Density is judged over
# this many sessions back from the latest bar, because that is the only stretch
# the metrics read.
METRIC_WINDOW = 252


# How much calendar time the metric window may occupy before it stops being the
# period its name claims. 252 sessions ought to fill about 365 days; 15 months
# allows for vendor gaps and holiday clusters without letting a "52-week high"
# quietly reach back years.
MAX_WINDOW_DAYS = 460


def _window_span(
    conn: duckdb.DuckDBPyConnection, index_name: str, last: date | None
) -> tuple[int | None, float | None]:
    """(days the metric window spans, sessions stored over sessions expected).

    The span is the gate; the ratio is reported alongside because it is what
    makes an odd span legible - a window stretched by missing sessions looks
    different from one stretched by a series that simply starts later.
    """
    if last is None:
        return None, None
    row = conn.execute(
        "SELECT min(trade_date) FROM ("
        "  SELECT trade_date FROM index_ohlcv_daily WHERE index_name = ? "
        "  ORDER BY trade_date DESC LIMIT ?"
        ")",
        [index_name, METRIC_WINDOW],
    ).fetchone()
    window_start = row[0] if row else None
    if window_start is None:
        return None, None

    stored = conn.execute(
        "SELECT count(*) FROM index_ohlcv_daily WHERE index_name = ? "
        "AND trade_date BETWEEN ? AND ?",
        [index_name, window_start, last],
    ).fetchone()[0]
    expected = _expected_sessions(conn, window_start, last)
    ratio = min(int(stored) / expected, 1.0) if expected else None
    return (last - window_start).days, ratio


def index_coverage(
    conn: duckdb.DuckDBPyConnection,
    indices: Sequence[TrackedIndex] = TRACKED,
) -> list[dict[str, object]]:
    """What is known about each tracked index's series, for the view and CLI.

    ``reaches_inception`` is computed here rather than stored: inception lives
    in the config and the series bounds live in the table, so deriving it at
    read time is the only way the two cannot disagree. ``None`` inception means
    not established, which resolves to False — the conservative answer, and the
    reason FR-18.3 reports a period high rather than an all-time high.
    """
    stored = {
        row[0]: row
        for row in conn.execute(
            "SELECT index_name, first_session, last_session, sessions, "
            "ohlc_basis, source FROM indices"
        ).fetchall()
    }
    out: list[dict[str, object]] = []
    for index in indices:
        row = stored.get(index.name)
        first = row[1] if row else None
        reaches = bool(
            first is not None
            and index.documented_inception is not None
            and first <= index.documented_inception
        )
        # Density over the window the metrics actually use, not over the whole
        # history. FR-18.3 looks back 252 sessions and FR-18.4 back 221; an
        # index sampled monthly until 2023 and daily since can answer both, and
        # measuring its whole span would refuse it for a sparseness that sits
        # entirely outside every window. What must be daily is the recent part.
        last = row[2] if row else None
        window_days, density = _window_span(conn, index.name, last)
        out.append({
            "index_name": index.name,
            "category": index.category,
            "first_session": first,
            "density": density,
            "window_days": window_days,
            # The gate: does the 252-session window occupy about 52 weeks?
            "daily": bool(window_days is not None and window_days <= MAX_WINDOW_DAYS),
            "last_session": row[2] if row else None,
            "sessions": int(row[3]) if row and row[3] is not None else 0,
            "ohlc_basis": row[4] if row else None,
            "source": row[5] if row else None,
            "documented_inception": index.documented_inception,
            "reaches_inception": reaches,
            "peak_metric": "ath" if reaches else "period",
        })
    return out
