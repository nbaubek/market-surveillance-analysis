{{
    config(
        materialized='incremental',
        incremental_strategy='merge',
        unique_key='message_key',
        table_type='iceberg',
        partitioned_by=['symbol', 'ts_event_day'],
        on_schema_change='append_new_columns',
        s3_data_dir='s3://trading-surveillance-data/gold',
    )
}}

-- Gold Phase 3: order-book state as PRICE-LEVEL INTERVALS — the validated
-- replay (see knowledge-base/02-dataset-and-events.md, feasibility steps 1-2, and
-- phase3-prototype/ for the evidence). One row per live level state:
-- the displayed quantity at (side, price) from event `seq_from` until the
-- level's next event (`valid_to_seq`), NULL end = still live. This interval
-- form reconstructs the book at ANY point without storing a book copy per
-- message — that is the entire point of the representation.
--
-- Replay rules (all verified empirically):
--   * Mutation = A (insert) and C (subtract) only; zero M rows exist
--     (modifies arrive as C+A pairs), and C.size is ALWAYS the quantity
--     to remove — standalone, execution leg, or replace leg alike.
--   * Only rows with net_qty > 0 are kept (live intervals); a C that
--     zeroes a level simply ends the previous interval (no row emitted).
--   * The window partition includes ts_event_day: sequence resets daily,
--     so without it a multi-day build would carry levels across days.
--   * Ordering is (channel_id, sequence, C-before-A tie-break, order_id).
--     Timestamps CANNOT order events: a trade and its book update share
--     identical ts_event (4,186/4,186 sampled groups). Same-sequence
--     ties (a replace at one price) order C first so net never dips.
--
-- Evaluation conventions for CONSUMERS (the interval end decides what
-- you get — this bit the prototype twice):
--   * at a timestamp t (minute boundaries): ts_from <= t < ts_to
--   * pre-trade at sequence s (trade's own group not yet applied):
--     seq_from < s AND (valid_to_seq IS NULL OR valid_to_seq >= s)
--   * post-event at sequence s: same with valid_to_seq > s
--
-- Incremental merge on the triggering event's message_key, mirroring
-- message_flags: 5-day catch-up default, start_date/end_date backfill,
-- day-aligned windows (a day is always reprocessed whole, keeping
-- valid_to_seq consistent). At scale this is the project's largest table
-- (~1.2M rows per symbol-day) — never full-rebuild it casually.

{% set start_var = var('start_date', none) %}
{% set end_var = var('end_date', none) %}
{% if (start_var is none) != (end_var is none) %}
    {{ exceptions.raise_compiler_error(
        "book_state: pass both start_date and end_date vars, or neither."
    ) }}
{% endif %}

with ev as (

    select
        message_key,
        symbol,
        action,
        side,
        price,
        size,
        channel_id,
        sequence,
        order_id,
        ts_event,
        cast(date_trunc('day', ts_event) as date) as ts_event_day
    from {{ ref('itch_mbo_cleaned') }}
    where action in ('A', 'C')
    {% if is_incremental() %}
    -- Day-aligned window on raw ts_event (end date inclusive), matching
    -- silver/message_flags; partition pruning stays intact.
    and ts_event >=
    {% if start_var is not none %}
        cast('{{ start_var }}' as timestamp)
        and ts_event < cast('{{ end_var }}' as timestamp) + interval '1' day
    {% else %}
        current_date - interval '5' day
    {% endif %}
    {% endif %}

),

lv as (

    select
        message_key,
        symbol,
        side,
        price,
        sequence,
        ts_event,
        ts_event_day,
        sum(case when action = 'A' then size else -size end) over (
            partition by symbol, ts_event_day, side, price
            order by channel_id,
                     sequence,
                     case action when 'C' then 0 else 1 end,
                     order_id
            rows between unbounded preceding and current row
        ) as net_qty,
        lead(sequence) over (
            partition by symbol, ts_event_day, side, price
            order by channel_id,
                     sequence,
                     case action when 'C' then 0 else 1 end,
                     order_id
        ) as valid_to_seq,
        lead(ts_event) over (
            partition by symbol, ts_event_day, side, price
            order by channel_id,
                     sequence,
                     case action when 'C' then 0 else 1 end,
                     order_id
        ) as ts_to
    from ev

)

-- Partition columns MUST be the final columns (Athena CTAS rule).
-- The interval guard drops UNOBSERVABLE intra-message states: a replace
-- at the same price (C+A in one group, C ordered first) yields a state
-- whose next level event is the A at the SAME sequence — a zero-length
-- interval, empty in both sequence and timestamp space (same-group
-- events share ts_event). The A's own state row covers the post-message
-- book, so nothing observable is lost (asserted by the well-formedness
-- test; 7,601 such rows existed before the guard).
select
    message_key,
    side,
    price,
    net_qty,
    sequence as seq_from,
    valid_to_seq,
    ts_event as ts_from,
    ts_to,
    symbol,
    ts_event_day
from lv
where net_qty > 0
  and (valid_to_seq is null or valid_to_seq > sequence)
