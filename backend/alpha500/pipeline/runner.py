"""EOD pipeline orchestration (SRS section 4).

FR-5.2: stages are discrete and individually re-runnable, each recording
start/end/row-count/status in ``job_runs``.
"""

from __future__ import annotations

import logging
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Iterator

from alpha500.config import settings
from alpha500.db import store
from alpha500.db.backup import backup_analytical_db, backup_app_db
from alpha500.db.connection import analytical, app, init_databases
from alpha500.exports import export_nightly
from alpha500.metrics.engine import compute_metrics_for_date
from alpha500.mktcal import calendar as cal
from alpha500.pipeline import ingest
from alpha500.pipeline.indices import sync_index_valuations
from alpha500.pipeline.validation import GateResult, run_gate
from alpha500.providers import NseArchiveProvider, ProviderError, YahooProvider
from alpha500.screens.presets import materialise_presets

log = logging.getLogger(__name__)

StageReporter = Callable[[str, str, str], None]

# How far back the nightly run re-checks index valuations. Generous on purpose:
# the file for a session is published late in the evening and may not exist yet
# when the run fires, and a machine that was off for a week leaves a hole. Only
# sessions not already stored are fetched, so the usual cost is one request.
INDEX_VALUATION_LOOKBACK_DAYS = 21


def _report(stage: str, status: str, message: str) -> None:
    log.info("[%s] %s %s", stage, status, message)


@dataclass(slots=True)
class PipelineResult:
    run_id: str
    data_as_of: date | None = None
    stages: dict[str, str] = field(default_factory=dict)
    gate: GateResult | None = None
    universe_added: list[str] = field(default_factory=list)
    universe_removed: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(v in {"OK", "SKIPPED"} for v in self.stages.values())


