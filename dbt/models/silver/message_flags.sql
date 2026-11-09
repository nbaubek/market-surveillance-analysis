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

-- Silver enrichment: message-group classification per message (Rules 1 and 3
-- in knowledge-base/02-dataset-and-events.md). One row per silver message, keyed by message_key —
-- an ANNOTATION table, not a copy of silver: consumers join on message_key
-- and take only the flags, keeping this table lean for the 2025 scale-up.
--
-- Why materialized (design decision documented in the knowledge base): the flags
-- are window functions over the full message stream; computing them as CTEs
-- inside every consumer re-runs those windows per model per rebuild. Here
-- they run once per window; consumers do a cheap key join instead. This is
-- the single source of truth for the classification — never copy the window
-- logic into a consumer.
--
-- Incremental merge mirrors itch_mbo_cleaned exactly: 5-day rolling
-- catch-up window by default, explicit start_date/end_date vars for
-- backfill, both-or-neither. Window edges are day-aligned and the group key
-- (ts_event_day, channel_id, sequence) contains the day — sequence resets
-- each trading day (open question 7) — so a message group never spans a
-- window edge and re-deriving any whole day is self-contained.
--
-- Flags are BOOLEAN; is_standalone_cancel is the pre-computed conjunction
-- so consumers can use it directly (trader-initiated cancel: no execution
-- leg, no replace leg — the churn / layering-spoofing-grade count).
--
-- Asymmetry to keep in mind when filtering: in_replace_group ("group has
-- an A") is TRUE for every A row — its own leg makes it so; it classifies
-- C rows. To classify A rows (replace-A leg vs genuine new add), use
-- in_cancel_group ("group has a C"): an A in a group that also contains a
-- C is the new-order leg of a replace pair (Rule 3), not fresh liquidity.

{% set start_var = var('start_date', none) %}
{% set end_var = var('end_date', none) %}
{% if (start_var is none) != (end_var is none) %}
    {{ exceptions.raise_compiler_error(
        "message_flags: pass both start_date and end_date vars, or neither."
    ) }}
{% endif %}

with windowed as (

    select
        message_key,
        symbol,
        ts_event,
        action,
        channel_id,
        sequence,
        cast(date_trunc('day', ts_event) as date) as ts_event_day,
        max(case when action in ('T', 'F') then 1 else 0 end) over (
            partition by symbol,
                         cast(date_trunc('day', ts_event) as date),
                         channel_id,
                         sequence
        ) as _execution_leg,
        max(case when action = 'A' then 1 else 0 end) over (
            partition by symbol,
                         cast(date_trunc('day', ts_event) as date),
                         channel_id,
                         sequence
        ) as _replace_leg,
        max(case when action = 'C' then 1 else 0 end) over (
            partition by symbol,
                         cast(date_trunc('day', ts_event) as date),
                         channel_id,
                         sequence
        ) as _cancel_leg
    from {{ ref('itch_mbo_cleaned') }}
    {% if is_incremental() %}
    -- Filter on raw ts_event (not the derived day) so partition pruning
    -- still applies. End date inclusive, matching silver's convention.
    where
    {% if start_var is not none %}
        ts_event >= cast('{{ start_var }}' as timestamp)
        and ts_event < cast('{{ end_var }}' as timestamp) + interval '1' day
    {% else %}
        ts_event >= current_date - interval '5' day
    {% endif %}
    {% endif %}

)

-- Partition columns MUST be the final columns (Athena CTAS rule).
select
    message_key,
    action,
    channel_id,
    sequence,
    _execution_leg = 1 as in_execution_group,
    _replace_leg = 1 as in_replace_group,
    _cancel_leg = 1 as in_cancel_group,
    action = 'C' and _execution_leg = 0 and _replace_leg = 0
        as is_standalone_cancel,
    symbol,
    ts_event_day
from windowed
