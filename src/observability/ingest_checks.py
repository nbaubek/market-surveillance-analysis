"""Payload-plane observability: semantic checks over each converted chunk.

Runs at ingestion time on the Databento API payload AFTER contract
conversion (types guaranteed by converter.py) and BEFORE the Iceberg
append. Fails closed: a failed check aborts the day's ingest — a bad
payload must never reach bronze.

Implemented with pyarrow.compute (no extra dependencies) because the
DataFrame flavor of soda-core requires dask-sql, which has no Python 3.13
wheels; the warehouse planes (silver, gold) use Soda on Athena — see
scan.py. Semantics mirror the SodaCL checks in checks/silver.yml style:
value domains and completeness.
"""

import pyarrow as pa
import pyarrow.compute as pc

ACTIONS = {"A", "M", "C", "T", "F", "R", "N"}
SIDES = {"A", "B", "N"}


def _non_r_mask(action: pa.ChunkedArray) -> pa.ChunkedArray:
    return pc.not_equal(action, "R")


def _failures(table: pa.Table) -> list[str]:
    """Return human names of failed checks for this chunk."""
    bad: list[str] = []
    action = table.column("action")

    if table.num_rows == 0:
        return ["row_count > 0"]

    for col in ("sequence", "ts_event", "symbol", "order_id"):
        if pc.any(pc.is_null(table.column(col))).as_py():
            bad.append(f"missing_count({col}) = 0")

    unknown_actions = pc.filter(action, pc.invert(pc.is_in(action, value_set=pa.array(sorted(ACTIONS), type=pa.string()))))
    if unknown_actions.length() > 0:
        bad.append("invalid_count(action) = 0 (valid: A M C T F R N)")

    bad_side = pc.filter(table.column("side"), pc.invert(pc.is_in(table.column("side"), value_set=pa.array(sorted(SIDES), type=pa.string()))))
    if bad_side.length() > 0:
        bad.append("invalid_count(side) = 0 (valid: A B N)")

    neg_size = pc.filter(table.column("size"), pc.less(table.column("size"), 0))
    if neg_size.length() > 0:
        bad.append("invalid_count(size) = 0 (valid min: 0)")

    # prices: present and positive on every non-R row (NULL price on a
    # market-action row = an UNDEF sentinel leaked past conversion)
    non_r = _non_r_mask(action)
    price = table.column("price")
    if pc.any(pc.and_(pc.is_null(price), non_r)).as_py():
        bad.append("missing_count(price) = 0 (non-R rows)")
    bad_price = pc.filter(price, pc.and_(non_r, pc.and_(pc.is_valid(price), pc.less(price, pa.scalar(1e-9, pa.float64())))))
    if bad_price.length() > 0:
        bad.append("invalid_count(price) = 0 (valid min: 1e-9, non-R rows)")

    return bad


def observe_payload(table: pa.Table, symbol: str, day: str) -> None:
    """Raise ValueError if any payload check fails on this chunk."""
    bad = _failures(table)
    if bad:
        raise ValueError(
            f"payload observability failed for {symbol} {day}: "
            + "; ".join(bad)
            + " — append aborted (fail closed)"
        )
