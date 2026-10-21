# Market Surveillance

Nasdaq TotalView-ITCH market-order-book analytics: Databento → contract-validated
streaming ingestion → Apache Iceberg medallion (bronze/silver/gold) on AWS
(S3 + Glue Data Catalog + Athena), orchestrated in Python.

- Ingestion CLI: `src/ingestion/` (`uv run --env-file .env python -m src.ingestion.ingest`)
- Infrastructure: `infra/` (Terraform: bucket, Glue database, Athena workgroup)
- Iceberg maintenance queries: `iceberg-maintain-queries.md`
- Data contract: `src/ingestion/schema.py` (see `CLAUDE.md` for the full contract notes)

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
