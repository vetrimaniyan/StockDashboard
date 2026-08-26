"""The data validation gate (SRS 3.4).

FR-4.2: a Block aborts the run and leaves the previous day's metrics in place
as the served dataset. Serving stale-but-correct data is always preferable to
serving fresh-but-corrupt data — the UI then has to make the staleness loud
(FR-8.9). This module decides; it does not publish.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from enum import StrEnum

import duckdb

from alpha500.mktcal import calendar as cal


class Severity(StrEnum):
    BLOCK = "BLOCK"
    WARN = "WARN"


@dataclass(slots=True)
class CheckResult:
    check_id: str
    name: str
    severity: Severity
    passed: bool
    detail: str = ""
    affected: int = 0


@dataclass(slots=True)
class GateResult:
    trade_date: date
    results: list[CheckResult] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return any(r.severity is Severity.BLOCK and not r.passed for r in self.results)

    @property
    def warnings(self) -> list[CheckResult]:
        return [r for r in self.results if r.severity is Severity.WARN and not r.passed]

    @property
    def failures(self) -> list[CheckResult]:
        return [r for r in self.results if not r.passed]

    def summary(self) -> str:
        failed = len(self.failures)
        if self.blocked:
            return f"BLOCKED on {self.trade_date}: {failed} check(s) failed"
        if failed:
            return f"passed with {failed} warning(s) on {self.trade_date}"
        return f"all checks passed on {self.trade_date}"


def run_gate(
    conn: duckdb.DuckDBPyConnection,
    trade_date: date,
    index_name: str,
    universe_size: int,
    cross_source_sample: dict[str, tuple[float, float]] | None = None,
) -> GateResult:
    """Run every FR-4.1 check for one session."""
    gate = GateResult(trade_date=trade_date)
    add = gate.results.append

    # V7 first: if it is not a trading session, nothing else is meaningful.
    trading = cal.is_trading_day(conn, trade_date)
    add(
        CheckResult(
            "V7", "Trade date is a valid NSE trading session", Severity.BLOCK,
            passed=trading,
            detail="" if trading else f"{trade_date} is not a trading session",
        )
    )

    row_count = conn.execute(
        "SELECT count(*) FROM ohlcv_daily WHERE trade_date = ?", [trade_date]
    ).fetchone()[0]

    # V1 — row count within +/-5% of the active universe.
    if universe_size > 0:
        lower, upper = universe_size * 0.95, universe_size * 1.05
        ok = lower <= row_count <= upper
        detail = (
            "" if ok else f"{row_count} rows vs universe {universe_size} "
            f"(allowed {lower:.0f}-{upper:.0f})"
        )
    else:
        ok, detail = False, "universe size is zero"
    add(CheckResult("V1", "Row count within 5% of universe", Severity.BLOCK, ok, detail,
                    affected=row_count))

    # V2 — duplicates. The primary key makes this structurally impossible;
    # the check stays because a schema change could quietly remove that key.
    dupes = conn.execute(
        """
        SELECT count(*) FROM (
            SELECT instrument_token, trade_date FROM ohlcv_daily
             WHERE trade_date = ?
             GROUP BY 1, 2 HAVING count(*) > 1
        )
        """,
        [trade_date],
    ).fetchone()[0]
    add(CheckResult("V2", "No duplicate (token, date)", Severity.BLOCK, dupes == 0,
                    f"{dupes} duplicated keys" if dupes else "", affected=dupes))

    # V3 — OHLC internal consistency.
    bad_ohlc = conn.execute(
        """
        SELECT count(*) FROM ohlcv_daily
         WHERE trade_date = ?
           AND NOT (low <= open AND open <= high AND low <= close AND close <= high)
        """,
        [trade_date],
    ).fetchone()[0]
    add(CheckResult("V3", "low <= open/close <= high", Severity.BLOCK, bad_ohlc == 0,
                    f"{bad_ohlc} rows violate OHLC ordering" if bad_ohlc else "",
                    affected=bad_ohlc))

    # V4 — no negative or null OHLC, volume >= 0.
    bad_values = conn.execute(
        """
        SELECT count(*) FROM ohlcv_daily
         WHERE trade_date = ?
           AND (open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL
                OR open <= 0 OR high <= 0 OR low <= 0 OR close <= 0 OR volume < 0)
        """,
        [trade_date],
    ).fetchone()[0]
    add(CheckResult("V4", "No negative or null OHLC", Severity.BLOCK, bad_values == 0,
                    f"{bad_values} rows with invalid values" if bad_values else "",
                    affected=bad_values))

    # V5 — large move with no corporate action: warn and quarantine.
    outliers = conn.execute(
        """
        WITH adj AS (
            SELECT instrument_token, trade_date, close * adj_factor AS c
              FROM ohlcv_daily
        ),
        rets AS (
            SELECT instrument_token, trade_date,
                   c / LAG(c) OVER (PARTITION BY instrument_token ORDER BY trade_date) - 1 AS ret
              FROM adj
        )
        SELECT r.instrument_token, r.ret
          FROM rets r
     LEFT JOIN corporate_actions ca
            ON ca.instrument_token = r.instrument_token AND ca.ex_date = r.trade_date
         WHERE r.trade_date = ? AND abs(r.ret) > 0.35 AND ca.instrument_token IS NULL
        """,
        [trade_date],
    ).fetchall()
    if outliers:
        _quarantine(conn, trade_date, "V5",
                    [(int(t), f"daily return {ret:.2%} with no corporate action")
                     for t, ret in outliers])
    add(CheckResult("V5", "Daily move > 35% without corporate action", Severity.WARN,
                    len(outliers) == 0,
                    f"{len(outliers)} rows quarantined" if outliers else "",
                    affected=len(outliers)))

    # V6 — zero volume on a trading session.
    zero_volume = conn.execute(
        "SELECT count(*) FROM ohlcv_daily WHERE trade_date = ? AND volume = 0",
        [trade_date],
    ).fetchone()[0]
    add(CheckResult("V6", "Volume = 0 on a trading session", Severity.WARN,
                    zero_volume == 0,
                    f"{zero_volume} symbols with zero volume" if zero_volume else "",
                    affected=zero_volume))

    # V8 — gap detection against the calendar, not against stored data.
    prior = conn.execute(
        "SELECT max(trade_date) FROM ohlcv_daily WHERE trade_date < ?", [trade_date]
    ).fetchone()[0]
    missing: list[date] = []
    if prior is not None:
        expected = cal.trading_days_between(
            conn, prior + timedelta(days=1), trade_date - timedelta(days=1)
        )
        if expected:
            present = {
                r[0]
                for r in conn.execute(
                    "SELECT DISTINCT trade_date FROM ohlcv_daily "
                    "WHERE trade_date BETWEEN ? AND ?",
                    [prior + timedelta(days=1), trade_date - timedelta(days=1)],
                ).fetchall()
            }
            missing = [d for d in expected if d not in present]
    add(CheckResult("V8", "No missing trading session since last stored date",
                    Severity.WARN, not missing,
                    f"missing sessions: {[str(d) for d in missing[:10]]}" if missing else "",
                    affected=len(missing)))

    # V9 — cross-source spot check on a random sample.
    if cross_source_sample:
        mismatches = [
            f"{sym}: {a:.2f} vs {b:.2f}"
            for sym, (a, b) in cross_source_sample.items()
            if b > 0 and abs(a - b) / b > 0.001
        ]
        add(CheckResult("V9", "Cross-source close agreement within 0.1%", Severity.WARN,
                        not mismatches, "; ".join(mismatches[:5]),
                        affected=len(mismatches)))
    else:
        add(CheckResult("V9", "Cross-source close agreement within 0.1%", Severity.WARN,
                        True, "not sampled this run"))

    return gate


def _quarantine(
    conn: duckdb.DuckDBPyConnection,
    trade_date: date,
    check_id: str,
    rows: list[tuple[int, str]],
) -> None:
    now = datetime.now(timezone.utc)
    conn.executemany(
        "INSERT INTO quarantined_rows VALUES (?,?,?,?,?) "
        "ON CONFLICT DO UPDATE SET detail = excluded.detail, "
        "quarantined_at = excluded.quarantined_at",
        [(token, trade_date, check_id, detail, now) for token, detail in rows],
    )
