-- 06_examples.sql — the example dump that exposed the off-by-one-group
-- bug. Run with the WRONG (post-event) convention
-- (vts > s.sequence): every trade prints at the EXACT midpoint of a
-- 2¢ spread — because the consumed level is missing, best bid/ask are
-- each one tick too far out. With the correct pre-trade convention the
-- same dump shows prints at the touch. Keep this as the fastest
-- regression eyeball for any future book-evaluation change.

with lv as (
    select side, price, sequence,
        sum(case when action = 'A' then size else -size end) over (
            partition by side, price
            order by channel_id, sequence,
                     case action when 'C' then 0 else 1 end, order_id
            rows between unbounded preceding and current row) as net_qty,
        lead(sequence) over (
            partition by side, price
            order by channel_id, sequence,
                     case action when 'C' then 0 else 1 end, order_id) as vts
    from market_surveillance_silver.itch_mbo_cleaned
    where ts_event_day = date '2019-07-30' and action in ('A', 'C')
),
live as (select side, price, sequence, vts from lv where net_qty > 0),
st as (
    select side, price, sequence
    from market_surveillance_silver.itch_mbo_cleaned
    where ts_event_day = date '2019-07-30' and action = 'T'
      and hour(ts_event) >= 14 and hour(ts_event) < 15
      and sequence % 997 = 0
),
book_at as (
    select s.sequence, s.side as t_side, s.price as t_price,
           max(l.price) filter (where l.side = 'B') as bb,
           min(l.price) filter (where l.side = 'A') as ba
    from st s
    join live l
      on l.sequence < s.sequence
     and (l.vts is null or l.vts >= s.sequence)   -- flip to > to see the bug
    group by 1, 2, 3
)
select t_side, t_price, bb, ba,
       cast(t_price - bb as varchar) as px_minus_bb,
       cast(ba - t_price as varchar) as ba_minus_px
from book_at
where bb is not null and ba is not null
order by sequence
limit 15;
