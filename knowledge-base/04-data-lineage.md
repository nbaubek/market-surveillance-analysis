# 04 · Data Lineage

How every number in the dashboard originates from a raw exchange message
and flows through the pipeline. Two ideas govern the design: **each layer
owns one responsibility**, and **the day is the unit of work** (windows
are day-aligned; idempotency is per (symbol, day)).

## The path of a message

```
Databento API (XNAS.ITCH batch files)
   │  src/ingestion/ — streaming, contract-validated in memory,
   │  no local staging; idempotent per (symbol, day) via catalog check
   ▼
BRONZE  itch_mbo                     [PyIceberg append]
   │  raw 1:1 image, partitions days(ts_event), identity(symbol)
   ▼
SILVER  itch_mbo_cleaned             [dbt incremental MERGE]
   │  dedup on message_key (first ts_recv wins)
   │  excludes synthetic bookkeeping: R (start-of-day clear) +
   │  day-boundary cleanup burst (C rows in first second of UTC day)
   │  drops ts_in_delta (redundant), derives ts_event_day
   ▼
SILVER  message_flags                [dbt incremental MERGE]
   │  one row per message: message-group classification
   │  (in_execution_group / in_replace_group / in_cancel_group /
   │   is_standalone_cancel) — the vocabulary of every ratio
   ▼
GOLD    hourly_liquidity_metrics ─┐
        minute_liquidity_metrics ─┤ [full rebuild — tiny outputs]
        daily_summary ────────────┤  tape-side aggregates at 3 grains
        volume_profile ───────────┘
GOLD    book_state ──────────────── [incremental MERGE — big: 1:1 volume]
        │  the replay: price-level intervals, ΣA−ΣC per (side, price),
        │  sequence-ordered, day-partitioned windows
        ▼
        minute_book_metrics ─────── [full rebuild] book panel per minute
   ▼
EXPORT  src/export/gold_snapshot.py → demo/data/*.parquet (UNLOAD→S3→local)
   ▼
DEMO    FastHTML + DuckDB + ECharts (zero-AWS)
```

## The mechanics that make it trustworthy

**Dual-mode windows.** The three incremental models (silver, flags,
book_state) share one convention: default = 5-day rolling catch-up;
`start_date`/`end_date` vars = day-aligned backfill. Idempotent by
construction — re-processing a window updates identical rows in place.
Key subtlety: merge keys must be null-safe (`message_key` = md5 over the
message identity with 'null' sentinels), because SQL `=` never matches
NULL and system rows carry NULL prices.

**book_state intervals.** One row per live level state: net quantity at
(side, price) from event `seq_from` until the level's next event. This
representation reconstructs the book at any instant without storing a
book copy per message. Consumers choose the evaluation convention:
timestamp-space `[ts_from, ts_to)` for minute boundaries; sequence-space
with `valid_to_seq >= s` for pre-trade state at an event. Only
observable intervals are stored (a same-price replace creates a
zero-length intra-message state — filtered, and a test enforces
well-formedness).

**Tests as invariants, not decor.** 36 tests, including singular tests
that *independently recompute* the replay's running sums (non-negativity)
and the sequence↔time ordering (no inversions). The lesson that forced
this: a test on filtered output is structurally blind to the states the
filter removes.

**Reconciliation habit.** Every new layer was proven against its source:
gold sums tie to silver exactly (9,098,433 rows, 3,643,556 standalone
cancels); the replay ties to the tape (95.7/99.0% exact-touch); the
production book tied to its prototype 766/766 rows, zero mismatches.

## Where each metric family is born

| Family | Born at | From |
|---|---|---|
| activity counts | gold aggregates | silver rows + message_flags |
| tape price/volume (OHLC, VWAP, OFI, vol) | gold aggregates | T rows in silver |
| cancellation ratios & large orders | daily_summary | silver + flags (+p95 per day) |
| lifetimes & within-60s | snapshot export | silver + flags (order_id pairing) |
| spread / depth / imbalance | minute_book_metrics | book_state intervals |
| volume profile | volume_profile | T rows bucketed |

## Refresh and scale notes

- Snapshot export re-runs in seconds (UNLOAD per table; ~715 KB total).
- At the planned 2-month × 6-symbol scale, `minute_book_metrics` is the
  first model to outgrow full rebuilds — the design docs (knowledge-base/,
  open q4) prescribes mirroring silver's window pattern, never a
  high-water mark.
- The demo is deliberately decoupled from AWS: same Parquet, no
  credentials — the medallion contract means the dashboard never reads
  anything but gold.
