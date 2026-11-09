"""Schedules and jobs for the market surveillance pipeline.

The daily catch-up schedule mirrors the pipeline's 5-day rolling window:
on each weekday it triggers materialization of the last N trading days,
which are idempotent (bronze skips ingested days, silver re-merges).
"""

import os
from datetime import datetime, timedelta

from dagster import (
    RunRequest,
    ScheduleDefinition,
    define_asset_job,
)

from orchestration.assets import bronze_ingestion, silver_models, gold_models

# The partitioned job: bronze → silver → gold for one day
daily_pipeline = define_asset_job(
    name="daily_pipeline",
    selection=[bronze_ingestion, silver_models, gold_models],
    description="Ingest → silver merge → gold rebuild for one trading day",
)


def _trading_days_back(n: int, from_date: datetime | None = None) -> list[str]:
    """Return the last n weekday dates as YYYY-MM-DD strings."""
    today = (from_date or datetime.now()).date()
    days: list[str] = []
    d = today
    while len(days) < n:
        if d.weekday() < 5:  # Mon-Fri
            days.append(d.strftime("%Y-%m-%d"))
        d -= timedelta(days=1)
    return days


_catch_up_days = int(os.environ.get("CATCH_UP_DAYS", "5"))

daily_catch_up = ScheduleDefinition(
    job=daily_pipeline,
    cron_schedule="0 6 * * 1-5",  # weekdays 06:00 UTC (2am ET)
    execution_timezone="UTC",
    description=(
        f"Weekday catch-up: materialize the last {_catch_up_days} trading "
        "days. Bronze skips days already ingested; silver re-merges "
        "idempotently — repeated runs are safe no-ops."
    ),
    execution_fn=lambda context: [
        RunRequest(partition_key=day, run_key=f"daily-catch-up-{day}")
        for day in _trading_days_back(_catch_up_days)
    ],
)
