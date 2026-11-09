"""Range-job extraction: plan, submit concurrently, wait once, append serially.

Measured motivation (2019-08 backfill): per-day jobs spent ~58s of local
CPU inside ~75 minutes of wall-clock — 98% was Databento batch-queue
round-trips. The queue cost is per JOB, not per day, so this extractor
now requests one job per consecutive run of missing days per symbol and
submits every job up front: Databento processes them concurrently and the
wait is one queue round-trip deep. Downloads and yields stay strictly
sequential — the consumer appends to one Iceberg table, and concurrent
appends would fight over commits.

`split_duration="day"` keeps range-job output as per-day files, so every
ExtractedDay still carries its true trading day and the consumer's
pipeline.day snapshot lineage stays per-day.
"""

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from src.ingestion.client import DatabentoClient
from src.ingestion.helpers import is_dbn_file, iter_days
from src.ingestion.spec import ExtractSpec

_DAY_IN_FILENAME = re.compile(r"(\d{8})\.mbo\.dbn")


@dataclass(frozen=True)
class ExtractedDay:
    """One downloaded day-file living in scratch (deleted by the consumer)."""

    symbol: str
    day: date
    path: Path


def _day_from_filename(filename: str) -> date:
    """Parse the trading day out of a Databento day-split file name."""
    match = _DAY_IN_FILENAME.search(filename)
    if not match:
        raise ValueError(f"cannot parse trading day from filename: {filename}")
    return date(int(match.group(1)[:4]), int(match.group(1)[4:6]), int(match.group(1)[6:8]))


def _consecutive_runs(days: list[date]) -> Iterator[tuple[date, date]]:
    """Group a sorted list of dates into (first, last_inclusive) runs."""
    if not days:
        return
    run_start = prev = days[0]
    for day in days[1:]:
        if day == prev + timedelta(days=1):
            prev = day
            continue
        yield run_start, prev
        run_start = prev = day
    yield run_start, prev


class DatabentoExtractor:
    """Plans missing-day runs, submits one range job each, waits once.

    Days already ingested (per `skip_day`, backed by the Iceberg catalog)
    are excluded from the plan, so reruns are idempotent and never billed
    twice; a partially-ingested range shrinks to runs over just the gaps.
    """

    def __init__(
        self,
        client: DatabentoClient,
        skip_day: Callable[[str, date], bool] | None = None,
        on_event: Callable[[str], None] | None = None,
    ) -> None:
        self.client = client
        self.skip_day = skip_day
        self.on_event = on_event

    def _emit(self, message: str) -> None:
        if self.on_event is not None:
            self.on_event(message)

    def extract(self, spec: ExtractSpec, scratch_dir: Path) -> Iterator[ExtractedDay]:
        """Yield scratch DBN day-files for every day not yet in bronze."""
        scratch_dir.mkdir(parents=True, exist_ok=True)

        # 1. plan: per symbol, runs of consecutive missing days
        runs: list[tuple[str, date, date]] = []
        for symbol in spec.symbols:
            missing = [
                day
                for day in iter_days(spec.start, spec.end)
                if not (self.skip_day is not None and self.skip_day(symbol, day))
            ]
            if not missing:
                self._emit(f"{symbol}: entire range already in bronze, skipping")
                continue
            for first, last in _consecutive_runs(missing):
                runs.append((symbol, first, last))
                self._emit(
                    f"{symbol}: planning {first}..{last} "
                    f"({(last - first).days + 1} calendar day(s))"
                )
        if not runs:
            return

        # 2. submit every job up front — concurrent queue processing
        jobs: list[tuple[str, str]] = []
        run_by_job: dict[str, tuple[str, date, date]] = {}
        for symbol, first, last in runs:
            label = f"{symbol} {first}..{last}"
            job_id = self.client.submit_range_job(
                spec, symbol, first, last + timedelta(days=1)
            )
            jobs.append((job_id, label))
            run_by_job[job_id] = (symbol, first, last)
            self._emit(f"{label}: submitted ({job_id})")

        # 3. one wait, all jobs
        self.client.wait_until_all_done(jobs, on_state=self._emit)

        # 4. download and yield strictly in order (serial appends)
        for job_id, label in jobs:
            symbol, _first, _last = run_by_job[job_id]
            for filename in self.client.list_filenames(job_id, label):
                if not is_dbn_file(filename):
                    continue
                path = self.client.download_file(job_id, filename, scratch_dir, label)
                day = _day_from_filename(filename)
                self._emit(f"{symbol} {day}: downloaded {path.name}")
                yield ExtractedDay(symbol=symbol, day=day, path=path)
