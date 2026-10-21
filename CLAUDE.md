## Instructions for Claude Code

- Don't make assumptions and rush without explicit instructions
- Use `uv` and never `pip` commands to manage project's virtual environment
- Don't add "Co-Authored by Claude" messages to commit body of any commit 

---

## ELT stages

### Schema Returned from Databento

The data that's returned from Databento must have this schema if expressed in DuckDB data types:

```
┌───────────────┬──────────────────────────┐
│  column_name  │       column_type        │
│    varchar    │         varchar          │
├───────────────┼──────────────────────────┤
│ ts_event      │ TIMESTAMP WITH TIME ZONE │
│ rtype         │ SMALLINT                 │
│ publisher_id  │ INTEGER                  │
│ instrument_id │ BIGINT                   │
│ action        │ VARCHAR                  │
│ side          │ VARCHAR                  │
│ price         │ DECIMAL(18,9)            │
│ size          │ BIGINT                   │
│ channel_id    │ SMALLINT                 │
│ order_id      │ BIGINT                   │
│ flags         │ SMALLINT                 │
│ ts_in_delta   │ INTEGER                  │
│ sequence      │ BIGINT                   │
│ symbol        │ VARCHAR                  │
│ ts_recv       │ TIMESTAMP WITH TIME ZONE │
└───────────────┴──────────────────────────┘
```

**Contract notes:**

- **price**: Databento's native precision is fixed-point (12,9) — 9 decimal digits at 1e-9 scale (e.g., 368.400000000). The contract stores `DECIMAL(18,9)`; the unscaled DBN integer is cast at ingestion into the bronze Iceberg table.
- **Signed integers**: Iceberg/Glue/Athena have no unsigned types, so DBN's unsigned columns map to the next-larger signed type.
- **Timestamps**: stored at microsecond precision (`timestamp("us", tz="UTC")` in Arrow). Iceberg `TIMESTAMP` is microsecond-precision; DBN's nanoseconds are truncated at conversion.


### Ingestion Pipeline

No persistent local staging. Data streams from Databento in chunks, is converted and validated against the schema contract in memory, and is written directly to the bronze Iceberg table. Local disk is scratch only, never an architectural layer. Idempotency is determined by the catalog (Iceberg snapshots / partitions already ingested), not by files on disk.

### **Strategy for Medallion Layers (Bronze ➡️ Silver ➡️ Gold)**

All three layers are Apache Iceberg tables managed through the Glue Data Catalog and queried with Athena. Iceberg owns the physical data-file layout and hidden partitioning — directory structure is table-internal and not part of the contract.

Catalog convention: one Glue database per layer — `market_surveillance_bronze`, `market_surveillance_silver`, `market_surveillance_gold` — so the Athena editor's database selector doubles as the layer selector.

```
s3://trading-surveillance-data/
├── bronze/
│   └── itch_mbo/            <-- Iceberg table: contract-validated MBO data
├── silver/
│   └── itch_mbo_cleaned/    <-- Iceberg table: deduplicated, cleaned data
└── gold/
    └── hourly_liquidity_metrics/ <-- Iceberg table: aggregates for dashboards
```

1. **Bronze Layer**: stream Databento data through the schema contract and append to the Iceberg bronze table. Hidden partitions: `days(ts_event)`, `identity(symbol)`.
2. **Silver Layer**: deduplicated, cleaned data.
3. **Gold Layer**: light aggregate business views (e.g., bid-ask spreads, hourly order volumes), pointed at a free BI tool (Tableau Public or Power BI Desktop) via Athena.




## Athena query results

Athena query results land under `s3://trading-surveillance-data/athena-results/`

---

## Orchestration


---


## Data Modeling



