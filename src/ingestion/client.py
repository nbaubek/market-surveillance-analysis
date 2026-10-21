"""Databento HTTP client wrapper: auth, retries, and job lifecycle."""

import logging
import os
import time
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from typing import TypeVar

import databento as db

from src.ingestion.spec import ExtractSpec

logger = logging.getLogger(__name__)

T = TypeVar("T")


class DatabentoClient:
    """Wraps `db.Historical` with retry, polling, and per-file downloads.

    UI-free: progress is reported via callbacks and the `logging` module,
    so the class composes with any front end (CLI today, Dagster later).
    """

    def __init__(
        self,
        api_key: str | None = None,
        max_attempts: int = 5,
        retry_sleep_seconds: float = 2.0,
        poll_interval_seconds: float = 1.0,
        poll_timeout_seconds: float = 1800.0,
    ) -> None:
        key = api_key if api_key is not None else os.environ.get("DATABENTO_API_KEY")
        if not key:
            raise RuntimeError(
                "DATABENTO_API_KEY is not set. Put it in .env and run via "
                "`uv run --env-file .env python -m src.ingestion.ingest`."
            )
        self._client = db.Historical(key)
        self.max_attempts = max_attempts
        self.retry_sleep_seconds = retry_sleep_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.poll_timeout_seconds = poll_timeout_seconds

    def _with_retries(self, call: Callable[[], T], label: str) -> T:
        """Run `call`, retrying transient 5xx gateway errors."""
        for attempt in range(1, self.max_attempts + 1):
            try:
                return call()
            except db.BentoServerError as e:
                if attempt == self.max_attempts:
                    raise
                sleep_for = self.retry_sleep_seconds * attempt
                logger.warning(
                    "%s: transient server error (%s); retrying in %.0fs (%d/%d)",
                    label,
                    e,
                    sleep_for,
                    attempt,
                    self.max_attempts - 1,
                )
                time.sleep(sleep_for)

    def estimate_cost(self, spec: ExtractSpec) -> float:
        """Estimated USD cost for the whole spec (free metadata endpoint)."""
        return self._with_retries(
            lambda: self._client.metadata.get_cost(
                dataset=spec.dataset,
                symbols=spec.symbols,
                schema=spec.data_schema,
                start=spec.start,
                end=spec.end,
            ),
            "cost estimate",
        )

    def submit_day_job(self, spec: ExtractSpec, symbol: str, day: date) -> str:
        """Submit a one-day batch job for a single symbol; return its job ID."""
        job = self._with_retries(
            lambda: self._client.batch.submit_job(
                dataset=spec.dataset,
                symbols=[symbol],
                schema=spec.data_schema,
                start=day,
                end=day + timedelta(days=1),
                split_duration="day",
            ),
            f"{symbol} {day}",
        )
        return job["id"]

    def wait_until_done(
        self,
        job_id: str,
        label: str,
        on_state: Callable[[str], None] | None = None,
    ) -> None:
        """Poll job state until done, reporting state changes via callback."""
        deadline = time.monotonic() + self.poll_timeout_seconds
        state: str | None = None
        while True:
            details = self._with_retries(
                lambda: self._client.batch.get_job_details(job_id), label
            )
            if details["state"] != state:
                state = details["state"]
                if on_state is not None:
                    on_state(state)
            if state == "done":
                return
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"{label}: job {job_id} still {state} after "
                    f"{self.poll_timeout_seconds:.0f}s"
                )
            time.sleep(self.poll_interval_seconds)

    def list_filenames(self, job_id: str, label: str) -> list[str]:
        entries = self._with_retries(
            lambda: self._client.batch.list_files(job_id), label
        )
        return [entry["filename"] for entry in entries]

    def download_file(
        self, job_id: str, filename: str, output_dir: Path, label: str
    ) -> Path:
        """Download a single job file into `output_dir`; return its local path."""
        paths = self._with_retries(
            lambda: self._client.batch.download(
                job_id=job_id,
                output_dir=str(output_dir),
                filename_to_download=filename,
            ),
            label,
        )
        return paths[0]
