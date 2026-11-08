-- 04_minute_stats_and_control.sql — spread/depth sanity plus the
-- wrong-book CONTROL that shows the replay signal is not coincidence.
-- Established: RTH median minute spread 1¢ (penny-tight book), and the
-- at-touch rate collapses from ~27% (real book, minute boundary) to
-- 2.3% (book shifted one hour). The remaining gap to 100% at minute
-- boundaries is within-minute book movement + genuinely off-touch
-- prints (7% of prints are sub-penny: hidden/price-improved), which
-- query 05 resolves at event granularity.

-- spread/depth aggregates (all minutes, two-sided)
select count(*) as minutes,
       count_if(best_bid >= best_ask) as crossed,              -- expect 0
       min(best_ask - best_bid) as min_spread,                 -- expect 0.01
       approx_percentile(cast(best_ask - best_bid as double), 0.5) as med_spread,
       avg(cast(best_ask - best_bid as double)) as avg_spread,
       max(best_ask - best_bid) as max_spread,
       round(avg(bid_depth_top)) as avg_bid_top,
       round(avg(ask_depth_top)) as avg_ask_top
from market_surveillance_gold.prototype_minute_book_20190730
where best_bid is not null and best_ask is not null;

-- control: same trades against a book shifted one hour (expect ~2-3%)
with t as (
    select side, price, ts_event
    from market_surveillance_silver.itch_mbo_cleaned
    where ts_event_day = date '2019-07-30' and action = 'T'
      and hour(ts_event) >= 13 and hour(ts_event) < 20
),
j as (
    select t.side, t.price, b.best_bid, b.best_ask
    from t
    join market_surveillance_gold.prototype_minute_book_20190730 b
      on cast(date_trunc('minute', t.ts_event) as timestamp)
         = b.minute_ts + interval '1' hour
)
select count_if(side = 'B' and price between best_ask - 0.01 and best_ask + 0.01) as buys_1c,
       count_if(side = 'B') as buys,
       count_if(side = 'A' and price between best_bid - 0.01 and best_bid + 0.01) as sells_1c,
       count_if(side = 'A') as sells
from j;
