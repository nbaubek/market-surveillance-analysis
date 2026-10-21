# Gold Layer Plan (sketch)

Aggregates for dashboards and surveillance analytics, built by dbt from
`itch_mbo_cleaned` (silver). Output feeds a free BI tool (Tableau Public /
Power BI Desktop) via Athena, per CLAUDE.md.

Grain of the primary table: **one row per (symbol, trading day, hour)**.
Partitioning: `identity(ts_event_day)`. Data volume is tiny (hundreds of rows
per symbol-month) — full-refresh materialization is acceptable at any scale
this project will reach; revisit only if it ever hurts.

## Phase 1 — `hourly_liquidity_metrics` (first model)

Per (symbol, ts_event_day, hour):

| Metric | Definition |
|---|---|
| `messages` | count(*) — all MBO messages |
| `adds` | count where action = 'A' |
| `cancels` | count where action = 'C' |
| `trades` | count where action in ('T', 'F') |
| `trade_volume` | sum(size) where action in ('T', 'F') |
| `vwap` | sum(price * size) / sum(size) where action in ('T', 'F') |
| `cancel_to_add_ratio` | cancels / nullif(adds, 0) |
| `messages_per_minute` | messages / 60 |

Notes: VWAP on DECIMAL(18,9) — decide cast-to-double vs decimal division.
Include RTH/after-hours flag? (session hour boundaries, ET vs UTC) — open
question, UTC hours as default.

## Phase 2 — surveillance-flavored metrics

| Metric | Definition | Grain question |
|---|---|---|
| `cancel_to_trade_ratio` | cancels / nullif(trades, 0) — classic layering/spoofing indicator | fits hourly |
| `large_order_share` | share of adds with size > p95(size) per symbol-day | needs daily percentile first, then hourly |
| `message_rate_burst` | max per-minute (or per-second) message count vs daily mean | needs a minute-level intermediate, not hourly |

Phase 2 likely adds one intermediate model at minute grain
(e.g. `minute_activity`) — decide whether it's a model or a CTE inside the
burst computation.

## Phase 3 — top-of-book reconstruction (advanced, deliberate decision)

True bid-ask spread and depth require replaying the order book: for each
`order_id`, track state from A(dd) through M(odify)/C(ancel)/T(rade), then
rank best bid/ask at each point in time. This is the most expensive query in
the system (window functions over the full message stream, per symbol-day).
Sketch: running order-state per order_id → best bid = max(price) among live
bids, best ask = min(price) among live asks → spread series → hourly
mean/median/p95 spread.

Alternative if the cost isn't justified: approximate spread from trade prices
(Roll estimator or high-low), documented as approximate.

## Open questions (to resolve during research)

1. Indicator thresholds: percentile basis for "large order", burst window size.
2. Session handling: UTC hours vs exchange hours (pre/post-market split)?
3. Spread: full reconstruction (phase 3) vs approximation vs skip.
4. Refresh: full rebuild per run vs incremental (high-water mark like silver).
5. Table location: profile `s3_data_dir` currently pins dbt tables under
   `silver/` — gold needs either per-model location override (`external_location`)
   or accepting a shared prefix. Resolve when building.
6. Dashboard tool choice (Tableau Public vs Power BI Desktop) — affects
   nothing upstream, decides late.
