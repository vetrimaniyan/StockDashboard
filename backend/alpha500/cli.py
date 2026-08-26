"""Command-line entry points."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date, datetime

from alpha500.config import settings
from alpha500.db import store
from alpha500.db.connection import analytical, init_databases
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

    if args.with_scheduler:
        from alpha500.scheduler import build_scheduler

        scheduler = build_scheduler()
        scheduler.start()
        print("  Scheduler started — EOD pipeline runs 18:45 IST on trading days.")

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

    p_serve = sub.add_parser("serve", help="start the API")
    p_serve.add_argument("--host", default=None)
    p_serve.add_argument("--port", type=int, default=None)
    p_serve.add_argument("--reload", action="store_true")
    p_serve.add_argument(
        "--with-scheduler",
        action="store_true",
        help="run the 18:45 IST EOD pipeline in-process (FR-5.1)",
    )

    args = parser.parse_args(argv)
    handlers = {
        "init": cmd_init, "universe": cmd_universe, "backfill": cmd_backfill,
        "pipeline": cmd_pipeline, "rebuild": cmd_rebuild,
        "reconcile": cmd_reconcile, "serve": cmd_serve,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
