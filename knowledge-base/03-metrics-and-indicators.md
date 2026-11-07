# 03 · Metrics and Indicators

Every metric the project computes, grouped by the market question it
answers — not alphabetically. Each entry follows one template:

**CONCEPT** (the market idea) → **FORMULA** → **EXAMPLE** (real numbers
from this project's data) → **INTERPRETATION** → **SURVEILLANCE
RELEVANCE** → **LIMITATIONS** → **SOURCE** (the dbt object that owns it).

Standing rule for every entry: these are **indicators, not evidence**.

---

## Group 1 — Activity · "How active was the market?"

### messages
**CONCEPT** Total event count — the raw pulse of the feed.
**FORMULA** `count(*)` per (symbol, day, hour/minute).
**EXAMPLE** MSFT 2019-07-30: 1,320,331 messages; AAPL the same day: 1,492,763.
**INTERPRETATION** Context denominator. MSFT days here run 1.3–2.9M messages; activity roughly doubles on the earnings day.
**SURVEILLANCE RELEVANCE** The baseline every "unusual activity" claim is measured against; also the normalization base for burst ratio.
**LIMITATIONS** Counts plumbing as well as trading (adds that never trade); says nothing about direction.
**SOURCE** `hourly_liquidity_metrics`, `minute_liquidity_metrics`, `daily_summary`.

### adds
**CONCEPT** New displayed orders — liquidity *offered*.
**FORMULA** `count(action='A')` (replace legs excluded where the distinction matters — see standalone cancels).
**EXAMPLE** MSFT 07-30: 622,608 adds.
**INTERPREILLATION** The quoting rate; denominator of cancel-to-add.
**SURVEILLANCE** Quoting without trading is the raw material of layering.
**LIMITATIONS** An add is a promise, revocable for free — never conflate displayed with intent.
**SOURCE** hourly/minute/daily models.

### cancels (raw)
**CONCEPT** All C rows, including mechanical legs.
**FORMULA** `count(action='C')`.
**EXAMPLE** MSFT 07-30: 638,515.
**INTERPRETATION** ~15% of these are bookkeeping (execution legs + replace legs), not decisions — which is exactly why the raw count is *not* used for surveillance ratios.
**LIMITATIONS** Inflated by mechanics; always prefer `standalone_cancels`.
**SOURCE** hourly/minute/daily.

### standalone_cancels ★
**CONCEPT** Cancels a human or algorithm *chose*: no execution, no replace in the message group.
**FORMULA** `count_if(is_standalone_cancel)` — flag from `message_flags`.
**EXAMPLE** MSFT total: 3,643,556 of 4,329,825 raw cancels across 4 days.
**INTERPRETATION** The honest churn measure; every surveillance ratio's numerator.
**SURVEILLANCE** Spoofing's defining activity, measured cleanly.
**LIMITATIONS** Legitimate market making lives here too — ratio and context matter, never the count alone.
**SOURCE** `message_flags` → all aggregate models.

### trades / fills
**CONCEPT** Tape prints (T) vs resting-order executions (F).
**FORMULA** `count(action='T')` / `count(action='F')`.
**EXAMPLE** MSFT 07-30: 31,858 trades, 27,350 fills.
**INTERPRETATION** Same executions counted from two sides: T = the visible tape (incl. crosses; T+F double-counts — T and F carry identical size).
**SURVEILLANCE** fills > trades gap = non-printable executions (dark-side liquidity trading against displayed orders).
**LIMITATIONS** T misses non-printable executions; F misses the print's market context.
**SOURCE** all aggregate models.

---

## Group 2 — Volume · "How much was traded?"

### trade_volume
**CONCEPT** Shares traded (T only).
**EXAMPLE** MSFT 07-30: 5,102,764 shares.
**LIMITATIONS** Not comparable across price levels — see notional.
**SOURCE** all aggregate models.

### notional_volume ★
**CONCEPT** Dollar turnover: `sum(price × size)` over T.
**EXAMPLE** MSFT 07-30: $716.8M; AAPL 4-day mean: $2.73B/day vs MSFT $1.38B.
**INTERPRETATION** The cross-symbol currency: share counts lie across price levels, dollars don't.
**SURVEILLANCE** Cross-ticker comparison and "thin day" context (close-marking prefers thin sessions).
**SOURCE** all aggregate models.

### cross_volume / volume_share
**CONCEPT** Auction prints (side=N) / a bucket's share of the day's volume.
**EXAMPLE** Closing-cross minutes can carry more volume than the whole prior hour.
**INTERPRETATION** cross_volume excludes itself from directional metrics by construction.
**SOURCE** aggregate models; `volume_profile`.

---

## Group 3 — Price · "How did prices behave?"

### open / high / low / close
**CONCEPT** First/last print, extremes (T rows; crosses included).
**EXAMPLE** MSFT 07-31: O 140.80 H 140.80 L 135.08 C 136.24 — open *is* the high: straight-down day.
**INTERPRETATION** Tape-based shape; the daily close captures the closing cross.
**LIMITATIONS** Print extremes, not quote extremes; sub-penny prints can fall outside the penny-grid book.
**SOURCE** all aggregate models.

### vwap ★
**CONCEPT** Volume-weighted average price — what the average participant actually paid.
**FORMULA** `Σ(price×size) / Σ(size)` over T; day VWAP recomputed from sums, never averaged from sub-VWAPs.
**EXAMPLE** MSFT 07-30: 140.47 while close was 140.32 (premium −0.11%).
**INTERPRETATION** The fair-value benchmark; the reference for premium.
**SOURCE** all aggregate models.

### twap
**CONCEPT** Time-weighted average — equal weight per traded minute.
**EXAMPLE** MSFT 07-31: TWAP 138.35 vs VWAP 137.45 — TWAP lags because volume concentrated at the lows.
**INTERPRETATION** The volume-agnostic counterfactual; VWAP−TWAP gaps flag volume-at-extremes.
**SOURCE** `daily_summary`.

### range_bps / realized_vol_bps ★
**CONCEPT** Intraday movement, two ways: (high−low)/vwap and the sqrt of summed squared minute log-returns.
**EXAMPLE** MSFT: 107 bps (quiet day) vs 416 bps (earnings day); realized vol 164 vs 248 bps mean across symbols.
**INTERPRETATION** range is one extreme pair; realized vol weighs every minute.
**SURVEILLANCE** Context gate: an indicator on a 400bps day means something different than on a 100bps day.
**SOURCE** all aggregate models (+ intraday cumulative in the demo).

### vwap_premium
**CONCEPT** close / vwap − 1: where the final print landed vs fair value.
**EXAMPLE** MSFT days: −0.11%, −0.88%, −0.81%, +0.32%.
**SURVEILLANCE** The marking-the-close outcome metric; large premium + late one-sided OFI is the pattern (or index rebalancing — the honest twin).
**SOURCE** hourly/daily.

### avg_trade_size
**CONCEPT** Shares per print.
**EXAMPLE** MSFT ~148 mean; closing-cross hour ~10,900.
**INTERPRETATION** Sudden size shifts flag participant changes (retail ↔ institutional).
**SOURCE** hourly/daily.

---

## Group 4 — Order flow · "Which side was more aggressive?"

### taker_buy_volume / taker_sell_volume
**CONCEPT** Volume by aggressor side (T rows carry the aggressor's side — event-verified: side=B prints at the ask, 95.7% exact).
**EXAMPLE** MSFT 07-31: 3.06M bought vs 4.02M sold aggressively.
**SOURCE** all aggregate models.

### order_flow_imbalance (OFI) ★
**CONCEPT** Net aggression: (buy − sell) / (their sum), in [−1, +1].
**EXAMPLE** MSFT 07-30..08-02: −0.03, −0.14, −0.03, −0.11 — persistent selling pressure through the earnings week.
**INTERPRETATION** Signed pressure on one axis; crosses excluded from the denominator by construction (identity buy+sell+cross=volume holds exactly at every grain).
**SURVEILLANCE** The marking-the-close lens's core signal: last-30-minute OFI + premium.
**LIMITATIONS** Tape-side only — says nothing about displayed liquidity (that's book_imbalance's job; they are different instruments).
**SOURCE** all aggregate models.

---

## Group 5 — Cancellation behavior · "How much activity was withdrawn?"

### cancel_to_add_ratio
**CONCEPT** Book churn pressure: raw cancels / adds.
**EXAMPLE** MSFT days ≈ 1.01–1.03 (near-parity churn).
**INTERPRETATION** Order-book stability; >1 sustained means the book replaces itself faster than it fills.
**SOURCE** hourly/daily.

### cancel_to_trade_ratio ★
**CONCEPT** standalone_cancels / trades — cancels per actual execution.
**FORMULA** Must use standalone cancels: raw C inflates ~15% mechanically.
**EXAMPLE** MSFT 4-day mean 13.9 vs AAPL 6.8 — MSFT is the churn-heavy book.
**INTERPRETATION** The classic layering/spoofing screen: liquidity advertised and withdrawn relative to liquidity actually traded.
**LIMITATIONS** Market makers live at high values by design; compare against the symbol's own baseline.
**SOURCE** `daily_summary`.

### large_order_threshold / count / share ★
**CONCEPT** "Large" defined per symbol-day: p95 of genuine (non-replace) add size.
**EXAMPLE** MSFT 07-30: threshold 228 shares, 26,571 large adds, 4.68% share; AAPL 07-30: threshold 126.
**INTERPRETATION** Self-calibrating: no absolute size assumption; share ≤ ~5% by construction, movement upward marks concentration.
**SURVEILLANCE** The spoofing lens's definition of "big order" — shown on the dashboard as context.
**SOURCE** `daily_summary`.

### order lifetimes (p50/p90, cancelled-within-60s) ★
**CONCEPT** How long fully-standalone-cancelled orders actually rested.
**EXAMPLE** AAPL 07-31: p50 74.9s, p90 1,711s; 79.6% gone within 60s (triggers the amber alert tile >30%).
**INTERPRETATION** Genuine interest waits; flickering doesn't. p50/p90 + the large-add cancel *pattern* tell the story.
**LIMITATIONS** Short lifetime alone is not spoofing — market makers cancel fast for a living (indicator, not evidence; deliberately no p99/within-5s on the dashboard to avoid over-reading).
**SOURCE** snapshot `lifetimes_day` / `spoof_minute` (exported from silver+message_flags).

---

## Group 6 — Intensity · "Did activity suddenly accelerate?"

### messages_per_minute / peak_minute_messages / burst_ratio ★
**CONCEPT** Mean rate; the peak minute; and peak/mean — how spiky the day was, normalized.
**EXAMPLE** MSFT 07-30 peak minute 21,295 messages (the 9:30 open — exactly minute 810), burst ratio 12.4.
**INTERPRETATION** burst_ratio is the comparable form (absolute peaks favor high-volume days).
**SURVEILLANCE** Cancel cascades arrive as message bursts; the layering lens reads burst + imbalance together.
**SOURCE** hourly/daily.

### active_hours / live_levels
**CONCEPT** Hours with any messages; count of live price levels in the book.
**EXAMPLE** 16 active hours/day; AAPL peaks ~3,300 live levels in RTH.
**INTERPRETATION** Session shape and book breadth at a glance.
**SOURCE** daily; `minute_book_metrics`.

---

## Group 7 — Displayed liquidity · "What was offered in the book?"

*All Group 7 metrics come from the price-level replay (book_state) — the
displayed book, validated to 95.7–99.0% exact-touch agreement with prints
at event instants (wrong-book control: 2.3%).*

### best_bid / best_ask / mid / spread
**CONCEPT** The touch and its gap.
**EXAMPLE** MSFT mid-day 07-30: 140.25/140.26 — penny-tight; pre-market can be tens of cents wide; median RTH spread = 1¢.
**INTERPRETATION** Instant transaction cost; locked (bid=ask) is a legal state, crossed (bid>ask) never occurs in validated data.
**SOURCE** `minute_book_metrics`.

### bid/ask_depth_top / bid/ask_depth_total
**CONCEPT** Displayed quantity at the touch / summed across all levels.
**EXAMPLE** MSFT 16:00 07-30: top depth 726 vs 701 — balanced; RTH mean ~400–530 shares at the touch.
**SURVEILLANCE** One side ballooning then collapsing = the layering cancel cascade; both breathing together is just an active market.
**SOURCE** `minute_book_metrics`.

### book_imbalance ★
**CONCEPT** Displayed buy-vs-sell liquidity balance at the top of book.
**FORMULA** `(bid_depth_top − ask_depth_top) / (bid_depth_top + ask_depth_top)` — **top of book only**; depth totals span all levels (a distinction the dashboard tags explicitly).
**EXAMPLE** best bid 800 shares, best ask 200 → (800−200)/(800+200) = **+0.6**: displayed bid quantity triple the ask.
**INTERPRETATION** + = bid-heavy displayed supply of buyers; − = ask-heavy; near 0 = balanced.
**SURVEILLANCE** Layering's signature: imbalance pinned near ±1 while price refuses to move, then evaporating in a cascade — real one-sided demand usually *trades*.
**LIMITATIONS** Displayed orders can be cancelled; imbalance does not establish buying or selling intent. Not total-depth.
**SOURCE** `minute_book_metrics`.

---

## Group 8 — Price distribution · "Where did trading concentrate?"

### volume profile (buckets, volume_share)
**CONCEPT** Volume by 10¢ price bucket; each bucket's share of the day.
**EXAMPLE** MSFT 07-30: 40.9% of volume at $140.30–140.39 (the close area; VWAP 140.47, close 140.32).
**INTERPRETATION** Fat bars = value areas (agreement); thin stretches = pockets crossed without commitment.
**SURVEILLANCE** Thin pockets near the close are cheap to push through — close-markers prefer them; cross-symbol comparisons use volume_share, never absolute buckets.
**LIMITATIONS** Fixed bins are symbol-specific; magnitude only, no direction.
**SOURCE** `volume_profile`.

---

## Deliberately not on the dashboard

`messages`, raw `fills`, `active_hours` (plumbing context), `open/high/low`
(range + close + premium already carry the shape), lifetime p99/within-5s
(invites over-reading), `mid` (spread carries it), raw `cancels` (inflated).
Full audit in the demo's design history; the rule is *interpretation over
catalogue*.
