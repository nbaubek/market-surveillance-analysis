-- 05_event_instant_touch.sql — THE decisive validation. Evaluates the
-- book at each sampled trade's own instant, in SEQUENCE space, with the
-- PRE-TRADE convention (interval end >= trade.sequence, so the level
-- the trade consumed is still displayed). Result on 2019-07-30
-- (sequence % 97 sample of RTH prints):
--     side='B': 133/139 (95.7%) print EXACTLY at the best ask
--     side='A':  98/ 99 (99.0%) print EXACTLY at the best bid
--     100% inside the spread; median spread 1¢
-- This (a) validates the replay and (b) re-verifies T.side = AGGRESSOR
-- side (order_flow_imbalance in the gold models is correct as built).
--
-- History of the traps this query embodies: a ts-space version
-- (ts_event < trade.ts_event) gave 0% at-touch because a trade and its
-- book update share identical ts_event; a sequence-space version with
-- valid_to_seq > s (post-event convention) gave the "all prints at the
-- exact mid of a 2¢ spread" artifact because the consumed level was
-- excluded. See 06_examples.sql for the dump that exposed it.

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
      and hour(ts_event) >= 13 and hour(ts_event) < 20
      and sequence % 97 = 0
),
book_at as (
    select s.sequence, s.side as t_side, s.price as t_price,
           max(l.price) filter (where l.side = 'B') as bb,
           min(l.price) filter (where l.side = 'A') as ba
    from st s
    join live l
      on l.sequence < s.sequence
     and (l.vts is null or l.vts >= s.sequence)   -- PRE-TRADE convention
    group by 1, 2, 3
)
select
    count(*) as trades,
    count_if(t_side = 'B') as side_B,
    count_if(t_side = 'B' and t_price = ba) as B_at_ask,   -- expect dominant
    count_if(t_side = 'B' and t_price = bb) as B_at_bid,
    count_if(t_side = 'A') as side_A,
    count_if(t_side = 'A' and t_price = bb) as A_at_bid,   -- expect dominant
    count_if(t_side = 'A' and t_price = ba) as A_at_ask,
    count_if(t_price between bb and ba) as inside,          -- expect 100%
    approx_percentile(cast(ba - bb as double), 0.5) as med_spread
from book_at
where bb is not null and ba is not null;
