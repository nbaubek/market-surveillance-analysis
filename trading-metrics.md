# Trading Metrics Catalog

Reference for every metric in the project — built and planned: what it is,
why it exists, and which database object owns it. Design decisions and
verification history live in `gold-layer-plan.md`; raw XNAS.ITCH semantics
in `dataset-info.md`; dbt column-level docs in `dbt/models/*/[model].yml`.
When you add a metric, update its model, its yml, and this file.

## Conventions (apply to every metric below)

- **Tape-based price metrics** use T rows only and **include crosses**
  (side=N prints). F rows are never summed with T (same executions, would
  double-count — Rule 1 in `gold-layer-plan.md`).
- **Cancel classification** comes from `message_flags`
  (`market_surveillance_silver.message_flags`): a C is *standalone*
  (trader-initiated) when its message group holds no T/F (execution leg)
  and no A (replace leg). Mechanical cancels are excluded by construction,
  never filtered downstream.
- **Aggressor side**: T rows carry the aggressor's side (verified).
  `taker_buy_volume + taker_sell_volume + cross_volume = trade_volume`
  holds exactly at every grain.
- **Times are UTC**. Hours/minutes with no messages produce no row;
  hours/minutes/days with messages but no trades have NULL price stats
  (not zeros). Ratios are NULL, never div-by-zero (nullif).
- **Divisions cast to DOUBLE first** — Trino `/` on two BIGINTs truncates
  (bit us once; see model comments).

## Object map

| Database object | Grain | Role |
|---|---|---|
| `market_surveillance_silver.message_flags` | one row per message | Classification flags (not metrics themselves; the vocabulary every surveillance metric below is written in) |
| `market_surveillance_gold.hourly_liquidity_metrics` | (symbol, day, UTC hour) | Core activity + surveillance + price panel |
| `market_surveillance_gold.minute_liquidity_metrics` | (symbol, day, UTC minute) | Time-weighted analytics + burst source + chart bars |
| `market_surveillance_gold.volume_profile` | (symbol, day, 10¢ price bucket) | Volume-at-price distribution |
| `market_surveillance_gold.daily_summary` | (symbol, day) | Dashboard landing table; day aggregates + everything that needs cross-hour/minute computation |

All gold tables are Iceberg, partitioned by `identity(ts_event_day)`,
rebuilt fully each run; `message_flags` is incremental-merge like silver.

---

## Built: classification flags

**Object: `market_surveillance_silver.message_flags`** (model:
`dbt/models/silver/message_flags.sql`). One row per silver message, joined
by consumers on `message_key`. Single source of truth — never re-derived.

| Flag | Meaning | Why it exists |
|---|---|---|
| `in_execution_group` | Message group contains a T or F | Marks rows belonging to an execution message (T+F+C triple, or F+C when non-printable) |
| `in_replace_group` | Group contains an A | Classifies C rows: the C is the modify leg of a replace. **Trivially TRUE for every A row** — never use it to filter adds |
| `in_cancel_group` | Group contains a C | Classifies A rows: an A whose group also holds a C is the new-order leg of a replace, not fresh liquidity |
| `is_standalone_cancel` | action=C, no execution leg, no replace leg | The trader-initiated cancel: the churn / layering-spoofing-grade count that every surveillance ratio below is built on |

## Built: activity & liquidity

**Objects: `hourly_liquidity_metrics`, `minute_liquidity_metrics`,
`daily_summary`** (identical definitions at each grain).

| Metric | Definition | Why it exists |
|---|---|---|
| `messages` | count(*) — all MBO actions | Overall market activity / system load; the burst denominator |
| `adds` | count(action='A') | New liquidity placed — the cancel-ratio denominator |
| `cancels` | count(action='C'), unfiltered | Raw cancellation volume (mechanical legs included) |
| `standalone_cancels` | count(is_standalone_cancel) | Trader-initiated cancels only: churn. The surveillance-grade cancel count; raw `cancels` overstates it by ~15% (execution + replace legs) |
| `trades` | count(action='T') | Tape prints; the visible execution count |
| `fills` | count(action='F') | Resting-order executions incl. non-printable ones — catches executions the tape never shows |
| `trade_volume` | sum(size) over T | Shares traded; the classic volume measure |
| `notional_volume` | sum(price × size) over T, DOUBLE | Dollar turnover — the only volume comparable across symbols (needed for the 6-ticker 2025 plan) |
| `cross_volume` | sum(size) over T where side='N' | Cross/auction volume — excluded from directional metrics by construction |
| `active_hours` (daily) | hours with ≥1 message | Session shape at a glance |
| `peak_message_hour` (daily) | max_by(event_hour, messages) | When activity concentrated |
| `messages_per_minute` (hourly) | messages / 60 | Mean rate normalization for hour comparisons |

## Built: surveillance indicators

**Objects: `hourly_liquidity_metrics`, `daily_summary`** (as noted).

| Metric | Definition | Why it exists |
|---|---|---|
| `cancel_to_add_ratio` | cancels / adds (both grains) | Order-book churn pressure; the classic book-stability indicator |
| `cancel_to_trade_ratio` (daily) | standalone_cancels / trades | Layering/spoofing screen: cancels per actual execution. MUST use standalone cancels — raw C counts are inflated by execution/replace legs |
| `taker_buy_volume` / `taker_sell_volume` | sum(size) over T by aggressor side | Who initiated — the building block of order-flow analysis |
| `order_flow_imbalance` (all grains) | (buy − sell) / (buy + sell), in [−1, 1] | Net directional aggression; persistent extremes flag one-sided pressure |
| `peak_minute_messages` (daily) | max per-minute message count | Burst detection peak |
| `burst_ratio` (daily) | peak / mean per-minute messages | How spiky the session was relative to its own average — normalized burst screen |
| `large_order_threshold` (daily) | p95 of genuine-add size (replace legs excluded) | Transparent, day-specific definition of "large" |
| `large_order_count` / `large_order_share` (daily) | adds above threshold; their share of genuine adds | Concentration of large liquidity placements; ~≤5% by construction, movement upward is the signal |

