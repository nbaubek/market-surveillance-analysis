"""Pure helper functions for the extraction stage."""

from collections.abc import Iterator
from datetime import date, timedelta


def iter_days(start: date, end: date) -> Iterator[date]:
    """Yield each calendar day in [start, end) — the Databento-exclusive range."""
    day = start
    while day < end:
        yield day
        day += timedelta(days=1)


def is_dbn_file(filename: str) -> bool:
    """True for DBN data files (skip job metadata like manifest.json)."""
    return filename.endswith(".dbn") or filename.endswith(".dbn.zst")
