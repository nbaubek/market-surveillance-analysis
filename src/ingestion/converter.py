"""Streaming DBN -> contract-schema Arrow chunks (no local output files)."""

from collections.abc import Iterator
from pathlib import Path

import databento as db
import pyarrow as pa
import pyarrow.compute as pc

from src.ingestion.schema import SchemaContract

# Rows per chunk: bounds peak memory (one frame + one Arrow table at a time)
# and sets the Iceberg snapshot granularity — each chunk append commits its
# own snapshot, so fewer/larger chunks = fewer snapshots to track. 500k rows
# ≈ 3 snapshots per MSFT trading day at ~150-200 MB peak memory.
CHUNK_ROWS = 500_000

# DBN's UNDEF price sentinel (INT64_MAX) surfaces as a float around 9.22e18;
# prices at or above this threshold become NULL per the contract.
UNDEF_PRICE_THRESHOLD = 9.2e18


class DbnChunkConverter:
    """Converts one DBN file into contract-schema Arrow tables, chunk by chunk.

    Prices arrive as float64 from `to_df(price_type="float")` and are cast to
    DECIMAL(18,9). This is exact for DBN data: prices carry at most 12
    significant digits ((12,9) precision), well inside float64's 15-16 digit
    round-trip guarantee, so rounding at the 9th decimal is lossless. The
    cast is unsafe-by-design for the intentional ns->us timestamp truncation.
    """

    def __init__(self, contract: SchemaContract, chunk_rows: int = CHUNK_ROWS) -> None:
        self.contract = contract
        self.chunk_rows = chunk_rows

    def stream(self, path: Path) -> Iterator[pa.Table]:
        """Yield contract-validated Arrow chunks from a .dbn/.dbn.zst file."""
        store = db.DBNStore.from_file(path)
        for frame in store.to_df(
            price_type="float",
            pretty_ts=True,
            map_symbols=True,
            count=self.chunk_rows,
        ):
            # `to_df` puts ts_recv on the index; promote it back to a column
            frame = frame.reset_index()
            table = pa.Table.from_pandas(frame, preserve_index=False)
            yield self._to_contract(path, table)

    def _to_contract(self, path: Path, table: pa.Table) -> pa.Table:
        table = table.select(self.contract.schema.names)
        price = pc.if_else(
            pc.greater_equal(table.column("price"), UNDEF_PRICE_THRESHOLD),
            pa.scalar(None, type=pa.float64()),
            table.column("price"),
        )
        table = table.set_column(
            table.schema.get_field_index("price"), "price", price
        )
        table = table.cast(self.contract.schema, safe=False)
        violations = self.contract.chunk_violations(table)
        if violations:
            raise ValueError(
                f"{path.name}: {violations} row(s) violate the contract in a chunk"
            )
        return table
