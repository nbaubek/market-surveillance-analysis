-- 01_replay_invariants.sql — core replay invariants for one symbol-day.
-- Established: 0 negative level states across 1,261,123 A/C events
-- (every C found sufficient quantity at its exact (side, price) level);
-- 0 timestamp inversions under sequence ordering; 3,698 levels.
-- Note the C-before-A tie-break in the ordering key: same-sequence
-- replaces at one price must order C first so net never dips negative.

-- invariant 1: running net per (side, price) must never go negative
with lv as (
    select action, side, price,
        sum(case when action = 'A' then size else -size end) over (
            partition by side, price
            order by channel_id, sequence,
                     case action when 'C' then 0 else 1 end, order_id
            rows between unbounded preceding and current row
        ) as net_qty
    from market_surveillance_silver.itch_mbo_cleaned
    where ts_event_day = date '2019-07-30' and action in ('A', 'C')
)
select count(*) as events,
       count(distinct concat_ws('|', side, cast(price as varchar))) as levels,
       count_if(net_qty < 0) as negative_states,   -- expect 0
       min(net_qty) as min_net,                    -- expect 0
       count_if(action = 'C' and net_qty = 0) as full_removals,
       count_if(action = 'C' and net_qty > 0) as partial_removals
from lv;

-- invariant 2: ts_event is monotone within a level under sequence
-- ordering (timestamp-space interval validity is sound)
select count(*) as ts_inversions                -- expect 0
from (
    select ts_event,
           lead(ts_event) over (
               partition by side, price
               order by channel_id, sequence,
                        case action when 'C' then 0 else 1 end, order_id
           ) as next_ts
    from market_surveillance_silver.itch_mbo_cleaned
    where ts_event_day = date '2019-07-30' and action in ('A', 'C')
)
where next_ts < ts_event;
