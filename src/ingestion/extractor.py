"""Per-(symbol, day) extraction orchestration as a streaming iterator."""

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from src.ingestion.client import DatabentoClient
from src.ingestion.helpers import is_dbn_file, iter_days
from src.ingestion.spec import ExtractSpec


@dataclass(frozen=True)
class ExtractedDay:
    """One downloaded day-file living in scratch (deleted by the consumer)."""

    symbol: str
    day: date
    path: Path


class DatabentoExtractor:
    """Streams scratch DBN files for a spec, one (symbol, day) at a time.

    Files land in a caller-managed scratch directory — local disk is never
    an architectural layer. Days already ingested (per `skip_day`, backed by
    the Iceberg catalog) are skipped without submitting a job, which makes
    reruns idempotent and avoids duplicate billing.
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
        """Yield scratch DBN paths for every (symbol, day) not yet ingested."""
        scratch_dir.mkdir(parents=True, exist_ok=True)
        for symbol in spec.symbols:
            for day in iter_days(spec.start, spec.end):
                if self.skip_day is not None and self.skip_day(symbol, day):
                    self._emit(f"{symbol} {day}: already in bronze, skipping")
                    continue
                yield from self._extract_day(spec, symbol, day, scratch_dir)

    def _extract_day(
        self,
        spec: ExtractSpec,
        symbol: str,
        day: date,
        scratch_dir: Path,
    ) -> Iterator[ExtractedDay]:
        label = f"{symbol} {day}"
        job_id = self.client.submit_day_job(spec, symbol, day)
        self.client.wait_until_done(
            job_id, label, on_state=lambda state: self._emit(f"{label}: {state}")
        )

        for filename in self.client.list_filenames(job_id, label):
            if not is_dbn_file(filename):
                continue
            path = self.client.download_file(job_id, filename, scratch_dir, label)
            self._emit(f"{label}: downloaded {path.name}")
            yield ExtractedDay(symbol=symbol, day=day, path=path)
