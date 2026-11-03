-- s3_data_dir overrides the profile's silver/ pin: gold data lives
-- under gold/ (naming from dbt_project.yml: table_unique).
{{
    config(
        materialized='table',
        table_type='iceberg',
        partitioned_by=['ts_event_day'],
        s3_data_dir='s3://trading-surveillance-data/gold',
    )
}}

-- Gold: volume profile, one row per (symbol, trading day, price bucket) —
-- the horizontal "volume by price level" distribution for dashboards.
--
-- Buckets are fixed 10-cent bins: price_bucket is the bin index in dimes
-- (floor(price * 10)), price_bucket_floor its lower edge. Fixed width keeps
-- buckets comparable across days for one symbol; cross-symbol comparison
-- should use volume_share, not absolute buckets (a $140 stock and a $5
-- stock bin very differently — revisit if small caps land, e.g. ATR-scaled
-- bins).
--
-- Tape-based like all price metrics: T rows only, crosses (side=N)
-- included. Full rebuild every run — tens of rows per symbol-day.

with buckets as (

    select
        symbol,
        cast(date_trunc('day', ts_event) as date) as ts_event_day,
        cast(floor(price * 10) as integer) as price_bucket,
        price,
        size
    from {{ ref('itch_mbo_cleaned') }}
    where action = 'T'

),

bucketed as (

    select
        symbol,
        price_bucket,
        count(*) as trades,
        sum(size) as trade_volume,
        sum(price * size) as notional_turnover,
        ts_event_day
    from buckets
    group by symbol, ts_event_day, price_bucket

)

-- volume_share via a window over the (tiny) per-day result: each bucket's
-- share of the symbol-day's traded volume. Partition column MUST be the
-- final column of the outermost SELECT (Athena CTAS rule).
select
    symbol,
    price_bucket,
    price_bucket / 10.0 as price_bucket_floor,
    trades,
    trade_volume,
    cast(notional_turnover as double) as notional_volume,
    cast(trade_volume as double)
        / nullif(sum(trade_volume) over (partition by symbol, ts_event_day), 0)
        as volume_share,
    ts_event_day
from bucketed
