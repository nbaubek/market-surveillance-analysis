{{
    config(
        materialized='incremental',
        incremental_strategy='append',
        table_type='iceberg',
        partitioned_by=['symbol', 'ts_event_day'],
        on_schema_change='append_new_columns',
    )
}}

-- Silver: bronze minus duplicates, at the same message-level grain.
--
-- append + batch deduplication: the standard pattern for high-volume message
-- data. Each run reads only rows newer than the high-water mark in this
-- table, deduplicates the batch on the full message identity (symbol,
-- ts_event, sequence, order_id, action, price, size — first ts_recv wins),
-- and appends. Databento delivers complete immutable days, so no
-- late-arrival lookback buffer is needed; the plain high-water mark is
-- correct and a rerun after a mid-run failure never duplicates (anything
-- already appended sits at or below max(ts_event) and is excluded).
--
-- Consequence of append: an already-appended day is never reprocessed —
-- reruns are forward-only. Rebuilding a day requires --full-refresh.

with source as (

    select *
    from {{ source('bronze', 'itch_mbo') }}

    {% if is_incremental() %}
    where ts_event > (select max(ts_event) from {{ this }})
    {% endif %}

),

deduplicated as (

    select
        *,
        row_number() over (
            partition by symbol, ts_event, sequence, order_id, action, price, size
            order by ts_recv
        ) as _dup_rank
    from source

)

-- Refresh records (action = 'R', rtype = 160): Databento prefixes each day
-- with an instrument-definition refresh that maps instrument_id -> symbol.
-- They carry no price and are not market activity — one per trading day —
-- so bronze keeps them faithfully but silver excludes them.

-- Partition columns MUST be the final columns of the SELECT (Athena CTAS rule).
select
    ts_event,
    rtype,
    publisher_id,
    instrument_id,
    action,
    side,
    price,
    size,
    channel_id,
    order_id,
    flags,
    ts_in_delta,
    sequence,
    ts_recv,
    symbol,
    cast(date_trunc('day', ts_event) as date) as ts_event_day
from deduplicated
where _dup_rank = 1 and action <> 'R'
