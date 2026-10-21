## Collection of queries for Iceberg tables maintenance

All runnable on Athena Query Editor directly, from dbt, or via Pyiceberg scripts.

### Snapshot timeline (ingestion audit)

```sql
SELECT snapshot_id, parent_id, committed_at, operation,
         summary['added-records']   AS added_records,
         summary['total-records']   AS total_records,
         summary['pipeline.symbol'] AS symbol,
         summary['pipeline.day']    AS ingested_day
  FROM "market_surveillance_bronze"."itch_mbo$snapshots"
 ORDER BY committed_at;
```

### Time travel

```sql
-- snapshot IDs are random 64-bit values (see $snapshots), NOT 1,2,3
SELECT count(*) FROM "market_surveillance_bronze"."itch_mbo"
FOR VERSION AS OF 5383391108533714686;

-- by point in time
SELECT count(*) FROM "market_surveillance_bronze"."itch_mbo"
FOR TIMESTAMP AS OF TIMESTAMP '2026-10-20 18:00:00';
```

### Data files inspection

```sql
SELECT file_path, record_count, file_size_in_bytes, partition
  FROM "market_surveillance_bronze"."itch_mbo$files"
 ORDER BY file_size_in_bytes DESC;
```

### Storage growth summary

```sql
SELECT count(*)              AS files,
       sum(record_count)     AS records,
       round(sum(file_size_in_bytes) / 1e9, 3) AS size_gb
  FROM "market_surveillance_bronze"."itch_mbo$files";
```

### Partition-level stats

```sql
SELECT partition, record_count, file_count
  FROM "market_surveillance_bronze"."itch_mbo$partitions";
```

### Schema / metadata history

```sql
SHOW CREATE TABLE "market_surveillance_bronze"."itch_mbo";
SELECT * FROM "market_surveillance_bronze"."itch_mbo$metadata_log_entries";
```

### Compaction (OPTIMIZE) — merge small files into larger ones

```sql
-- whole table
OPTIMIZE "market_surveillance_bronze"."itch_mbo" REWRITE DATA USING BIN_PACK;

-- one partition only
OPTIMIZE "market_surveillance_bronze"."itch_mbo" REWRITE DATA USING BIN_PACK
WHERE symbol = 'MSFT';
```

### VACUUM — expire old snapshots and delete orphaned files

Respects the retention properties below; this is what actually frees S3 storage
and shrinks metadata. Files referenced by retained snapshots are never touched.

```sql
VACUUM "market_surveillance_bronze"."itch_mbo";
```

### Orphaned table directories (sweep)

Two different kinds of "orphan" exist, with different cleanup paths:

1. **Within the table location** — files from failed writes/compactions inside
   the table's registered root. `VACUUM` (or PyIceberg `remove_orphan_files`)
   handles these automatically.
2. **Sibling directories** — dbt-athena mints a fresh `<uuid>/` directory per
   table creation. NOTE (observed): a *successful* rebuild does NOT orphan the
   old directory — Athena's `DROP TABLE` on Iceberg tables purges the
   underlying data. Sibling orphans arise from CTAS attempts that FAILED
   before commit (their staging dirs linger), which is why this sweep exists.
   Run it after any failed dbt run or manual table rebuild.

Print-first sweep — lists directory roots under a table's path, flags the
Glue-registered one as LIVE, everything else as a candidate (eyeball before
deleting):

```python
import boto3

glue = boto3.client("glue", region_name="us-east-1")
s3 = boto3.client("s3", region_name="us-east-1")
BUCKET = "trading-surveillance-data"

def registered_location(database: str, table: str) -> str:
    loc = glue.get_table(DatabaseName=database, Name=table)["Table"]["StorageDescriptor"]["Location"]
    return loc.split(f"{BUCKET}/", 1)[1]  # key prefix, no bucket

def immediate_roots(prefix: str) -> list[str]:
    resp = s3.list_objects_v2(Bucket=BUCKET, Prefix=prefix, Delimiter="/")
    return [p["Prefix"] for p in resp.get("CommonPrefixes", [])]

# dbt-athena layout: <s3_data_dir>/<database>/<table>/<uuid>/
for database, table in [("market_surveillance_silver", "itch_mbo_cleaned")]:
    prefix = f"silver/{database}/{table}/"
    live = registered_location(database, table)
    for root in immediate_roots(prefix):
        state = "LIVE" if live.startswith(root.rstrip("/")) else "orphan?"
        print(f"{state:<7} s3://{BUCKET}/{root}")
    # To delete a confirmed orphan:
    # objs = s3.list_objects_v2(Bucket=BUCKET, Prefix=root).get("Contents", [])
    # s3.delete_objects(Bucket=BUCKET, Delete={"Objects": [{"Key": o["Key"]} for o in objs]})
```

### Retention / file-size tuning

```sql
ALTER TABLE "market_surveillance_bronze"."itch_mbo" SET PROPERTIES (
  'history.expire.max-snapshot-age-ms' = '604800000',    -- 7 days of time travel
  'history.expire.min-snapshots-to-keep' = '10',
  'write.target-file-size-bytes' = '134217728'           -- 128 MB after OPTIMIZE
);
```

### PyIceberg equivalents (programmatic maintenance)

- `max_snapshot_age_ms=7 * 24 * 3600 * 1000` - How many milliseconds from snapshot creation date to wait before deletion of that particular snapshot.
- `min_snapshots_to_keep=10` - Think of this as a **safety net**
    - If your table is very active: If you committed 50 new snapshots over the last 7 days, Iceberg will delete the older ones but leave you with those 50 recent snapshots.
    - If your table is completely idle: If no new data has been written to the table for a month, all your snapshots are technically older than 7 days. If you didn't have a minimum floor, Iceberg would delete all historical snapshots, leaving you with only 1 (the current state). Because min_snapshots_to_keep=10 is set, Iceberg will refuse to delete the 10 most recent snapshots, safeguarding your ability to rollback or look at recent history even during quiet periods.

```python
from datetime import timedelta

from pyiceberg.catalog import load_catalog

catalog = load_catalog(
    "glue",
    **{
        "type": "glue",
        "warehouse": "s3://trading-surveillance-data",
        "glue.region": "us-east-1",
        "s3.region": "us-east-1",
    },
)
table = catalog.load_table("market_surveillance.itch_mbo")

# snapshot expiry + orphan cleanup, same semantics as Athena VACUUM
table.expire_snapshots(
    max_snapshot_age_ms=7 * 24 * 3600 * 1000,
    min_snapshots_to_keep=10,
)
table.remove_orphan_files(older_than=timedelta(days=3))
```

Note: This is an alternative to using milliseconds for `max_snapshot_age_ms`:

```python
from datetime import datetime, timedelta

# Let the library handle the milliseconds conversion under the hood
cutoff_time = datetime.now() - timedelta(days=7)
table.expire_snapshots().older_than(cutoff_time).commit()
```
