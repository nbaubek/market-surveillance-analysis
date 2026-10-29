# Gold Layer Plan (sketch)

Aggregates for dashboards and surveillance analytics, built by dbt from
`itch_mbo_cleaned` (silver). Output feeds a free BI tool (Tableau Public /
Power BI Desktop) via Athena, per CLAUDE.md.

Grain of the primary table: **one row per (symbol, trading day, hour)**.
Partitioning: `identity(ts_event_day)`. Data volume is tiny (hundreds of rows
per symbol-month) — full-refresh materialization is acceptable at any scale
this project will reach; revisit only if it ever hurts.

## Message semantics rules (from dataset-info.md)

Two entity systems exist in MBO data; every metric must say which one it uses.

**Message group** — rows produced by the same TotalView message. Identity:
`(ts_event_day, channel_id, sequence)`; all normalized records of one message
share it (sequence is venue-assigned per channel per trading day; symbol is
redundant since one message touches one instrument, kept defensively).
**Order lifecycle** — the resting order, identified by `order_id` (real on
A/M/C/F rows; `0` on every T row).

**Rule 1 — executions are triples.** One execution emits T + F + C sharing
one message group (the T is omitted when the message is non-printable;
cross/non-displayed trades emit a lone side=N T with no F/C). Consequences:
- `C` rows inside a T/F group are mechanical book-keeping, not trader
  cancels. **Standalone cancel** = C whose message group contains no T/F
  (Rule 1) and no A (Rule 3).
- F carries the resting order's real `order_id`; T does not.

**Rule 2 — order_id = 0 on all T rows is a placeholder** (Nasdaq never
exposes the aggressor). Lifecycle / order-size metrics may only group by
order_id on A/M/C/F rows; grouping T rows on order_id would create one
phantom mega-order ("order 0") containing the whole day's trades.

**Rule 3 — replace = C(old_id) + A(new_id) in one message group.** A C whose
group contains an A is a modify, not churn. **Churn** therefore = standalone
cancel per above: trader-initiated, execution-free, replace-free. Candidate
churn metrics: cancels per resting order, share of orders cancelled within N
seconds of add, modify-to-cancel ratio.

Counting caveat: T and F from one execution carry the SAME size — counting
or summing across both double-counts (Phase 1 definitions below respect
this).

Book-replay caveat: silver excludes the R book-clear rows, so a from-scratch
replay starts each day empty and misses depth carried over from prior
sessions (GTC orders). Databento injects a synthetic start-of-day snapshot
precisely to seed state; decide later whether replay consumes bronze
(R + snapshot state) or silver accepts the open distortion.

## Phase 1 — `hourly_liquidity_metrics` (first model)

Per (symbol, ts_event_day, hour):

| Metric | Definition |
|---|---|
| `messages` | count(*) — all MBO messages |
| `adds` | count where action = 'A' |
| `cancels` | count where action = 'C' (unfiltered; execution legs included) |
| `standalone_cancels` | count where action = 'C' and message group has no T/F and no A (Rules 1+3) |
| `trades` | count where action = 'T' — tape prints only; F excluded (same executions as T, would double-count) |
| `fills` | count where action = 'F' — resting-order executions, independent of tape printability |
| `trade_volume` | sum(size) where action = 'T' |
| `vwap` | sum(price * size) / sum(size) where action = 'T' |
| `cancel_to_add_ratio` | cancels / nullif(adds, 0) |
| `messages_per_minute` | messages / 60 |

Notes: VWAP on DECIMAL(18,9) — decide cast-to-double vs decimal division.
T-only tape metrics miss non-printable executions by definition (not on the
tape) but include crosses (side=N). Include RTH/after-hours flag? (session
hour boundaries, ET vs UTC) — open question, UTC hours as default.

## Phase 2 — surveillance-flavored metrics

| Metric | Definition | Grain question |
|---|---|---|
| `cancel_to_trade_ratio` | standalone_cancels / nullif(trades, 0) — classic layering/spoofing indicator; MUST use standalone cancels, raw C counts are inflated by execution legs (Rule 1) | fits hourly |
| `large_order_share` | share of adds with size > p95(size) per symbol-day; consider excluding replace-A legs (Rule 3) so one modify doesn't count as a fresh large order | needs daily percentile first, then hourly |
| `message_rate_burst` | max per-minute (or per-second) message count vs daily mean | needs a minute-level intermediate, not hourly |

Phase 2 likely needs message-group flags (is_execution / is_replace /
is_standalone_cancel). Decide whether they live in one intermediate model
(e.g. `message_groups`) or as CTEs repeated inside each consumer.

## Phase 3 — top-of-book reconstruction (advanced, deliberate decision)

Replay per (symbol, ts_event_day): apply A/M/C/F to order state (T carries
no resting-order information — Rule 2; F reduces the resting order by size),
then rank best bid/ask at each point in time: best bid = max(price) among
live bids, best ask = min(price) among live asks → spread series → hourly
mean/median/p95 spread. This is the most expensive query in the system
(window functions over the full message stream, per symbol-day).

See the book-replay caveat above: silver-only replay misses GTC depth
carried into the session; seeding from bronze's start-of-day snapshot is
the correct-but-more-complex option.

Alternative if the cost isn't justified: approximate spread from trade
prices (Roll estimator or high-low), documented as approximate.

## Open questions (to resolve during research)

1. Indicator thresholds: percentile basis for "large order", burst window size.
2. Session handling: UTC hours vs exchange hours (pre/post-market split)?
3. Spread: full reconstruction (phase 3) vs approximation vs skip.
4. Refresh: gold tables are small — full rebuild per run is acceptable
   (aligns with the header). If incremental is ever wanted, mirror silver's
   merge window/backfill pattern, not a high-water mark.
5. Table location: profile `s3_data_dir` currently pins dbt tables under
   `silver/` — gold needs either per-model location override
   (`external_location`) or accepting a shared prefix. Resolve when building.
6. Dashboard tool choice (Tableau Public vs Power BI Desktop) — affects
   nothing upstream, decides late.
7. Verify empirically whether `sequence` resets per trading day (assumed
   yes; analyses are day-partitioned, so containment holds either way).
8. Should message-group flags (execution / replace / standalone-cancel) be
   one materialized model or repeated CTEs in consumers?
