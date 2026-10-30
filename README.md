# Market Surveillance

Nasdaq TotalView-ITCH market-order-book analytics: Databento → contract-validated
streaming ingestion → Apache Iceberg medallion (bronze/silver/gold) on AWS
(S3 + Glue Data Catalog + Athena), orchestrated in Python.

- Ingestion CLI: `src/ingestion/` (`uv run --env-file .env python -m src.ingestion.ingest`)
- Infrastructure: `infra/` (Terraform: bucket, Glue database, Athena workgroup)
- Transformation: `dbt/` (silver model — see "dbt: silver layer" below)
- Iceberg maintenance queries: `iceberg-maintain-queries.md`
- Data contract: `src/ingestion/schema.py` (see `CLAUDE.md` for the full contract notes)
- Source dataset reference: `dataset-info.md` (Databento XNAS.ITCH normalization)

## dbt: silver layer

Three models today:

- **`itch_mbo_cleaned`** (`dbt/models/silver/`) — an Apache Iceberg table in
  `market_surveillance_silver`, built incrementally from the bronze source.
- **`hourly_liquidity_metrics`** (`dbt/models/gold/`) — an Apache Iceberg
  table in `market_surveillance_gold`, rebuilt fully each run (gold volume
  is tiny): hourly liquidity metrics per (symbol, day, UTC hour) — messages,
  adds, standalone cancels (surveillance-grade: excludes mechanical
  execution/replace legs), tape trades, fills, volume, notional turnover,
  tape OHLC, VWAP, avg trade size, range (bps), and cancel ratios. Metric
  semantics follow the verified message rules in `gold-layer-plan.md`.
- **`daily_summary`** (`dbt/models/gold/`) — an Apache Iceberg table in
  `market_surveillance_gold`, rebuilt fully each run: one row per
  (symbol, day) — the dashboard landing table. Day OHLC (first/last tape
  print), recomputed day VWAP, totals, active hours, peak message hour, and
  cancel ratios including the Phase-2 `cancel_to_trade_ratio`.

**What it does.** Takes the raw MBO stream at the same message-level grain and:

- deduplicates on the full message identity (symbol, ts_event, sequence,
  order_id, action, price, size — first `ts_recv` wins);
- excludes `R` book-clear records (the clear-book part of Databento's
  synthetic start-of-day snapshot — not market activity; one per trading day);
- adds `message_key`, a null-safe md5 surrogate of the message identity —
  the MERGE key (raw columns can't be joined on: SQL `=` never matches NULL,
  and system rows carry NULL price/order_id);
- derives `ts_event_day` (identity partition column) and drops `ts_in_delta`
  (redundant on XNAS.ITCH: `ts_recv − ts_event`, both kept).

**Why merge.** Incremental strategy is `merge` on `message_key`: matched
messages update in place with identical values, unseen ones insert. Since
Databento delivers complete immutable days, *re-running any date range is
idempotent* — there is no high-water mark and no forward-only constraint.
`dbt test` (6 tests) enforces not-null keys and accepted action/side values,
including that R records never reappear.

### Running

From `dbt/` (profile: `dbt/profiles.yml`, Athena target, `s3_data_dir` pinned
under `silver/` to stay outside the 30-day lifecycle prefix):

```
dbt run  --select itch_mbo_cleaned                          # silver: build
dbt test --select itch_mbo_cleaned                          # silver: enforce
dbt run  --select hourly_liquidity_metrics daily_summary    # gold: build
```

With no vars, the model runs in **catch-up mode**: every run re-processes a
5-day rolling window (`ts_event >= current_date - interval '5' day`). For
the current historical dataset this is a cheap no-op; it becomes the daily
scheduled mode once ingestion moves to current data and Dagster lands.

### Backfilling

**Manual range (end date inclusive, partition-pruned):**

```
dbt run --select itch_mbo_cleaned \
  --vars '{"start_date": "2025-01-01", "end_date": "2025-01-31"}'
```

Both vars must be passed together (compiler error otherwise). `--full-refresh`
ignores the window entirely and rebuilds the table from all of bronze.

**End-to-end backfill workflow (ingest → transform):**

1. Bronze first — the ingestion CLI is idempotent per (symbol, day) via
   catalog checks, in the same two modes (`--end` is *exclusive*):
   ```
   uv run --env-file .env python -m src.ingestion.ingest \
     --symbols MSFT AAPL --start 2025-01-01 --end 2025-02-01
   ```
   Omitting `--start/--end` requests the last `--lookback-days` calendar
   days (default 5, UTC).
2. Silver second — always run dbt after ingesting, for the same dates with
   the end date inclusive (one day later than the CLI's exclusive end).
3. Re-running any step is safe: bronze skips days already in the catalog,
   silver re-merges idempotently. Gaps or corrections: re-run bronze for the
   range, then dbt with the same vars. Full rebuild after a model change:
   `dbt run --full-refresh --select itch_mbo_cleaned`.
4. Weekends/holidays inside a range are fine — Databento simply has no files
   for non-trading days, so the steps no-op for them. Calendar ranges can be
   passed directly.

## Bucket lifecycle: the 30-day rule

The rule in `infra/main.tf` is a single S3 lifecycle configuration on
`trading-surveillance-data`:

- **Filter**: prefix `athena-results/` — nothing else. `bronze/`, `silver/`,
  and a future `gold/` are structurally invisible to it.
- **Action**: expiration after 30 days, evaluated per object from its own
  creation date — a rolling cleanup, not a calendar-day wipe.
- **Permanence**: plain object deletion; the bucket has versioning disabled,
  so nothing is recoverable.

Why only this prefix: `athena-results/` is both the Athena workgroup's
query-output location and dbt-athena's *default* table location. Query
results are disposable by design, and the rule doubles as self-cleaning for
orphaned CTAS leftovers — but it also means real table data must never live
under it, or S3 would delete the table's Parquet files 30 days after write,
leaving Iceberg snapshots pointing at missing files. That is why
`dbt/profiles.yml` pins `s3_data_dir` to `silver/`, keeping every dbt-built
table out of the blast radius.

## Ingestion memory profile (measured)

Peak process RSS (Python 3.13, `resource.getrusage`), including a ~140–147 MB
baseline for interpreter + databento/pyarrow/pyiceberg imports. Ingestion
streams per (symbol, day); memory depends only on the chunk size, never on
the requested date range — the same numbers bound any execution environment
(container, Lambda, small VM).

| Chunk size | Day ingested | Rows | Peak RSS | Snapshots committed |
|---|---|---|---|---|
| 100,000 | 2019-07-30 | 1,320,332 | 239 MB (measured) | 14 |
| 500,000 (default) | ~2M row day | — | ~300–350 MB (estimated) | ~4–5 |
| whole day | 2019-08-02 | 2,740,840 | 930 MB (measured) | 1 |

Findings:

- Working memory scales at roughly **280 bytes/row** per chunk (pandas frame +
  Arrow table + Parquet writer buffers), so whole-day chunking of a ~2.7M-row
  day costs ~780 MB above baseline; a 5M+ message day would approach ~1.5 GB.
- **500k rows is the default**: a deliberate middle ground — ~300 MB peak
  regardless of day volume (comfortably within a ~1 GB Lambda or container),
  a handful of snapshots per day, files of ~8–10 MB that
  `OPTIMIZE ... REWRITE DATA` can bin-pack later (see maintenance queries).
- Override per run with `--chunk-rows` (e.g. `--chunk-rows 10000000` for one
  snapshot per trading day when snapshot granularity matters more than memory).
