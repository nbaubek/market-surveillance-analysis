"""Export the demo data snapshot: gold tables + order-lifetime signals.

Writes Parquet files to demo/data/ so the dashboard runs with ZERO AWS
dependency (DuckDB over local Parquet). Uses Athena UNLOAD when the
workgroup allows it, falling back to CTAS + Glue-location + DROP (the
workgroup enforces a centralized output location and has rejected
external_location before).

Aggregates rather than raw rows wherever volume would bloat the repo:
per-order lifetimes are reduced to per-minute and per-day signals in SQL.

Run from the repo root:
    AWS_PROFILE=my-dev-profile uv run python -m src.export.gold_snapshot
"""

import shutil
import sys
import tempfile
from pathlib import Path

import boto3

SILVER = '"market_surveillance_silver"."itch_mbo_cleaned"'
FLAGS = '"market_surveillance_silver"."message_flags"'
GOLD = '"market_surveillance_gold"'
ORD = "channel_id, sequence, case action when 'C' then 0 else 1 end, order_id"

OUT_DIR = Path(__file__).resolve().parents[2] / "demo" / "data"
STAGE = "s3://trading-surveillance-data/athena-results/demo-export"

QUERIES: dict[str, str] = {
    "daily_summary": f"select * from {GOLD}.daily_summary",
    "hourly_metrics": f"select * from {GOLD}.hourly_liquidity_metrics",
    "minute_metrics": f"select * from {GOLD}.minute_liquidity_metrics",
    "minute_book": f"select * from {GOLD}.minute_book_metrics",
    "volume_profile": f"select * from {GOLD}.volume_profile",
    # Spoofing signal, minute grain: genuine (non-replace) large adds vs the
    # symbol-day p95, and how many were fully removed by standalone cancels
    # within 60s of their add — the classic flickering-liquidity screen.
    "spoof_minute": f"""
        with thresholds as (
            select m.symbol, m.ts_event_day,
                   approx_percentile(m.size, 0.95) as large_thr
            from {SILVER} m
            join {FLAGS} f on m.message_key = f.message_key
            where m.action = 'A' and not f.in_cancel_group
            group by 1, 2
        ),
        large_adds as (
            select m.symbol,
                   m.ts_event_day,
                   hour(m.ts_event) * 60 + minute(m.ts_event) as event_minute,
                   m.order_id, m.size, m.ts_event
            from {SILVER} m
            join {FLAGS} f on m.message_key = f.message_key
            join thresholds t
              on t.symbol = m.symbol and t.ts_event_day = m.ts_event_day
            where m.action = 'A' and not f.in_cancel_group
              and m.size > t.large_thr
        ),
        removals as (
            select m.symbol, m.ts_event_day, m.order_id,
                   sum(case when f.is_standalone_cancel then m.size else 0 end)
                       as standalone_shares,
                   sum(case when f.in_execution_group then m.size else 0 end)
                       as exec_shares,
                   max(case when f.is_standalone_cancel then m.ts_event end)
                       as last_standalone_ts
            from {SILVER} m
            join {FLAGS} f on m.message_key = f.message_key
            where m.action = 'C'
            group by 1, 2, 3
        )
        select a.symbol, a.ts_event_day, a.event_minute,
               count(*) as large_adds,
               count_if(r.standalone_shares >= a.size and r.exec_shares = 0
                        and r.last_standalone_ts is not null
                        and r.last_standalone_ts <= a.ts_event + interval '60' second)
                   as large_cancelled_60s
        from large_adds a
        left join removals r
          on r.symbol = a.symbol and r.ts_event_day = a.ts_event_day
         and r.order_id = a.order_id
        group by 1, 2, 3
    """,
    # Lifetime distribution, day grain: orders fully removed by standalone
    # cancels (the spoof-relevant population), how long they rested.
    "lifetimes_day": f"""
        with orders as (
            select m.symbol, m.ts_event_day, m.order_id,
                   max(case when m.action = 'A' then m.ts_event end) as add_ts,
                   max(case when m.action = 'A' then m.size end) as add_size,
                   sum(case when f.is_standalone_cancel then m.size else 0 end)
                       as standalone_shares,
                   sum(case when f.in_execution_group then m.size else 0 end)
                       as exec_shares,
                   max(case when f.is_standalone_cancel then m.ts_event end)
                       as last_standalone_ts
            from {SILVER} m
            join {FLAGS} f on m.message_key = f.message_key
            where m.action in ('A', 'C')
            group by 1, 2, 3
        ),
        cancelled as (
            select symbol, ts_event_day,
                   date_diff('millisecond', add_ts, last_standalone_ts) / 1000.0
                       as lifetime_s
            from orders
            where add_ts is not null
              and standalone_shares >= add_size
              and exec_shares = 0
              and last_standalone_ts is not null
        )
        select symbol, ts_event_day,
               count(*) as standalone_cancelled_orders,
               approx_percentile(lifetime_s, 0.5) as p50_lifetime_s,
               approx_percentile(lifetime_s, 0.9) as p90_lifetime_s,
               approx_percentile(lifetime_s, 0.99) as p99_lifetime_s,
               count_if(lifetime_s <= 5) as within_5s,
               count_if(lifetime_s <= 60) as within_60s
        from cancelled
        group by 1, 2
    """,
}


