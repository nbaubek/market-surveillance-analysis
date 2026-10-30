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

-- Gold: daily summary, one row per (symbol, trading day) — the dashboard
-- landing table. Aggregates hourly_liquidity_metrics, so every metric
-- semantics caveat there applies here unchanged (verified message rules
-- in gold-layer-plan.md).
--
-- Day open/close come from the hourly open/close values: open = open of the
-- earliest hour that had trades (pre-market hours with book activity but
-- no prints contribute NULL and are filtered out), close = close of the
-- latest such hour — the last print of the day, i.e. after the closing
-- cross. min/max ignore NULL low/high rows for hours without trades.
--
-- Day VWAP is recomputed from summed notional/shares (not averaged from
-- hourly VWAPs) — the correct volume weighting. range_bps and
-- vwap_premium are NULL for days with no trades.
--
-- Full rebuild every run — gold volume is tiny (per the plan).

with daily as (

    select
        symbol,
        count(*) as active_hours,
        max_by(event_hour, messages) as peak_message_hour,
        sum(messages) as messages,
        sum(adds) as adds,
        sum(cancels) as cancels,
        sum(standalone_cancels) as standalone_cancels,
        sum(trades) as trades,
        sum(fills) as fills,
        sum(trade_volume) as trade_volume,
        sum(notional_volume) as notional_volume,
        sum(notional_volume) / nullif(sum(trade_volume), 0) as vwap,
        min_by(open, event_hour) filter (where open is not null) as open,
        max_by(close, event_hour) filter (where close is not null) as close,
        min(low) as low,
        max(high) as high,
        ts_event_day
    from {{ ref('hourly_liquidity_metrics') }}
    group by symbol, ts_event_day

)

-- Partition column MUST be the final column of the outermost SELECT
-- (Athena CTAS rule).
select
    symbol,
    active_hours,
    peak_message_hour,
    messages,
    adds,
    cancels,
    standalone_cancels,
    trades,
    fills,
    trade_volume,
    notional_volume,
    vwap,
    open,
    high,
    low,
    close,
    cast(trade_volume as double) / nullif(trades, 0) as avg_trade_size,
    (high - low) / nullif(vwap, 0) * 10000.0 as range_bps,
    close / nullif(vwap, 0) - 1 as vwap_premium,
    cast(cancels as double) / nullif(adds, 0) as cancel_to_add_ratio,
    cast(standalone_cancels as double) / nullif(trades, 0) as cancel_to_trade_ratio,
    ts_event_day
from daily