class Pipeline:
    def __init__(self, reporter: StageReporter | None = None) -> None:
        self.run_id = uuid.uuid4().hex[:12]
        self.report = reporter or _report

    @contextmanager
    def _stage(self, result: PipelineResult, name: str) -> Iterator[dict[str, Any]]:
        started = datetime.now(timezone.utc)
        ctx: dict[str, Any] = {"rows": 0, "message": ""}
        self._record(name, "RUNNING", started, None, 0, "")
        self.report(name, "RUNNING", "")
        try:
            yield ctx
        except Exception as exc:  # noqa: BLE001 - every stage failure is recorded
            result.stages[name] = "FAILED"
            result.messages.append(f"{name}: {exc}")
            self._record(name, "FAILED", started, datetime.now(timezone.utc), 0, str(exc))
            self.report(name, "FAILED", str(exc))
            raise
        else:
            status = ctx.get("status", "OK")
            result.stages[name] = status
            self._record(
                name, status, started, datetime.now(timezone.utc),
                int(ctx["rows"]), str(ctx["message"]),
            )
            self.report(name, status, str(ctx["message"]))

    def _record(
        self, stage: str, status: str, started: datetime,
        ended: datetime | None, rows: int, message: str,
    ) -> None:
        with app() as conn:
            conn.execute(
                "INSERT INTO job_runs (run_id, stage, status, started_at, ended_at, "
                "row_count, message) VALUES (?,?,?,?,?,?,?)",
                (
                    self.run_id, stage, status, started.isoformat(),
                    ended.isoformat() if ended else None, rows, message[:2000],
                ),
            )

    def run(self, target_date: date | None = None, skip_corporate_actions: bool = False
            ) -> PipelineResult:
        init_databases()
        result = PipelineResult(run_id=self.run_id)
        nse = NseArchiveProvider()
        yahoo = YahooProvider()

        with analytical() as conn:
            # FR-5.1: consult the calendar and skip non-trading days.
            cal.populate_weekdays(
                conn, date.today() - timedelta(days=400), date.today() + timedelta(days=30)
            )
            try:
                with self._stage(result, "sync_calendar") as ctx:
                    ctx["rows"] = cal.seed_from_nse(conn)
            except Exception:
                result.messages.append("calendar seed failed; weekday fallback in use")

            with self._stage(result, "sync_instruments") as ctx:
                count, added, removed = ingest.sync_universe(conn, nse)
                ctx["rows"] = count
                ctx["message"] = f"{len(added)} added, {len(removed)} removed"
                result.universe_added = added
                result.universe_removed = removed
                self._log_universe_changes(added, removed)

            universe = store.active_universe(conn, settings.index_name)

            with self._stage(result, "fetch_candles") as ctx:
                rows, sessions = ingest.incremental_prices(conn, nse, through=target_date)
                ctx["rows"] = rows
                ctx["message"] = f"{len(sessions)} session(s)"

            with self._stage(result, "fetch_index") as ctx:
                ctx["rows"] = ingest.incremental_index(conn, yahoo)

            # The index P/E panel's own data. Nothing fetched this before, so
            # it went stale silently for as long as nobody ran `alpha500
            # indices` by hand — and staleness in a valuation panel reads as a
            # market that has not moved, which is the FR-8.9 failure exactly.
            #
            # every=1 over a short window: recent sessions are exact. The
            # decade of history behind the medians stays a separate, manual
            # backfill, because sampling it costs hours.
            #
            # Wrapped like sync_calendar. This feeds one panel and must never
            # cost the run its metrics — but a drifted header now raises rather
            # than storing null ratios, and that has to stay visible, so the
            # stage is recorded FAILED rather than swallowed.
            valuation_end = target_date or date.today()
            try:
                with self._stage(result, "fetch_index_valuation") as ctx:
                    written, missing = sync_index_valuations(
                        conn,
                        nse,
                        valuation_end - timedelta(days=INDEX_VALUATION_LOOKBACK_DAYS),
                        valuation_end,
                        every=1,
                    )
                    ctx["rows"] = written
                    ctx["message"] = f"{missing} session(s) with no file"
            except Exception:
                result.messages.append(
                    "index valuations not updated; the panel reports its own as-of date"
                )

            if skip_corporate_actions:
                with self._stage(result, "sync_corporate_actions") as ctx:
                    ctx["status"] = "SKIPPED"
            else:
                with self._stage(result, "sync_corporate_actions") as ctx:
                    ctx["rows"] = ingest.sync_corporate_actions(conn, universe, yahoo)

            as_of = target_date or store.latest_stored_date(conn)
            result.data_as_of = as_of
            if as_of is None:
                result.messages.append("no data stored; nothing to validate or compute")
                return result

            with self._stage(result, "validate") as ctx:
                sample: dict[str, tuple[float, float]] = {}
                try:
                    nse_rows = {s: c.close for s, c in nse.fetch_session(as_of).items()}
                    sample = ingest.cross_source_sample(conn, as_of, nse_rows)
                except ProviderError:
                    pass

                gate = run_gate(
                    conn, as_of, settings.index_name, len(universe), sample
                )
                result.gate = gate
                ctx["message"] = gate.summary()
                if gate.blocked:
                    ctx["status"] = "FAILED"
                    ctx["message"] = gate.summary()

            # FR-4.2: a Block leaves the previous day's metrics in place.
            if result.gate is not None and result.gate.blocked:
                result.messages.append(
                    "validation blocked; previous metrics left in place as served dataset"
                )
                return result

            with self._stage(result, "compute_metrics") as ctx:
                ctx["rows"] = compute_metrics_for_date(conn, as_of, settings.index_name)

            with self._stage(result, "run_screens") as ctx:
                ctx["rows"] = materialise_presets(conn, as_of)

            # Shareable copies, refreshed while the connection is still open.
            # Never fatal: the metrics are the pipeline's product and a failed
            # file write must not cost them.
            with self._stage(result, "export_screens") as ctx:
                try:
                    summary = export_nightly(conn, as_of)
                    ctx["rows"] = len(summary["written"])
                    note = f"{len(summary['written'])} written"
                    if summary["skipped"]:
                        note += f", {len(summary['skipped'])} empty today"
                    if summary["failed"]:
                        note += f", {len(summary['failed'])} failed"
                        result.messages.append(
                            "export: " + "; ".join(summary["failed"])
                        )
                    ctx["message"] = note
                except Exception as exc:  # noqa: BLE001
                    ctx["status"] = "FAILED"
                    ctx["message"] = str(exc)
                    result.messages.append(f"screen export failed: {exc}")

            # Inside the analytical context on purpose: DuckDB allows one
            # writer per file across the machine, so the snapshot has to borrow
            # the connection the pipeline already holds rather than open a
            # second one and deadlock against itself.
            #
            # Never fatal. The night's metrics are already written, and losing
            # them to a failed copy would be perverse.
            with self._stage(result, "backup_analytical_db") as ctx:
                snapshot = backup_analytical_db(conn)
                status = str(snapshot["status"])
                ctx["message"] = f"{status}: {snapshot['reason']}"
                ctx["status"] = "FAILED" if status == "FAILED" else "OK"
                if status == "FAILED":
                    result.messages.append(
                        f"analytical backup failed: {snapshot['reason']}"
                    )

        # Last, and deliberately outside the analytical connection. The user
        # store is the half of the data that no backfill can reconstruct, so
        # it is snapshotted on every run that gets this far. A backup nobody
        # remembers to take is not a backup.
        with self._stage(result, "backup_app_db") as ctx:
            summary = backup_app_db()
            outcome = str(summary["status"])
            ctx["message"] = f"{outcome}: {summary['reason']}"
            # job_runs records OK/FAILED/SKIPPED only; an unchanged store is a
            # successful backup, and the message says which.
            ctx["status"] = {"UNCHANGED": "OK"}.get(outcome, outcome)
            if outcome == "FAILED":
                # Reported, never fatal. The night's metrics are already
                # written, and losing them to a failed copy would be perverse.
                result.messages.append(f"app.sqlite backup failed: {summary['reason']}")

        return result

    def _log_universe_changes(self, added: list[str], removed: list[str]) -> None:
        if not added and not removed:
            return
        today = date.today().isoformat()
        with app() as conn:
            conn.executemany(
                "INSERT INTO universe_changes (change_date, tradingsymbol, change_type, "
                "index_name) VALUES (?,?,?,?)",
                [(today, s, "ADDED", settings.index_name) for s in added]
                + [(today, s, "REMOVED", settings.index_name) for s in removed],
            )


def rebuild_metrics(target_date: date | None = None) -> int:
    """FR-5.4: re-run stages 7-8 only, offline, against stored data."""
    init_databases()
    with analytical() as conn:
        as_of = target_date or store.latest_stored_date(conn)
        if as_of is None:
            return 0
        rows = compute_metrics_for_date(conn, as_of, settings.index_name)
        materialise_presets(conn, as_of)
        return rows
