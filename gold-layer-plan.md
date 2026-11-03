# Gold Layer Plan (sketch)

Aggregates for dashboards and surveillance analytics, built by dbt from
`itch_mbo_cleaned` (silver). Output feeds a free BI tool (Tableau Public /
Power BI Desktop) via Athena, per CLAUDE.md.

Grain of the primary table: **one row per (symbol, trading day, hour)**,
with supporting grains at minute (liquidity/bars), price bucket (volume
profile), and day (dashboard landing). Partitioning: `identity(ts_event_day)`
on gold tables. Aggregate data volume is tiny — full-refresh materialization
is acceptable at any scale this project will reach; revisit only if it ever
hurts. The one exception is `message_flags` (silver enrichment, one row per
message): it is incremental-merge like silver, since its volume is silver's
volume.

## Message semantics rules (from dataset-info.md)

Two entity systems exist in MBO data; every metric must say which one it uses.

**Message group** — rows produced by the same TotalView message. Identity:
`(ts_event_day, channel_id, sequence)`; all normalized records of one message
share it (sequence is venue-assigned per channel per trading day; symbol is
redundant since one message touches one instrument, kept defensively).
**Order lifecycle** — the resting order, identified by `order_id` (real on
A/M/C/F rows; `0` on every T row).

**Rule 1 — executions are triples.** One execution emits T + F + C sharing
one message group (the T is omitted when the message is non-printable —
verified: 11 F+C-only groups on 2019-07-30; cross/non-displayed trades emit
a lone side=N T with no F/C). Consequences:
- `C` rows inside a T/F group are mechanical book-keeping, not trader
  cancels. **Standalone cancel** = C whose message group contains no T/F
  (Rule 1) and no A (Rule 3).
- F carries the resting order's real `order_id`; T does not.
- State semantics (verified against Databento's order-tracking tutorial AND
  the data): **C is the only state-mutating record in the triple** — all
  fills are accompanied by a C that subtracts its size from the resting
  order; T and F are book-state no-ops. C.size = F.size in every execution
  group (27,350/27,350 on 2019-07-30), so replay applies the C exactly once
  and never double-applies F.
- The T row carries the AGGRESSOR's side (the F/C rows carry the resting
  order's side) — usable for aggressor-side analytics.

**Rule 2 — order_id = 0 on all T rows is a placeholder** (Nasdaq never
exposes the aggressor). Lifecycle / order-size metrics may only group by
order_id on A/M/C/F rows; grouping T rows on order_id would create one
phantom mega-order ("order 0") containing the whole day's trades.

**Rule 3 — replace = C(old_id) + A(new_id) in one message group.** A C whose
group contains an A is a modify, not churn (verified: 54,624 A+C groups on
2019-07-30 — more numerous than execution triples). **Churn** therefore =
standalone cancel per above: trader-initiated, execution-free, replace-free.
Candidate churn metrics: cancels per resting order, share of orders
cancelled within N seconds of add, modify-to-cancel ratio.

Counting caveat: T and F from one execution carry the SAME size — counting
or summing across both double-counts (Phase 1 definitions below respect
this).

Book-replay caveat: silver excludes the R book-clear rows, so a from-scratch
replay starts each day empty and misses depth carried over from prior
sessions (GTC orders). Databento injects a synthetic start-of-day snapshot
precisely to seed state; decide later whether replay consumes bronze
(R + snapshot state) or silver accepts the open distortion.

## Phase 1 — `hourly_liquidity_metrics` + `daily_summary` (built, verified)

