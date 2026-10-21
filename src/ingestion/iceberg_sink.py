"""Generic Iceberg sink: table bootstrap and chunked transactional append."""

from collections.abc import Callable, Iterator
from datetime import date, datetime, time, timedelta, timezone

import pyarrow as pa
from pyiceberg.catalog import Catalog
from pyiceberg.expressions import And, EqualTo, GreaterThanOrEqual, LessThan
from pyiceberg.io.pyarrow import _pyarrow_to_schema_without_ids
from pyiceberg.partitioning import PartitionSpec
from pyiceberg.schema import Schema, assign_fresh_schema_ids

from src.ingestion.schema import SchemaContract

DEFAULT_TABLE_PROPERTIES = {
    "format-version": "2",
    "write.parquet.compression-codec": "zstd",
}


class IcebergTableSink:
    """Append-only Iceberg sink for a single table.

    Everything table-specific — identifier, location, contract, partition
    spec, properties — is injected; the class owns only the generic
    lifecycle: create-if-missing, (symbol, day) existence checks, and
    chunked transactional appends. Layer-specific wiring lives with each
    table's definition (see schema.py for the bronze MBO table).

    Each chunk is appended inside one transaction per call, so memory stays
    bounded at one chunk even for partitioned tables (streaming
    RecordBatchReader appends are not yet supported for those in pyiceberg).
    A failure mid-append may leave orphan data files that no snapshot
    references; those are cleaned up by standard Iceberg orphan-file
    maintenance, not by this class.

    `has_day` assumes the table carries `symbol` and `ts_event` columns.
    """

    def __init__(
        self,
        catalog: Catalog,
        identifier: str,
        location: str,
        contract: SchemaContract,
        partition_spec_builder: Callable[[Schema], PartitionSpec],
        properties: dict[str, str] = DEFAULT_TABLE_PROPERTIES,
    ) -> None:
        self.catalog = catalog
        self.identifier = identifier
        self.location = location
        self.contract = contract
        self.partition_spec_builder = partition_spec_builder
        self.properties = properties

    def ensure_table(self) -> None:
        """Create the table from the contract if it does not exist yet."""
        schema = assign_fresh_schema_ids(
            _pyarrow_to_schema_without_ids(self.contract.schema)
        )
        self.catalog.create_table_if_not_exists(
            identifier=self.identifier,
            schema=schema,
            partition_spec=self.partition_spec_builder(schema),
            location=self.location,
            properties=self.properties,
        )

    def has_day(self, symbol: str, day: date) -> bool:
        """Idempotency check against the catalog, not local disk."""
        start = datetime.combine(day, time.min, tzinfo=timezone.utc)
        end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=timezone.utc)
        row_filter = And(
            EqualTo("symbol", symbol),
            And(GreaterThanOrEqual("ts_event", start), LessThan("ts_event", end)),
        )
        table = self.catalog.load_table(self.identifier)
        return table.scan(row_filter=row_filter).count() > 0

    def append_chunks(
        self,
        chunks: Iterator[pa.Table],
        snapshot_properties: dict[str, str],
    ) -> int:
        """Append all chunks in one transaction; return the row count."""
        table = self.catalog.load_table(self.identifier)
        rows = 0
        with table.transaction() as tx:
            for chunk in chunks:
                tx.append(df=chunk, snapshot_properties=snapshot_properties)
                rows += chunk.num_rows
        return rows
