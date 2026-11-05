-- Replay invariant: within a price level, event order by
-- (channel_id, sequence, C-before-A, order_id) must agree with ts_event
-- order — the next event by sequence must not have an EARLIER timestamp.
-- Inversions corrupt interval endpoints (ts_from/ts_to), producing
-- phantom "live since midnight" states. This is the invariant that was
-- only ever hand-checked on MSFT; AAPL's day-boundary cleanup rows
-- (ts_event at day start, sequence from the prior session's tail)
-- violated it ~4.5k times before silver learned to exclude them.
select
    symbol,
    ts_event_day,
    side,
    cast(price as varchar) as price,
    count(*) as inverted_rows
from (
    select
        symbol,
        ts_event_day,
        side,
        price,
        ts_event,
        lead(ts_event) over (
            partition by symbol, ts_event_day, side, price
            order by channel_id,
                     sequence,
                     case action when 'C' then 0 else 1 end,
                     order_id
        ) as next_ts
    from {{ ref('itch_mbo_cleaned') }}
    where action in ('A', 'C')
)
where next_ts < ts_event
group by 1, 2, 3, 4
