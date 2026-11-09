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

-- Gold: minute liquidity metrics, one row per (symbol, trading day, minute
-- of day, UTC). Same definitions and semantics as hourly_liquidity_metrics
-- (see that model and knowledge-base/02-dataset-and-events.md) at minute grain; it exists because
-- hourly buckets cannot answer time-weighted questions:
--
--   - burst detection (peak vs mean minute message rate) — daily_summary
--     derives burst_ratio from this table,
--   - TWAP (mean of traded-minute closes) and realized volatility (sqrt of
--     summed squared minute-to-minute log returns) — daily_summary derives
--     both from this table,
--   - minute bars for dashboard charts.
--
-- Kept lean: ratios derivable from these columns are not stored. Flags come
-- from message_flags (single source of truth). Minutes with zero messages
-- produce no row; minutes with messages but no trades have NULL price
-- columns. Full rebuild every run — ~900 rows per symbol-day at most.

with flagged as (

    select
        m.symbol,
        cast(date_trunc('day', m.ts_event) as date) as ts_event_day,
        hour(m.ts_event) * 60 + minute(m.ts_event) as event_minute,
        m.action,
        m.side,
        m.size,
        m.price,
        m.ts_event,
        f.is_standalone_cancel
    from {{ ref('itch_mbo_cleaned') }} m
    join {{ ref('message_flags') }} f
        on m.message_key = f.message_key

),

minute as (

    select
        symbol,
        event_minute,
        count(*) as messages,
        count_if(action = 'A') as adds,
        count_if(action = 'C') as cancels,
        count_if(is_standalone_cancel) as standalone_cancels,
        count_if(action = 'T') as trades,
        sum(if(action = 'T', size, 0)) as trade_volume,
        -- Aggressor-side split; identity taker_buy + taker_sell + cross = volume.
        sum(if(action = 'T' and side = 'B', size, 0)) as taker_buy_volume,
        sum(if(action = 'T' and side = 'A', size, 0)) as taker_sell_volume,
        sum(if(action = 'T' and side = 'N', size, 0)) as cross_volume,
        sum(if(action = 'T', price * size, 0)) as notional_turnover,
        cast(sum(if(action = 'T', price * size, 0)) as double)
            / nullif(cast(sum(if(action = 'T', size, 0)) as double), 0) as vwap,
        min_by(price, ts_event) filter (where action = 'T') as open,
        max_by(price, ts_event) filter (where action = 'T') as close,
        min(price) filter (where action = 'T') as low,
        max(price) filter (where action = 'T') as high,
        ts_event_day
    from flagged
    group by symbol, ts_event_day, event_minute

)

-- Partition column MUST be the final column of the outermost SELECT
-- (Athena CTAS rule).
select
    symbol,
    event_minute,
    messages,
    adds,
    cancels,
    standalone_cancels,
    trades,
    trade_volume,
    taker_buy_volume,
    taker_sell_volume,
    cross_volume,
    cast(taker_buy_volume - taker_sell_volume as double)
        / nullif(cast(taker_buy_volume + taker_sell_volume as double), 0)
        as order_flow_imbalance,
    cast(notional_turnover as double) as notional_volume,
    vwap,
    open,
    high,
    low,
    close,
    ts_event_day
from minute