Status: `dbt/models/gold/hourly_liquidity_metrics.sql` and
`dbt/models/gold/daily_summary.sql`; hourly sums tie out exactly to silver
(messages/trades/adds/cancels/fills/standalone_cancels, 4 days). Both are
Iceberg `table`s (full CTAS rebuild per run — see open question 4)
partitioned by `identity(ts_event_day)`, under
`s3://trading-surveillance-data/gold/`. Hours with zero messages produce no
row (overnight silence); hours with messages but no trades have NULL price
stats; BI tools cross-fill.

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
| `notional_volume` | sum(price * size) where action = 'T', DOUBLE (dollar turnover; cross-symbol comparable) |
| `vwap` | notional / shares over T, DOUBLE; NULL when no trades |
| `open` / `close` | first / last T price in the hour (`min_by`/`max_by(price, ts_event)`); tape-based, includes crosses (side=N) |
| `high` / `low` | max / min T price in the hour |
| `avg_trade_size` | trade_volume / trades |
| `range_bps` | (high − low) / vwap * 10000 — hourly volatility proxy |
| `vwap_premium` | close / vwap − 1 |
| `cancel_to_add_ratio` | cancels / nullif(adds, 0) — cast to DOUBLE first (Trino `/` on two BIGINTs truncates) |
| `messages_per_minute` | messages / 60 |

**`daily_summary`** — one row per (symbol, ts_event_day), aggregated from
the hourly model: summed counts/volumes, day VWAP recomputed from summed
notional/shares (not an average of hourly VWAPs), day OHLC from the
earliest/latest hour with trades (day close captures the closing cross),
`active_hours`, `peak_message_hour` (`max_by(event_hour, messages)`), and
`cancel_to_trade_ratio` (Phase 2 item: standalone_cancels / trades, the
layering/spoofing screen). The dashboard landing table.

Sanity anchors (MSFT, 2019-07-30 → 08-02): day VWAP 140.47 → 136.52 with
the 08-01 post-earnings drop (open 137.00, range 298 bps vs 108 bps on
07-30); closing-cross hour 20 has avg_trade_size ~10,900 vs ~160 day mean.

## Tier 2 — `message_flags`, minute metrics, volume profile (built, verified)

**`message_flags`** (`dbt/models/silver/message_flags.sql`) — the
materialized message-group classification (open question 8, resolved).
One row per silver message, keyed by `message_key`: an annotation table,
NOT a copy of silver — consumers join on `message_key` and take only the
flags, keeping it lean for the 2025 scale-up. Incremental merge mirroring
`itch_mbo_cleaned` (same dual-mode window; day-aligned edges are safe
because the group key contains `ts_event_day`). Columns:
`in_execution_group` (group has a T/F — Rule 1), `in_replace_group`
(group has an A — Rule 3), `in_cancel_group` (group has a C), 
`is_standalone_cancel` (C with neither: the trader-initiated / churn
count). Flag asymmetry: `in_replace_group` is trivially TRUE for every A
row (its own leg) — it classifies C rows; classify A rows with
`in_cancel_group`. **Single source of truth — never
re-derive the window logic in a consumer** (`hourly_liquidity_metrics`
was refactored to join it; sums unchanged). Verified: 9,098,433 rows =
silver rows, all keys distinct, standalone = 3,643,556 (the independently
verified count).

**`minute_liquidity_metrics`** (`dbt/models/gold/`) — minute-grain mirror
of the hourly model (same semantics, flags via the join): messages, adds,
cancels, standalone_cancels, trades, volume, notional, VWAP, OHLC per
(symbol, day, UTC minute). ~3,310 rows for 4 MSFT days. Exists because
hourly buckets cannot answer time-weighted questions: burst detection,
TWAP, realized volatility, and minute bars for charts.

**`volume_profile`** (`dbt/models/gold/`) — volume by 10-cent price bucket
per (symbol, day) over T rows: trades, volume, notional, `volume_share`
(share of symbol-day volume; sums to 1 per day). Fixed bins are
symbol-specific — cross-symbol comparisons use `volume_share`, and bin
width gets revisited when small caps land (open question 1 adjacent).

**`daily_summary` additions** (derived from the minute model):
`peak_minute_messages` (max per-minute message count), `burst_ratio`
(peak / mean over active minutes — the `message_rate_burst` screen),
`twap` (mean of traded-minute closes; silent minutes skipped, not
zero-filled), `realized_vol_bps` (sqrt of summed squared close-to-close
minute log returns over consecutive traded minutes; sparse-minute
approximation). Sanity anchors: peak minute = the 13:30 UTC (9:30 ET)
opening minute exactly (21,295 msgs on 07-30); realized vol 100–200 bps
ranking matches the range ranking (earnings day 07-31 highest); TWAP >
VWAP on the two down days (equal time-weighting vs volume-weighting).

