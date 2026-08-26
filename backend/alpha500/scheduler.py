"""Local scheduler (FR-5.1).

Runs the EOD pipeline at 18:45 IST on trading days. NSE publishes the final
bhavcopy after post-close processing; scheduling earlier risks ingesting
provisional data.

APScheduler runs in-process, as §2.1 specifies. That is also what makes the
DuckDB single-writer constraint tractable: the scheduler and the API share one
process and therefore one connection (see DECISIONS.md, D-6).
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from alpha500.db.connection import analytical
from alpha500.mktcal import calendar as cal
from alpha500.pipeline.runner import Pipeline

log = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
PIPELINE_JOB_ID = "eod_pipeline"


def _is_trading_day(day: date) -> bool:
    try:
        with analytical(read_only=True) as conn:
            return cal.is_trading_day(conn, day)
    except Exception:  # noqa: BLE001 - a locked store must not skip the run
        log.warning("could not consult calendar; falling back to the weekday rule")
        return day.weekday() < 5


def run_pipeline_if_trading_day() -> None:
    today = datetime.now(IST).date()
    if not _is_trading_day(today):
        log.info("%s is not a trading session; skipping pipeline", today)
        return

    result = Pipeline().run()
    if result.gate is not None and result.gate.blocked:
        # FR-11.2: a validation block is an alert, distinct from the digest.
        log.error("PIPELINE BLOCKED %s: %s", result.run_id, result.gate.summary())
    elif not result.ok:
        log.error("PIPELINE FAILED %s: %s", result.run_id, "; ".join(result.messages))
    else:
        log.info("pipeline %s complete, data as of %s", result.run_id, result.data_as_of)


def build_scheduler(hour: int = 18, minute: int = 45) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone=IST)
    scheduler.add_job(
        run_pipeline_if_trading_day,
        trigger=CronTrigger(day_of_week="mon-fri", hour=hour, minute=minute, timezone=IST),
        id=PIPELINE_JOB_ID,
        name="EOD ingestion pipeline",
        # A host that was asleep at 18:45 should still run when it wakes, but
        # only once, and only if it is not absurdly late.
        misfire_grace_time=6 * 3600,
        coalesce=True,
        max_instances=1,
        replace_existing=True,
    )
    return scheduler
