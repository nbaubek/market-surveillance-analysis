-- 03_minute_book_ctas.sql — the prototype minute book (27s for one
-- symbol-day, 766 minute rows, 0 crossed, min spread $0.01).
-- The production equivalent is dbt model minute_book_metrics (which
-- reads book_state); this query recomputes the level intervals inline.
-- Checkpoints come from minute_liquidity_metrics (message-active
-- minutes) via at_timezone to stay tz-explicit. Note the workgroup
-- rejects external_location on CTAS (centralized output) and non-Iceberg
-- CTAS cannot store timestamp-with-time-zone — hence the final cast.

create table market_surveillance_gold.prototype_minute_book_20190730 as
with ev as (
    select action, side, price, size, channel_id, sequence, order_id, ts_event
    from market_surveillance_silver.itch_mbo_cleaned
    where ts_event_day = date '2019-07-30' and action in ('A', 'C')
),
lv as (
    select side, price, channel_id, sequence, order_id, action, ts_event,
        sum(case when action = 'A' then size else -size end) over (
            partition by side, price
            order by channel_id, sequence,
                     case action when 'C' then 0 else 1 end, order_id
            rows between unbounded preceding and current row
        ) as net_qty
    from ev
),
st as (
    select side, price, net_qty, ts_event,
        lead(ts_event) over (
            partition by side, price
            order by channel_id, sequence,
                     case action when 'C' then 0 else 1 end, order_id
        ) as valid_to
    from lv
),
live as (select side, price, net_qty, ts_event, valid_to from st where net_qty > 0),
ck as (
    select at_timezone(cast(m.ts_event_day as timestamp)
                       + interval '1' minute * m.event_minute, 'UTC') as ts
    from market_surveillance_gold.minute_liquidity_metrics m
    where m.ts_event_day = date '2019-07-30'
),
per_ck as (
    -- max() dedupes same-microsecond consecutive level events straddling
    -- a checkpoint
    select c.ts, l.side, l.price, max(l.net_qty) as net_qty
    from ck c
    join live l on c.ts >= l.ts_event and (l.valid_to is null or c.ts < l.valid_to)
    group by 1, 2, 3
)
select
    cast(ts as timestamp) as minute_ts,
    max(price) filter (where side = 'B') as best_bid,
    min(price) filter (where side = 'A') as best_ask,
    max_by(net_qty, price) filter (where side = 'B') as bid_depth_top,
    min_by(net_qty, price) filter (where side = 'A') as ask_depth_top,
    sum(net_qty) filter (where side = 'B') as bid_depth_total,
    sum(net_qty) filter (where side = 'A') as ask_depth_total,
    count(*) as live_levels,
    cast(max_by(net_qty, price) filter (where side = 'B')
         - min_by(net_qty, price) filter (where side = 'A') as double)
    / nullif(cast(max_by(net_qty, price) filter (where side = 'B')
         + min_by(net_qty, price) filter (where side = 'A') as double), 0)
        as book_imbalance
from per_ck
group by ts;
