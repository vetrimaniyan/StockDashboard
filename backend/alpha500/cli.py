"""Command-line entry points."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date, datetime

from alpha500.config import settings
from alpha500.db import store
from alpha500.db.connection import (
    analytical,
    configure_process_connection,
    init_databases,
)
from alpha500.mktcal import calendar as cal
from alpha500.pipeline import ingest
from alpha500.pipeline.adjust import reconcile_adjustments
from alpha500.pipeline.runner import Pipeline, rebuild_metrics
from alpha500.providers import NseArchiveProvider, YahooProvider


def _progress(label: str, done: int, total: int) -> None:
    width = 32
    filled = int(width * done / max(total, 1))
    bar = "#" * filled + "." * (width - filled)
    sys.stdout.write(f"\r  [{bar}] {done}/{total}  {label[:22]:<22}")
    sys.stdout.flush()
    if done == total:
        sys.stdout.write("\n")


def _parse_date(text: str | None) -> date | None:
    return datetime.strptime(text, "%Y-%m-%d").date() if text else None


def _parse_hhmm(text: str | None) -> tuple[int | None, int | None]:
    """Parse ``HH:MM``; None means fall back to the configured schedule."""
    if not text:
        return None, None
    parsed = datetime.strptime(text, "%H:%M")
    return parsed.hour, parsed.minute


def cmd_init(_args: argparse.Namespace) -> int:
    init_databases()
    with analytical() as conn:
        cal.populate_weekdays(conn, date(2015, 1, 1), date.today().replace(month=12, day=31))
        try:
            marked = cal.seed_from_nse(conn)
            print(f"  seeded {marked} holidays from NSE")
        except Exception as exc:  # noqa: BLE001
            print(f"  holiday seed skipped ({exc}); weekday fallback in use")
    print(f"Initialised {settings.analytical_db} and {settings.app_db}")
    return 0


def cmd_universe(_args: argparse.Namespace) -> int:
    init_databases()
    with analytical() as conn:
        count, added, removed = ingest.sync_universe(conn, NseArchiveProvider())
    print(f"Universe: {count} constituents ({len(added)} added, {len(removed)} removed)")
    if added:
        print("  added:  ", ", ".join(added[:20]))
    if removed:
        print("  removed:", ", ".join(removed[:20]))
    return 0


def cmd_backfill(args: argparse.Namespace) -> int:
    init_databases()
    started = time.monotonic()
    with analytical() as conn:
        universe = store.active_universe(conn, settings.index_name)
        if not universe:
            print("Universe is empty. Run 'alpha500 universe' first.")
            return 1
        if args.limit:
            universe = universe[: args.limit]

        print(f"Index history ({args.years}y)...")
        print(f"  {ingest.backfill_index(conn, args.years)} sessions")

        print(f"Price history for {len(universe)} symbols ({args.years}y)...")
        rows, failures = ingest.backfill_prices(
            conn, universe, years=args.years, progress=_progress, force=args.force
        )
        print(f"  {rows} rows written")
        if failures:
            print(f"  {len(failures)} symbols returned nothing: {', '.join(failures[:15])}")

        if not args.skip_actions:
            print("Corporate actions and adjustment factors...")
            count = ingest.sync_corporate_actions(conn, universe, progress=_progress)
            print(f"  {count} actions stored")

    print(f"Backfill finished in {time.monotonic() - started:.1f}s")
    return 0


def cmd_pipeline(args: argparse.Namespace) -> int:
    def reporter(stage: str, status: str, message: str) -> None:
        if status != "RUNNING":
            print(f"  {stage:<24} {status:<8} {message}")

    print("Running EOD pipeline...")
    result = Pipeline(reporter=reporter).run(
        target_date=_parse_date(args.date), skip_corporate_actions=args.skip_actions
    )
    print(f"\nRun {result.run_id} — data as of {result.data_as_of}")
    if result.gate is not None:
        print(f"Validation: {result.gate.summary()}")
        for check in result.gate.failures:
            print(f"  [{check.severity}] {check.check_id} {check.name}: {check.detail}")
    for message in result.messages:
        print(f"  ! {message}")
    return 0 if result.ok else 1


def cmd_rebuild(args: argparse.Namespace) -> int:
    started = time.monotonic()
    rows = rebuild_metrics(_parse_date(args.date))
    elapsed = time.monotonic() - started
    print(f"Recomputed {rows} metric rows in {elapsed:.1f}s (NFR-1.7 budget: 60s)")
    return 0


def cmd_materialise(args: argparse.Namespace) -> int:
    """Compute metrics across history so a backtest has point-in-time inputs."""
    from alpha500.metrics.history import materialise_history

    init_databases()
    started = time.monotonic()
    with analytical() as conn:
        bounds = conn.execute(
            "SELECT min(trade_date), max(trade_date) FROM ohlcv_daily"
        ).fetchone()
        if bounds is None or bounds[0] is None:
            print("No price history stored. Run 'alpha500 backfill' first.")
            return 1
        start = _parse_date(args.start) or bounds[0]
        end = _parse_date(args.end) or bounds[1]
        rows = materialise_history(conn, start, end, progress=lambda m: print(f"  {m}"))
    elapsed = time.monotonic() - started
    print(f"Materialised {rows:,} metric rows for {start}..{end} in {elapsed:.1f}s")
    return 0


def cmd_backtest(args: argparse.Namespace) -> int:
    """Replay a screen over history with realistic friction (Phase 3)."""
    import dataclasses

    from alpha500.backtest.engine import BacktestConfig, run_backtest
    from alpha500.backtest.walkforward import sweep, walk_forward
    from alpha500.screens.presets import PRESETS, get_preset

    if args.screen not in PRESETS:
        print(f"Unknown screen {args.screen!r}. Available: {', '.join(PRESETS)}")
        return 1

    with analytical(read_only=True) as conn:
        bounds = conn.execute(
            "SELECT min(trade_date), max(trade_date) FROM metrics_daily"
        ).fetchone()
        if bounds is None or bounds[0] is None or bounds[0] == bounds[1]:
            print(
                "Metrics are materialised for at most one session. "
                "Run 'alpha500 materialise' first — a backtest needs the metrics "
                "as they stood on each historical date."
            )
            return 1

        config = BacktestConfig(
            screen=get_preset(args.screen),
            exit_screen=get_preset("Momentum Breakdown") if args.use_exit_screen else None,
            start=_parse_date(args.start) or bounds[0],
            end=_parse_date(args.end) or bounds[1],
            initial_capital=args.capital,
            max_positions=args.max_positions,
            stop_atr_multiple=args.stop,
            trailing_stop=args.trailing,
        )

        result = run_backtest(conn, config)
        _print_backtest(args.screen, result)

        if args.sweep:
            values = [float(v) for v in args.sweep.split(",")]
            print("\nATR stop sweep")
            verdict = sweep(
                conn, config, values,
                lambda cfg, value: dataclasses.replace(cfg, stop_atr_multiple=value),
            )
            for point in verdict.points:
                print(
                    f"  k={point.value:<5} net CAGR {point.metric:>7.2f}%   "
                    f"trades {point.detail['trades']:>4}   "
                    f"maxDD {point.detail['max_drawdown_pct']:>7.2f}%"
                )
            print(f"  best k={verdict.best_value}, plateau width "
                  f"{verdict.plateau_width}/{len(values)}")
            if verdict.warning:
                print(f"\n  {verdict.warning}")

        if args.walk_forward:
            values = [float(v) for v in (args.sweep or "1.5,2.0,2.5,3.0,4.0").split(",")]
            print("\nWalk-forward")
            wf = walk_forward(
                conn, config, values,
                lambda cfg, value: dataclasses.replace(cfg, stop_atr_multiple=value),
            )
            for window in wf.windows:
                print(
                    f"  test {window['test_start']}..{window['test_end']}  "
                    f"k={window['chosen_value']:<5} "
                    f"in {window['in_sample_cagr']:>7.2f}%  "
                    f"out {window['out_of_sample_cagr']:>7.2f}%"
                )
            if wf.in_sample_cagr is not None:
                print(f"  mean in-sample {wf.in_sample_cagr:.2f}%, "
                      f"out-of-sample {wf.out_of_sample_cagr:.2f}%")
            if wf.warning:
                print(f"\n  {wf.warning}")
    return 0


def _print_backtest(name: str, result: Any) -> None:
    summary = result.summary
    trades = summary.trades
    print(f"\n{name} — {summary.start} to {summary.end} ({summary.sessions} sessions)")
    print(f"  {'':<18}{'gross of tax':>14}{'net of tax':>14}")
    for label, attr in (
        ("CAGR %", "cagr_pct"),
        ("total return %", "total_return_pct"),
        ("max drawdown %", "max_drawdown_pct"),
    ):
        g = getattr(summary.gross, attr)
        n = getattr(summary.net, attr)
        print(f"  {label:<18}{g:>14.2f}{n:>14.2f}")
    for label, attr in (("Sharpe", "sharpe"), ("Sortino", "sortino")):
        g = getattr(summary.gross, attr)
        n = getattr(summary.net, attr)
        gs = f"{g:.2f}" if g is not None else "n/a"
        ns = f"{n:.2f}" if n is not None else "n/a"
        print(f"  {label:<18}{gs:>14}{ns:>14}")

    if trades.trades:
        print(f"\n  trades {trades.trades}   hit rate {trades.hit_rate_pct:.1f}%   "
              f"avg hold {trades.avg_holding_days:.0f}d   exposure {trades.exposure_pct:.0f}%")
        print(f"  avg win {trades.avg_win_pct:.2f}%   avg loss {trades.avg_loss_pct:.2f}%   "
              f"win/loss {trades.win_loss_ratio:.2f}" if trades.win_loss_ratio else "")
        print(f"  costs Rs{trades.total_costs:,.0f}   TDS withheld Rs{trades.total_tds:,.0f}")

    for warning in summary.warnings:
        print(f"\n  !! {warning}")


def cmd_reconcile(_args: argparse.Namespace) -> int:
    """FR-3.2 reconciliation — a release gate (NFR-5.4)."""
    with analytical(read_only=True) as conn:
        violations = reconcile_adjustments(conn)
    if not violations:
        print("Corporate-action reconciliation PASSED: no adjusted return exceeds 35% "
              "on a split/bonus ex-date.")
        return 0
    print(f"Corporate-action reconciliation FAILED: {len(violations)} violation(s)")
    for v in violations[:20]:
        print(f"  {v['tradingsymbol']:<14} {v['trade_date']}  "
              f"{float(v['return']):+.2%}  ({v['action_type']})")
    return 1


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    host = args.host or settings.api_host
    if host not in {"127.0.0.1", "localhost", "::1"}:
        # NFR-4.1: binding beyond loopback must be deliberate and warned about.
        print(
            f"\n  WARNING: binding to {host} exposes this service beyond loopback.\n"
            "  Market-data licensing does not permit redistribution, and the API\n"
            "  has no authentication. Bind to 127.0.0.1 unless you are certain.\n"
        )

    # With the scheduler in-process the pipeline writes through this same
    # connection, so the process must hold the store read-write. Without it,
    # read-only leaves the file available to other readers.
    configure_process_connection(read_only=not args.with_scheduler)

    if args.with_scheduler:
        from alpha500.scheduler import PIPELINE_JOB_ID, build_scheduler

        hour, minute = _parse_hhmm(args.at)
        scheduler = build_scheduler(hour, minute)
        scheduler.start()
        job = scheduler.get_job(PIPELINE_JOB_ID)
        print(
            f"  Scheduler started — EOD pipeline runs "
            f"{hour if hour is not None else settings.pipeline_hour:02d}:"
            f"{minute if minute is not None else settings.pipeline_minute:02d} IST "
            "on trading days."
        )
        if job is not None:
            print(f"  Next run: {job.next_run_time}")

    uvicorn.run(
        "alpha500.api.main:app",
        host=host,
        port=args.port or settings.api_port,
        reload=args.reload,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    parser = argparse.ArgumentParser(prog="alpha500", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="create databases and seed the trading calendar")
    sub.add_parser("universe", help="sync the NIFTY 500 constituent list")

    p_backfill = sub.add_parser("backfill", help="load bulk price history (explicit only)")
    # Five years by operator decision. Note this yields ~1236 sessions, just
    # under FR-2.2's 1260 floor, because NSE trades ~247 days a year rather
    # than the 252 the spec assumes. Pass --years 6 to clear it.
    p_backfill.add_argument("--years", type=int, default=5)
    p_backfill.add_argument("--limit", type=int, default=None,
                            help="only the first N symbols, for a quick trial")
    p_backfill.add_argument("--force", action="store_true",
                            help="refetch symbols that already have history")
    p_backfill.add_argument("--skip-actions", action="store_true")

    p_pipeline = sub.add_parser("pipeline", help="run the incremental EOD pipeline")
    p_pipeline.add_argument("--date", default=None, help="target session, YYYY-MM-DD")
    p_pipeline.add_argument("--skip-actions", action="store_true")

    p_rebuild = sub.add_parser("rebuild", help="recompute metrics offline (stages 7-8)")
    p_rebuild.add_argument("--date", default=None)

    sub.add_parser("reconcile", help="run the corporate-action reconciliation gate")

    p_hist = sub.add_parser(
        "materialise", help="compute metrics for every session in a range (Phase 3)"
    )
    p_hist.add_argument("--from", dest="start", default=None, metavar="YYYY-MM-DD")
    p_hist.add_argument("--to", dest="end", default=None, metavar="YYYY-MM-DD")

    p_bt = sub.add_parser("backtest", help="replay a screen over history (Phase 3)")
    p_bt.add_argument("screen", nargs="?", default="Momentum Leaders")
    p_bt.add_argument("--from", dest="start", default=None, metavar="YYYY-MM-DD")
    p_bt.add_argument("--to", dest="end", default=None, metavar="YYYY-MM-DD")
    p_bt.add_argument("--capital", type=float, default=1_000_000.0)
    p_bt.add_argument("--max-positions", type=int, default=10)
    p_bt.add_argument("--stop", type=float, default=2.0, help="ATR stop multiple")
    p_bt.add_argument("--trailing", action="store_true", help="trail the stop")
    p_bt.add_argument(
        "--use-exit-screen", action="store_true",
        help="exit on the Momentum Breakdown signal as well as the stop",
    )
    p_bt.add_argument("--sweep", default=None, metavar="1.5,2.0,2.5",
                      help="sweep the ATR stop multiple and judge the peak")
    p_bt.add_argument("--walk-forward", action="store_true",
                      help="choose the stop in-sample, measure it out-of-sample")

    p_serve = sub.add_parser("serve", help="start the API")
    p_serve.add_argument("--host", default=None)
    p_serve.add_argument("--port", type=int, default=None)
    p_serve.add_argument("--reload", action="store_true")
    p_serve.add_argument(
        "--with-scheduler",
        action="store_true",
        help="run the nightly EOD pipeline in-process (FR-5.1)",
    )
    p_serve.add_argument(
        "--at",
        default=None,
        metavar="HH:MM",
        help="scheduler time in IST (default 18:45, after NSE publishes)",
    )

    args = parser.parse_args(argv)
    handlers = {
        "init": cmd_init, "universe": cmd_universe, "backfill": cmd_backfill,
        "pipeline": cmd_pipeline, "rebuild": cmd_rebuild,
        "materialise": cmd_materialise, "backtest": cmd_backtest,
        "reconcile": cmd_reconcile, "serve": cmd_serve,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