def wait(athena, qid: str) -> None:
    import time

    while True:
        st = athena.get_query_execution(QueryExecutionId=qid)["QueryExecution"]["Status"]
        if st["State"] in ("SUCCEEDED", "FAILED", "CANCELLED"):
            if st["State"] != "SUCCEEDED":
                raise RuntimeError(st.get("StateChangeReason", "unknown"))
            return
        time.sleep(0.8)


def run_unload(athena, sql: str, dest: str) -> bool:
    try:
        qid = athena.start_query_execution(
            QueryString=f"unload ({sql})\nto '{dest}'\nwith (format = 'parquet')",
            WorkGroup="market-surveillance",
            QueryExecutionContext={"Database": "market_surveillance_gold"},
        )["QueryExecutionId"]
        wait(athena, qid)
        return True
    except Exception as e:  # noqa: BLE001
        print(f"  unload rejected ({str(e).splitlines()[0][:90]}), trying ctas")
        return False


def run_ctas(athena, glue, sql: str, name: str) -> str:
    qid = athena.start_query_execution(
        QueryString=f"create table {GOLD}.{name} as {sql}",
        WorkGroup="market-surveillance",
        QueryExecutionContext={"Database": "market_surveillance_gold"},
    )["QueryExecutionId"]
    wait(athena, qid)
    loc = glue.get_table(
        DatabaseName="market_surveillance_gold", Name=name
    )["Table"]["StorageLocation"]
    athena.start_query_execution(
        QueryString=f"drop table {GOLD}.{name}",
        QueryExecutionContext={"Database": "market_surveillance_gold"},
        WorkGroup="market-surveillance",
    )
    return loc


def download_dir(s3, uri: str, target: Path) -> list[Path]:
    import time

    parts = uri.replace("s3://", "").split("/", 1)
    bucket, prefix = parts[0], parts[1].rstrip("/") + "/"

    # UNLOAD finalizes its query state slightly before every data object is
    # visible on list — retry the listing briefly before giving up.
    objects: list[dict] = []
    for _ in range(6):
        objects = [
            o
            for o in s3.list_objects_v2(Bucket=bucket, Prefix=prefix).get("Contents", [])
            if o["Size"] > 0 and not o["Key"].endswith("/")
        ]
        if objects:
            break
        time.sleep(1.0)

    files: list[Path] = []
    for obj in objects:
        local = target / f"{target.name}__{Path(obj['Key']).name}"
        s3.download_file(bucket, obj["Key"], str(local))
        files.append(local)
    return files


def to_single_parquet(files: list[Path], out: Path) -> None:
    import pyarrow.parquet as pq

    tables = [pq.read_table(f) for f in files]
    table = tables[0] if len(tables) == 1 else __import__("pyarrow").concat_tables(tables)
    pq.write_table(table, out)
    for f in files:
        f.unlink()


def main() -> None:
    session = boto3.Session(profile_name="my-dev-profile")
    athena = session.client("athena", region_name="us-east-1")
    glue = session.client("glue", region_name="us-east-1")
    s3 = session.client("s3", region_name="us-east-1")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="demo-export-"))
    run_id = tempfile.mktemp(prefix="", dir="/tmp").split("/")[-1]

    try:
        for i, (name, sql) in enumerate(QUERIES.items(), 1):
            out = OUT_DIR / f"{name}.parquet"
            print(f"[{i}/{len(QUERIES)}] {name} ...", end=" ", flush=True)
            ok = run_unload(athena, sql, f"{STAGE}/{run_id}/{name}/")
            if ok:
                files = download_dir(s3, f"{STAGE}/{run_id}/{name}/", tmp)
            else:
                loc = run_ctas(athena, glue, sql, f"tmp_export_{name}")
                files = download_dir(s3, loc, tmp)
            if not files:
                raise RuntimeError(f"no parquet produced for {name}")
            to_single_parquet(files, out)
            print(f"{out.stat().st_size / 1024:.0f} KB")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\nsnapshot complete: {OUT_DIR}")


if __name__ == "__main__":
    sys.exit(main())
