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
-- VWAP is DOUBLE: DECIMAL(18,9) * BIGINT sums to DECIMAL(38,9), and dividing
-- two decimal(38,9) values is where Athena/Trino precision blowups live;
-- BI consumers expect double anyway. NULL when the hour has no trades.
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

)

-- Partition column MUST be the final column of the SELECT (Athena CTAS rule).
-- Alias references within the same SELECT are not allowed in Athena, hence
-- the repeated count_if() calls for derived ratios.
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
    cast(sum(if(action = 'T', price * size, 0)) as double)
        / nullif(cast(sum(if(action = 'T', size, 0)) as double), 0) as vwap,
    count_if(action = 'C') / nullif(count_if(action = 'A'), 0) as cancel_to_add_ratio,
    count(*) / 60.0 as messages_per_minute,
    ts_event_day
from flagged
group by symbol, ts_event_day, event_hour
