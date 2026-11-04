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

-- Gold Phase 3: book metrics at minute grain, one row per
-- (symbol, day, UTC minute WITH book content) — the top-of-book panel:
-- best bid/ask, spread, mid, top and total displayed depth, live level
-- count, top-of-book imbalance. Evaluates the book_state intervals at
-- each minute boundary of minutes that had messages (checkpoints come
-- from minute_liquidity_metrics — minutes with no messages have the
-- previous minute's book and produce no row here either).
--
-- Evaluation is timestamp-space ([ts_from, ts_to)) — fine at minute
-- boundaries; sequence-space conventions matter only for event-instant
-- consumers (see book_state's header). The max() dedupe guards against
-- same-microsecond consecutive level events straddling a boundary.
--
-- Minutes early in pre-market can be one-sided (bids quoted before the
-- first ask): the missing side is NULL, and spread/mid/imbalance are
-- NULL with it. Locked books (bid = ask) are legal market states — the
-- not-crossed test flags only bid > ask. Full rebuild every run; the
-- range join is partitioned by (symbol, ts_event_day) equality keys.

with ck as (

    select
        symbol,
        ts_event_day,
        event_minute,
        at_timezone(
            cast(ts_event_day as timestamp) + interval '1' minute * event_minute,
            'UTC'
        ) as ts
    from {{ ref('minute_liquidity_metrics') }}

),

per_ck as (

    select
        c.symbol,
        c.ts_event_day,
        c.event_minute,
        b.side,
        b.price,
        max(b.net_qty) as net_qty
    from ck c
    join {{ ref('book_state') }} b
      on b.symbol = c.symbol
     and b.ts_event_day = c.ts_event_day
     and b.ts_from <= c.ts
     and (b.ts_to is null or b.ts_to > c.ts)
    group by 1, 2, 3, 4, 5

)

-- Partition column MUST be the final column of the outermost SELECT
-- (Athena CTAS rule).
select
    symbol,
    event_minute,
    max(price) filter (where side = 'B') as best_bid,
    min(price) filter (where side = 'A') as best_ask,
    min(price) filter (where side = 'A') - max(price) filter (where side = 'B') as spread,
    (max(price) filter (where side = 'B')
     + min(price) filter (where side = 'A')) / 2 as mid,
    max_by(net_qty, price) filter (where side = 'B') as bid_depth_top,
    min_by(net_qty, price) filter (where side = 'A') as ask_depth_top,
    sum(net_qty) filter (where side = 'B') as bid_depth_total,
    sum(net_qty) filter (where side = 'A') as ask_depth_total,
    count(*) as live_levels,
    -- cast to DOUBLE before dividing (Trino BIGINT / BIGINT truncates).
    cast(max_by(net_qty, price) filter (where side = 'B')
         - min_by(net_qty, price) filter (where side = 'A') as double)
    / nullif(cast(max_by(net_qty, price) filter (where side = 'B')
         + min_by(net_qty, price) filter (where side = 'A') as double), 0)
        as book_imbalance,
    ts_event_day
from per_ck
group by symbol, ts_event_day, event_minute
