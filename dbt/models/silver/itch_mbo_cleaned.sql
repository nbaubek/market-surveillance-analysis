{{
    config(
        materialized='incremental',
        incremental_strategy='merge',
        unique_key='message_key',
        table_type='iceberg',
        partitioned_by=['symbol', 'ts_event_day'],
        on_schema_change='append_new_columns',
    )
}}

{% set start_var = var('start_date', none) %}
{% set end_var = var('end_date', none) %}
{% if (start_var is none) != (end_var is none) %}
    {{ exceptions.raise_compiler_error(
        "itch_mbo_cleaned: pass both start_date and end_date vars, or neither."
    ) }}
{% endif %}

-- Silver: bronze minus duplicates, at the same message-level grain.
--
-- Parametrized pipeline, two modes (incremental runs only):
--   * catch-up (default): every run re-processes the last 5 calendar days —
--       ts_event_day >= current_date - interval '5' day
--   * backfill: an explicit range replaces the window:
--       dbt run --vars '{"start_date": "2019-07-30", "end_date": "2019-08-02"}'
--   * --full-refresh ignores both and rebuilds from all of bronze.
--
-- Merge semantics on message_key: messages already in silver are matched and
-- updated in place with identical values (bronze days are immutable); messages
-- never seen are inserted. Re-running any date range is therefore idempotent —
-- no high-water mark, no forward-only constraint. Trade-off: matched rows are
-- copy-on-write rewritten even when unchanged, so overlapping windows cost more
-- than the old append strategy (fine at this volume; OPTIMIZE/VACUUM clean up).
--
-- message_key is a null-safe md5 surrogate of the message identity (symbol,
-- ts_event, sequence, order_id, action, price, size). Athena MERGE joins on
-- plain '=' and NULL never equals NULL, so a raw composite key would re-insert
-- every system row (NULL price/order_id) on each catch-up run. The 'null'
-- sentinels are unreachable real values for these numeric columns; symbol,
-- action and ts_event are not_null (tested) and need no sentinel.
--
-- The dedup CTE stays mandatory: Athena's MERGE fails at runtime if two source
-- rows match the same target row, so the merged source must carry exactly one
-- row per message_key (first ts_recv wins).
--
-- Refresh records (action = 'R', rtype 160 instrument-definition refreshes)
-- are excluded — see silver.yml.
--
-- Partition columns MUST be the final columns of the SELECT (Athena CTAS rule).

with source as (

    select *
    from {{ source('bronze', 'itch_mbo') }}

    {% if is_incremental() %}
    where
        {% if start_var is not none %}
        -- backfill mode: partition-pruned scan of the requested range.
        -- Expressed on raw ts_event (bronze has no ts_event_day column) so
        -- Iceberg's days(ts_event) transform still prunes partitions.
        -- End date inclusive: half-open upper bound covers the whole end day.
        ts_event >= cast('{{ start_var }}' as timestamp)
        and ts_event < cast('{{ end_var }}' as timestamp) + interval '1' day
        {% else %}
        -- catch-up mode: rolling window relative to today
        ts_event >= current_date - interval '5' day
        {% endif %}
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

),

keyed as (

    select
        *,
        to_hex(md5(to_utf8(concat_ws('|',
            symbol,
            cast(ts_event as varchar),
            coalesce(cast(sequence as varchar), 'null'),
            coalesce(cast(order_id as varchar), 'null'),
            action,
            coalesce(cast(price as varchar), 'null'),
            coalesce(cast(size as varchar), 'null')
        )))) as message_key
    from deduplicated
    where _dup_rank = 1 and action <> 'R'

)

-- Partition columns last (Athena CTAS rule).
select
    message_key,
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
from keyed
