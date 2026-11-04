-- 02_snapshot_anatomy.sql — how each trading day initializes.
-- Established: exactly ONE R per day at ~07:07-07:09 UTC (~3am ET),
-- sequence 0, order_id 0, side N, no price, flags 8; ZERO messages
-- before it and ZERO messages of any kind in the 5 minutes after it.
-- The "synthetic start-of-day snapshot" is just that book-clear marker:
-- no re-injected A records exist anywhere (not even in bronze), so each
-- day's book builds organically from empty once pre-market opens at
-- 8 UTC (4am ET). Consequence: SILVER-ONLY replay is exact; bronze
-- seeding is unnecessary (bronze holds nothing extra but the R row).
-- Also established via the action mix: zero M rows (modifies arrive as
-- C+A pairs) and zero action='N' rows (side='N' occurs only as the SIDE
-- of cross T rows).

-- R anatomy per day
select cast(date_trunc('day', ts_event) as date) as day, count(*) as r_rows,
       min(ts_event) as first_ts, max(ts_event) as last_ts,
       min(sequence) as min_seq, max(sequence) as max_seq
from market_surveillance_bronze.itch_mbo
where action = 'R'
group by 1 order by 1;

-- any messages before the R? (expect 0 per day)
with r as (
    select cast(date_trunc('day', ts_event) as date) as day, min(ts_event) as r_ts
    from market_surveillance_bronze.itch_mbo where action = 'R' group by 1
)
select r.day,
       count_if(b.ts_event < r.r_ts) as msgs_before_r,   -- expect 0
       count_if(b.ts_event >= r.r_ts
                and b.ts_event < r.r_ts + interval '5' minute) as msgs_5min_after  -- expect 1 (the R itself)
from market_surveillance_bronze.itch_mbo b
join r on cast(date_trunc('day', b.ts_event) as date) = r.day
group by 1 order by 1;

-- silver action mix per day (zero M and N actions; replay mutates via
-- A and C only; C.size is uniformly the quantity to remove)
select cast(date_trunc('day', ts_event) as date) as day, action, count(*) as n
from market_surveillance_silver.itch_mbo_cleaned
group by 1, 2 order by 1, 2;
