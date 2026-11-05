-- Replay invariant: a level's displayed quantity must never go negative.
-- IMPORTANT: this recomputes the running sum INDEPENDENTLY from silver —
-- book_state itself only stores net_qty > 0 rows, so testing that table
-- can never see a negative state (the first version of this test was
-- structurally blind for exactly that reason and missed the AAPL
-- day-boundary corruption). A violation means a C subtracted from a
-- level without sufficient resting quantity at its (side, price).
with lv as (
    select
        sum(case when action = 'A' then size else -size end) over (
            partition by symbol, ts_event_day, side, price
            order by channel_id,
                     sequence,
                     case action when 'C' then 0 else 1 end,
                     order_id
            rows between unbounded preceding and current row
        ) as net_qty
    from {{ ref('itch_mbo_cleaned') }}
    where action in ('A', 'C')
)
select net_qty, count(*) as negative_rows
from lv
where net_qty < 0
group by 1
