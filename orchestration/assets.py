"""Pipeline assets: bronze ingestion, silver/gold dbt, Soda observability.

Each asset wraps an existing CLI tool via subprocess — the most robust
pattern across local dev (dagster dev with .env) and Dagster+ Serverless
(pre-built environment with native env vars). Assets receive configuration
via Dagster resources (see resources.py), making it explicit, UI-visible,
and testable.

Daily partitions map 1:1 onto the pipeline's day-aligned windows:
  - ingestion CLI's --start/--end (exclusive end, one day)
  - dbt's start_date/end_date vars (inclusive end, same day)
"""

import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

from dagster import (
    AssetExecutionContext,
    DailyPartitionsDefinition,
    asset,
)

from orchestration.resources import AwsConfig, DbtConfig, PipelineConfig

REPO_ROOT = Path(__file__).resolve().parents[1]

PARTITIONS = DailyPartitionsDefinition(start_date="2019-07-30")


def _run(
    context: AssetExecutionContext,
    cmd: list[str],
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    label: str = "",
) -> str:
    """Run a subprocess, streaming output to the Dagster log."""
    context.log.info(f"$ {' '.join(cmd)}" + (f"  (cwd={cwd.name})" if cwd else ""))

    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)

    result = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        env=merged_env,
        capture_output=True,
        text=True,
        timeout=3600,
    )

    if result.stdout:
        for line in result.stdout.strip().splitlines()[-50:]:
            context.log.info(f"  {line}")
    if result.stderr:
        for line in result.stderr.strip().splitlines()[-30:]:
            context.log.warning(f"  {line}")

    if result.returncode != 0:
        raise RuntimeError(
            f"{label or 'command'} failed (exit {result.returncode}): "
            f"{' '.join(cmd[:8])}..."
        )
    return result.stdout


def _next_day(day: str) -> str:
    return (datetime.strptime(day, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Bronze: ingest one day of MBO data for all symbols


@asset(
    partitions_def=PARTITIONS,
    group_name="bronze",
    description="Ingest one trading day of MBO data for all configured symbols into bronze (Iceberg). Weekends are skipped (no market data).",
    required_resource_keys={"pipeline", "aws"},
)
def bronze_ingestion(context: AssetExecutionContext) -> None:
    day = context.partition_key
    pipeline: PipelineConfig = context.resources.pipeline
    aws: AwsConfig = context.resources.aws

    # Skip weekends before touching Databento (saves a ~10-min queue
    # round-trip for a guaranteed-empty result). Holidays (MLK, July 4,
    # etc.) are NOT skipped — they no-op naturally via Databento returning
    # no files, at the cost of one queue wait. A holiday calendar could
    # be added later if it bothers.
    dt = datetime.strptime(day, "%Y-%m-%d")
    if dt.weekday() >= 5:
        context.log.info(f"{day} is a weekend — no market data, skipping")
        return

    cmd = [sys.executable, "-m", "src.ingestion.ingest",
           "--start", day, "--end", _next_day(day)]
    for s in pipeline.symbol_list:
        cmd.extend(["--symbols", s])

    _run(context, cmd, cwd=REPO_ROOT, env=aws.subprocess_env,
         label=f"bronze ingestion {day} ({pipeline.symbols})")


# ---------------------------------------------------------------------------
# Silver: dbt merge for silver + flags + book_state


@asset(
    partitions_def=PARTITIONS,
    group_name="silver",
    description="Run dbt silver models (itch_mbo_cleaned, message_flags, book_state) for the partition day.",
    required_resource_keys={"aws", "dbt"},
)
def silver_models(context: AssetExecutionContext) -> None:
    day = context.partition_key
    aws: AwsConfig = context.resources.aws
    dbt: DbtConfig = context.resources.dbt

    vars_json = f'{{"start_date": "{day}", "end_date": "{day}"}}'
    dbt_dir = REPO_ROOT / dbt.project_dir

    _run(
        context,
        [sys.executable, "-m", "dbt.cli.main", "run",
         "--select", "itch_mbo_cleaned", "message_flags", "book_state",
         "--vars", vars_json],
        cwd=dbt_dir,
        env=aws.subprocess_env,
        label=f"dbt silver merge {day}",
    )


# ---------------------------------------------------------------------------
# Gold: full rebuild of all aggregate tables
# Daily-partitioned for orchestration simplicity (each trigger rebuilds all,
# which is idempotent and fast — a few minutes at current scale). For large
# backfills, deselect this asset and run it once at the end.


@asset(
    partitions_def=PARTITIONS,
    group_name="gold",
    description="Full gold rebuild (all aggregate tables). Idempotent; each run rebuilds everything.",
    required_resource_keys={"aws", "dbt"},
)
def gold_models(context: AssetExecutionContext) -> None:
    aws: AwsConfig = context.resources.aws
    dbt: DbtConfig = context.resources.dbt

    _run(
        context,
        [sys.executable, "-m", "dbt.cli.main", "run"],
        cwd=REPO_ROOT / dbt.project_dir,
        env=aws.subprocess_env,
        label="dbt gold rebuild",
    )


# ---------------------------------------------------------------------------
# Soda: post-build observability scan (silver + gold)


@asset(
    group_name="observability",
    description="Run Soda data quality scans on silver and gold layers. Skipped gracefully if soda-core is not installed.",
    required_resource_keys={"aws"},
)
def soda_scan(context: AssetExecutionContext) -> None:
    """Run both scans; skip with a warning if soda-core isn't available.

    Soda requires soda-core-athena which pins PyAthena<3, conflicting with
    dbt-athena's >=3 — so it's kept in an ephemeral env locally and is NOT
    in the project dependencies. On Dagster+, include it or accept the
    graceful skip (dbt tests still provide build-time quality gates).
    """
    aws: AwsConfig = context.resources.aws

    check = subprocess.run(
        [sys.executable, "-c", "import soda.scan"],
        capture_output=True, text=True, env=aws.subprocess_env,
    )
    if check.returncode != 0:
        context.log.warning(
            "soda-core not installed in this environment "
            "(PyAthena version conflict with dbt-athena); skipping. "
            "Run locally: uv run --no-project --with soda-core-athena "
            "--with setuptools python src/observability/scan.py silver|gold"
        )
        return

    for target in ("silver", "gold"):
        _run(
            context,
            [sys.executable, "src/observability/scan.py", target],
            cwd=REPO_ROOT,
            env=aws.subprocess_env,
            label=f"soda {target} scan",
        )
