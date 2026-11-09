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
-- in knowledge-base/02-dataset-and-events.md).
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
-- Minute-derived columns come from minute_liquidity_metrics:
--   peak_minute_messages / burst_ratio — max and max/mean of per-minute
--     message counts over ACTIVE minutes (minutes with no messages produce
--     no row), the message-rate burst screen;
--   twap — mean of traded-minute closes (minute-grain time-weighted
--     approximation; silent minutes between trades are skipped, not filled);
--   realized_vol_bps — sqrt of summed squared minute-to-minute log returns
--     (close-to-close over consecutive traded minutes), * 10000. Sparse
--     minutes make this an approximation of true realized variance.
--
-- Aggressor-side split (order_flow_imbalance) sums the hourly taker
-- volumes: T rows carry the aggressor's side; crosses (side=N) are tracked
-- in cross_volume and excluded from the imbalance denominator.
--
-- Large-order screen: share of adds above the symbol-day p95 add size
-- (approx_percentile), replace-A legs excluded via message_flags (Rule 3).
-- By construction the share is ~5% or less; deviation upward marks
-- concentration of large liquidity placements.
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
        sum(taker_buy_volume) as taker_buy_volume,
        sum(taker_sell_volume) as taker_sell_volume,
        sum(cross_volume) as cross_volume,
        sum(notional_volume) as notional_volume,
        sum(notional_volume) / nullif(sum(trade_volume), 0) as vwap,
        min_by(open, event_hour) filter (where open is not null) as open,
        max_by(close, event_hour) filter (where close is not null) as close,
        min(low) as low,
        max(high) as high,
        ts_event_day
    from {{ ref('hourly_liquidity_metrics') }}
    group by symbol, ts_event_day

),

minute_stats as (

    select
        symbol,
        ts_event_day,
        max(messages) as peak_minute_messages,
        cast(max(messages) as double)
            / nullif(cast(avg(messages) as double), 0) as burst_ratio,
        avg(cast(close as double)) as twap
    from {{ ref('minute_liquidity_metrics') }}
    group by symbol, ts_event_day

),

minute_returns as (

    select
        symbol,
        ts_event_day,
        ln(dclose / lag(dclose) over (
            partition by symbol, ts_event_day
            order by event_minute
        )) as log_return
    from (
        select
            symbol,
            ts_event_day,
            event_minute,
            cast(close as double) as dclose
        from {{ ref('minute_liquidity_metrics') }}
        where close is not null
    )

),

realized_vol as (

    select
        symbol,
        ts_event_day,
        sqrt(sum(pow(log_return, 2))) * 10000.0 as realized_vol_bps
    from minute_returns
    where log_return is not null
    group by symbol, ts_event_day

),

-- Large-order screen (Phase 2): share of adds above the symbol-day p95
-- add size. Replace-A legs are excluded via in_cancel_group (Rule 3: an A
-- whose group also contains a C is the new-order leg of a replace pair,
-- not fresh liquidity — note in_replace_group itself is TRUE for every A
-- row and cannot be used to filter adds). Population = genuine new adds.
add_sizes as (

    select
        m.symbol,
        cast(date_trunc('day', m.ts_event) as date) as ts_event_day,
        m.size
    from {{ ref('itch_mbo_cleaned') }} m
    join {{ ref('message_flags') }} f
        on m.message_key = f.message_key
    where m.action = 'A'
      and not f.in_cancel_group

),

add_thresholds as (

    select
        symbol,
        ts_event_day,
        approx_percentile(size, 0.95) as large_order_threshold,
        count(*) as eligible_adds
    from add_sizes
    group by symbol, ts_event_day

),

large_orders as (

    select
        a.symbol,
        a.ts_event_day,
        count_if(a.size > t.large_order_threshold) as large_order_count
    from add_sizes a
    join add_thresholds t
        on a.symbol = t.symbol and a.ts_event_day = t.ts_event_day
    group by a.symbol, a.ts_event_day

)

-- Partition column MUST be the final column of the outermost SELECT
-- (Athena CTAS rule). LEFT JOINs: a day always has minute rows when it has
-- hourly rows, but the join must not drop a day if a source is somehow
-- empty (NULLs are the honest signal, not missing rows).
select
    d.symbol,
    d.active_hours,
    d.peak_message_hour,
    d.messages,
    d.adds,
    d.cancels,
    d.standalone_cancels,
    d.trades,
    d.fills,
    d.trade_volume,
    d.notional_volume,
    d.vwap,
    d.open,
    d.high,
    d.low,
    d.close,
    cast(d.trade_volume as double) / nullif(d.trades, 0) as avg_trade_size,
    (d.high - d.low) / nullif(d.vwap, 0) * 10000.0 as range_bps,
    d.close / nullif(d.vwap, 0) - 1 as vwap_premium,
    cast(d.cancels as double) / nullif(d.adds, 0) as cancel_to_add_ratio,
    cast(d.standalone_cancels as double) / nullif(d.trades, 0) as cancel_to_trade_ratio,
    d.taker_buy_volume,
    d.taker_sell_volume,
    d.cross_volume,
    cast(d.taker_buy_volume - d.taker_sell_volume as double)
        / nullif(cast(d.taker_buy_volume + d.taker_sell_volume as double), 0)
        as order_flow_imbalance,
    ms.peak_minute_messages,
    ms.burst_ratio,
    ms.twap,
    rv.realized_vol_bps,
    t.large_order_threshold,
    lo.large_order_count,
    cast(lo.large_order_count as double)
        / nullif(t.eligible_adds, 0) as large_order_share,
    d.ts_event_day
from daily d
left join minute_stats ms
    on d.symbol = ms.symbol and d.ts_event_day = ms.ts_event_day
left join realized_vol rv
    on d.symbol = rv.symbol and d.ts_event_day = rv.ts_event_day
left join add_thresholds t
    on d.symbol = t.symbol and d.ts_event_day = t.ts_event_day
left join large_orders lo
    on d.symbol = lo.symbol and d.ts_event_day = lo.ts_event_day
