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

-- Gold Phase 1: hourly liquidity metrics, one row per (symbol, trading day,
-- hour) — see gold-layer-plan.md for the verified message-semantics rules
-- these definitions follow.
--
-- Message-group flags (Rules 1 and 3): all rows of one TotalView message
-- share (ts_event_day, channel_id, sequence). The window functions mark
-- whether a row's group contains an execution leg (T/F) or an add leg (A),
-- so standalone_cancels can exclude execution cancels and replace legs.
-- Computed in one pass with window functions — no self-join. The window
-- partition includes ts_event_day because sequence resets each trading day
-- (verified; see gold-layer-plan.md open question 7).
--
-- OHLC (open/high/low/close) is tape-based: prices of T rows only, which
-- include crosses (side=N) like the rest of the tape metrics. open/close
-- use min_by/max_by(price, ts_event); ties at identical ts_event resolve
-- arbitrarily (microsecond collisions on one symbol's tape are rare).
--
-- VWAP is DOUBLE: DECIMAL(18,9) * BIGINT sums to DECIMAL(38,9), and dividing
-- two decimal(38,9) values is where Athena/Trino precision blowups live;
-- BI consumers expect double anyway. NULL when the hour has no trades.
-- range_bps/vwap_premium inherit that NULL (no trades -> no high/low/vwap).
--
-- Structure: base aggregates land in the `hourly` CTE; derived ratios
-- (vwap, avg_trade_size, range_bps, vwap_premium) reference its aliases
-- from the outer query, because alias self-reference is not allowed within
-- one SELECT in Athena. The FILTER clauses keep everything in a single
-- scan of silver (no tape-only subselect).
--
-- Hours with zero messages produce no row (sparse output); BI tools
-- cross-fill. Full rebuild every run — gold volume is tiny (per the plan).

with flagged as (

    select
        symbol,
        cast(date_trunc('day', ts_event) as date) as ts_event_day,
        hour(ts_event) as event_hour,
        action,
        size,
        price,
        ts_event,
        max(case when action in ('T', 'F') then 1 else 0 end) over (
            partition by symbol,
                         cast(date_trunc('day', ts_event) as date),
                         channel_id,
                         sequence
        ) as in_execution_group,
        max(case when action = 'A' then 1 else 0 end) over (
            partition by symbol,
                         cast(date_trunc('day', ts_event) as date),
                         channel_id,
                         sequence
        ) as in_replace_group
    from {{ ref('itch_mbo_cleaned') }}

),

hourly as (

    select
        symbol,
        event_hour,
        count(*) as messages,
        count_if(action = 'A') as adds,
        count_if(action = 'C') as cancels,
        count_if(action = 'C'
                 and in_execution_group = 0
                 and in_replace_group = 0) as standalone_cancels,
        count_if(action = 'T') as trades,
        count_if(action = 'F') as fills,
        sum(if(action = 'T', size, 0)) as trade_volume,
        sum(if(action = 'T', price * size, 0)) as notional_turnover,
        cast(sum(if(action = 'T', price * size, 0)) as double)
            / nullif(cast(sum(if(action = 'T', size, 0)) as double), 0) as vwap,
        min_by(price, ts_event) filter (where action = 'T') as open,
        max_by(price, ts_event) filter (where action = 'T') as close,
        min(price) filter (where action = 'T') as low,
        max(price) filter (where action = 'T') as high,
        ts_event_day
    from flagged
    group by symbol, ts_event_day, event_hour

)

-- Partition column MUST be the final column of the outermost SELECT
-- (Athena CTAS rule).
select
    symbol,
    event_hour,
    messages,
    adds,
    cancels,
    standalone_cancels,
    trades,
    fills,
    trade_volume,
    cast(notional_turnover as double) as notional_volume,
    vwap,
    open,
    high,
    low,
    close,
    cast(trade_volume as double) / nullif(trades, 0) as avg_trade_size,
    (high - low) / nullif(vwap, 0) * 10000.0 as range_bps,
    close / nullif(vwap, 0) - 1 as vwap_premium,
    -- cast to DOUBLE before dividing: Trino's / on two BIGINTs truncates.
    cast(cancels as double) / nullif(adds, 0) as cancel_to_add_ratio,
    messages / 60.0 as messages_per_minute,
    ts_event_day
from hourly