## Built: price & price-weighted metrics

**Objects: `hourly_liquidity_metrics`, `minute_liquidity_metrics`,
`daily_summary`**.

| Metric | Definition | Why it exists |
|---|---|---|
| `open` / `close` | first/last T price (min_by/max_by on ts_event) | Session/hour boundaries; daily close captures the closing cross |
| `high` / `low` | max/min T price | Range extremes |
| `vwap` | Σ(price×size) / Σ(size) over T | Volume-weighted fair value benchmark; day VWAP recomputed from sums, never averaged from sub-VWAPs |
| `twap` (daily) | mean of traded-minute closes | Time-weighted benchmark — the volume-agnostic counterpart to VWAP |
| `avg_trade_size` | trade_volume / trades | Print-size profile (closing-cross hours spike to ~10,900 vs ~160 daily mean) |
| `range_bps` | (high − low) / vwap × 10⁴ | Volatility proxy normalized by price level |
| `vwap_premium` | close / vwap − 1 | Where price ended vs what was actually paid — trend confirmation |
| `realized_vol_bps` (daily) | √Σ(ln(close_t/close_{t−1}))² × 10⁴ over consecutive traded minutes | Realized volatility from the tape; sparse-minute approximation |

## Built: distribution metrics

**Object: `market_surveillance_gold.volume_profile`** (model:
`dbt/models/gold/volume_profile.sql`).

| Metric | Definition | Why it exists |
|---|---|---|
| `price_bucket` / `price_bucket_floor` | floor(price × 10) in dimes; lower edge in $ | 10-cent binning (fixed width per symbol — revisit for small caps) |
| `trades` / `trade_volume` / `notional_volume` | per-bucket tape counts/sums | Volume-at-price distribution |
| `volume_share` | bucket volume / symbol-day volume (sums to 1) | The horizontal volume profile: where value actually traded; cross-symbol safe |

## Built: displayed-liquidity / book metrics (Phase 3 replay)

**Objects: `market_surveillance_gold.book_state`** (price-level
intervals; the replay engine — see `knowledge-base/prototype-evidence/` for validation
evidence) **and `market_surveillance_gold.minute_book_metrics`** (the
consumable panel; model: `dbt/models/gold/minute_book_metrics.sql`).

| Metric | Definition | Why it exists |
|---|---|---|
| `best_bid` / `best_ask` | Highest live bid / lowest live ask at the minute boundary | The touch — reference price for everything below |
| `spread` | best_ask − best_bid | Transaction cost / liquidity tightness; locked (0) is legal, crossed never (tested) |
| `mid` | (best_bid + best_ask) / 2 | Fair-value reference; anchors hidden/price-improved print analysis |
| `bid_depth_top` / `ask_depth_top` | Displayed quantity at the touch | Size actually available at the best price |
| `bid_depth_total` / `ask_depth_total` | Summed displayed depth per side | Book pressure / resilience |
| `live_levels` | Count of live price levels | Book breadth at a glance |
| `book_imbalance` | (bid_top − ask_top) / (their sum), in [−1, 1] | Displayed-liquidity imbalance — the book-side counterpart of order_flow_imbalance; persistent extremes at the touch flag one-sided quoting |

Underlying replay rules (verified; enforced by singular dbt tests):
mutation via A/C only, C.size always the quantity removed, quantities
never negative, intervals well-formed, quotes never crossed and
penny-gridded. Validated to 95.7%/99.0% exact-touch prints against the
pre-trade book at event instants.

---

## Planned (not yet built)

| Metric | Working definition | Target object | Why / status |
|---|---|---|---|
| Cancels per resting order | standalone cancels / distinct resting order_ids (A/M/C/F only — order_id=0 on T, Rule 2) | daily / new order-lifecycle model | Per-order churn intensity |
| Time-to-cancel share | share of orders standalone-cancelled within N seconds of add | order-lifecycle model | Flickering-liquidity / spoof signature; needs order_id-level event pairing |
| Modify-to-cancel ratio | replaces / standalone cancels | daily | Distinguishes re-pricing behavior from withdrawal behavior |
| Session splits | same metrics split pre-market / RTH / post-market (ET boundaries) | dimension on existing models | Pre-market microstructure differs structurally from RTH; UTC-hours-only hides it — open question 2 |
| Baselines / z-scores | per-symbol rolling distributions of the indicators above (needs the 2025 multi-symbol year) | views or a gold baseline model | "Understand normal before detecting abnormal": anomaly detection is only meaningful against a per-symbol, per-time-of-day baseline; deferred until the dataset is big enough to define one |
| Hourly/daily spread rollup | mean/median/p95 of minute_book_metrics spread per hour/day | view or small model over minute_book_metrics | Dashboard convenience; trivial aggregate, build when the dashboard needs it |

### Deliberately NOT metrics

- **Book-state flags as analytics** (`in_execution_group` etc. on T/F
  rows) — they are classification vocabulary, meaningful only through the
  consumer metrics above.
- **Raw cancel counts as churn** — always pair with `standalone_cancels`;
  the delta is mechanical book-keeping, not behavior.
