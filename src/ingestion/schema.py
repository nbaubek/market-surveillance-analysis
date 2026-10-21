"""Executable schema contract for the bronze Iceberg ingest.

The Arrow schema is enforced on every chunk at write time (the cast target),
and `chunk_violations` applies vectorized row-level invariants via
pyarrow.compute — columnar, no Python-object validation, no local files.
"""

import pyarrow as pa
import pyarrow.compute as pc
from pyiceberg.partitioning import PartitionField, PartitionSpec
from pyiceberg.schema import Schema
from pyiceberg.transforms import DayTransform, IdentityTransform

MBO_SCHEMA = pa.schema([
    pa.field("ts_event", pa.timestamp("us", tz="UTC")),
    pa.field("rtype", pa.int16()),
    pa.field("publisher_id", pa.int32()),
    pa.field("instrument_id", pa.int64()),
    pa.field("action", pa.string()),
    pa.field("side", pa.string()),
    pa.field("price", pa.decimal128(18, 9)),
    pa.field("size", pa.int64()),
    pa.field("channel_id", pa.int16()),
    pa.field("order_id", pa.int64()),
    pa.field("flags", pa.int16()),
    pa.field("ts_in_delta", pa.int32()),
    pa.field("sequence", pa.int64()),
    pa.field("symbol", pa.string()),
    pa.field("ts_recv", pa.timestamp("us", tz="UTC")),
])

# Known MBO action codes (add, modify, reduce/clear, trade, fill).
_KNOWN_ACTIONS = ("A", "M", "C", "R", "T", "F")
_KNOWN_SIDES = ("A", "B", "N")

# Hidden-partition field IDs for the MBO bronze table.
PARTITION_SPEC_FIELD_IDS = {"ts_event_day": 1000, "symbol": 1001}


def build_partition_spec(schema: Schema) -> PartitionSpec:
    """Hidden partitions for the MBO table: days(ts_event) + identity(symbol)."""
    return PartitionSpec(
        PartitionField(
            source_id=schema.find_field("ts_event").field_id,
            field_id=PARTITION_SPEC_FIELD_IDS["ts_event_day"],
            transform=DayTransform(),
            name="ts_event_day",
        ),
        PartitionField(
            source_id=schema.find_field("symbol").field_id,
            field_id=PARTITION_SPEC_FIELD_IDS["symbol"],
            transform=IdentityTransform(),
            name="symbol",
        ),
    )


class SchemaContract:
    """Declared Arrow schema plus vectorized invariants for bronze chunks."""

    def __init__(self, schema: pa.Schema = MBO_SCHEMA) -> None:
        self.schema = schema

    def chunk_violations(self, table: pa.Table) -> int:
        """Count rows violating the invariants; NULL passes enum/range checks."""

        def ok_if_null(condition: pa.ChunkedArray) -> pa.ChunkedArray:
            return pc.fill_null(condition, True)

        action_ok = ok_if_null(
            pc.is_in(table.column("action"), value_set=pa.array(_KNOWN_ACTIONS, pa.string()))
        )
        side_ok = ok_if_null(
            pc.is_in(table.column("side"), value_set=pa.array(_KNOWN_SIDES, pa.string()))
        )
        price_ok = ok_if_null(
            pc.greater(
                table.column("price"),
                pa.scalar(0, type=self.schema.field("price").type),
            )
        )
        ts_event_ok = pc.is_valid(table.column("ts_event"))

        bad = pc.and_(
            pc.and_(pc.invert(action_ok), pc.invert(side_ok)),
            pc.or_(pc.invert(price_ok), pc.invert(ts_event_ok)),
        )
        return pc.sum(pc.fill_null(bad, False)).as_py() or 0