**Aggressor-side / large-order additions** (complete the Phase 2 set):
`order_flow_imbalance` + `taker_buy_volume` / `taker_sell_volume` /
`cross_volume` at hourly, minute, and day grains (identity
buy+sell+cross = trade_volume verified exact at all grains); day-grain
`large_order_threshold` (p95 of genuine adds via `approx_percentile`),
`large_order_count`, `large_order_share` in `daily_summary`. Anchors
(MSFT, 4 days): thresholds 201–228 shares, shares 3.6–4.7% (≤5% by
construction), OFI negative all four days (the July–Aug 2019 sell-off
period), most negative −0.137 on the 07-31 earnings day.


## Phase 2 — surveillance-flavored metrics

| Metric | Definition | Status |
|---|---|---|
| `cancel_to_trade_ratio` | standalone_cancels / nullif(trades, 0) — classic layering/spoofing indicator; MUST use standalone cancels, raw C counts are inflated by execution legs (Rule 1) | built (day grain, `daily_summary`) |
| `message_rate_burst` | max per-minute message count vs daily mean | built (`peak_minute_messages` + `burst_ratio` in `daily_summary`, from the minute model) |
| `order_flow_imbalance` | (taker_buy − taker_sell) / (taker_buy + taker_sell) from T rows, which carry the AGGRESSOR's side; crosses (side=N) tracked separately in `cross_volume` and excluded from the denominator; identity buy+sell+cross = trade_volume holds exactly at every grain | built (hourly, minute, day) |
| `large_order_share` | share of adds with size > p95(size) per symbol-day; replace-A legs excluded — but NOT via `in_replace_group`, which is trivially TRUE for every A row (its own leg): use `in_cancel_group` (an A whose group also holds a C is the new-order leg of a replace pair, Rule 3) | built (day grain, `daily_summary`: threshold + count + share) |

Message-group flags decision resolved: materialized as `message_flags`
(see Tier 2 section) — consumers join, never re-derive.

## Phase 3 — top-of-book reconstruction (advanced, deliberate decision)

Replay per (symbol, ts_event_day): apply A/M/C to order state — C carries
the size delta and is the only state-mutating action (T and F are
book-state no-ops per the order-tracking tutorial; T carries no
resting-order information at all — Rule 2), then rank best bid/ask at each
point in time: best bid = max(price) among
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
4. RESOLVED: gold models are Iceberg `table` materialization — full CTAS
   rebuild per run (volume is tiny). If incremental is ever wanted, mirror
   silver's merge window/backfill pattern, not a high-water mark.
5. RESOLVED (with an adapter twist): `external_location` is REJECTED for
   Iceberg `table` builds — dbt-athena requires `s3_data_naming` containing
   `unique` (rename-based swap needs a fresh path per rebuild). Gold folder
   sets `+s3_data_naming: table_unique`; each model overrides
   `s3_data_dir='s3://trading-surveillance-data/gold'` (profile-level
   `s3_data_dir` stays pinned to `silver/` for incremental silver models).
6. Dashboard tool choice (Tableau Public vs Power BI Desktop) — affects
   nothing upstream, decides late.
7. RESOLVED (verified on silver, 2026-10-29): `sequence` resets each trading
   day (per-day min ≈ 237k–240k across all 4 ingested days) and MSFT runs
   on a single channel (channel_id = 0). The group key
   (ts_event_day, channel_id, sequence) is valid; re-check channel spread
   when more symbols are added.
8. RESOLVED: message-group flags are materialized as `message_flags`
   (`dbt/models/silver/message_flags.sql`) — one row per silver message,
   joined by consumers on `message_key`. Incremental merge with the same
   dual-mode window as `itch_mbo_cleaned` (flags are group-local and the
   group key contains the day, so day-aligned windows are self-contained).
   Built ahead of the 2025 scale-up because the minute model and the
   upcoming `large_order_share` consume it; window functions run once per
   window instead of once per consumer per rebuild. See the Tier 2 section.
