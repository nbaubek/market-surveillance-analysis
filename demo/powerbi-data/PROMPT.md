# Power BI Dashboard — Build Instructions for Claude Code

You are building a Power BI dashboard for a market surveillance project.
The data files are in the same directory as this prompt (CSV format).
Use the Power BI MCP server to create the semantic model and report.

## Data Files

| File | Grain | Key columns |
|---|---|---|
| `daily_summary.csv` | (symbol, ts_event_day) | symbol, ts_event_day, vwap, twap, open, high, low, close, trade_volume, notional_volume, order_flow_imbalance, realized_vol_bps, range_bps, vwap_premium, cancel_to_add_ratio, cancel_to_trade_ratio, standalone_cancels, large_order_share, large_order_threshold, large_order_count, burst_ratio, peak_minute_messages, trades, messages |
| `hourly_metrics.csv` | (symbol, ts_event_day, event_hour) | symbol, event_hour, ts_event_day, messages, adds, cancels, standalone_cancels, trades, fills, trade_volume, notional_volume, vwap, open, high, low, close, order_flow_imbalance, cancel_to_add_ratio |
| `minute_metrics.csv` | (symbol, ts_event_day, event_minute) | symbol, event_minute (0–1439 UTC), ts_event_day, messages, adds, cancels, standalone_cancels, trades, trade_volume, taker_buy_volume, taker_sell_volume, cross_volume, order_flow_imbalance, vwap, open, high, low, close |
| `minute_book.csv` | (symbol, ts_event_day, event_minute) | symbol, event_minute, best_bid, best_ask, spread, mid, bid_depth_top, ask_depth_top, bid_depth_total, ask_depth_total, live_levels, book_imbalance |
| `volume_profile.csv` | (symbol, ts_event_day, price_bucket) | symbol, price_bucket (dimes), price_bucket_floor, trades, trade_volume, notional_volume, volume_share |
| `spoof_minute.csv` | (symbol, ts_event_day, event_minute) | symbol, event_minute, large_adds, large_cancelled_60s |
| `lifetimes_day.csv` | (symbol, ts_event_day) | symbol, standalone_cancelled_orders, p50_lifetime_s, p90_lifetime_s, within_5s, within_60s |

## Data Semantics (read before building)

- **symbol**: stock ticker (MSFT, AAPL)
- **ts_event_day**: trading day (date)
- **event_hour**: UTC hour (0–23); RTH = 13–20 UTC (9:30–16:00 ET)
- **event_minute**: UTC minute of day (0–1439); RTH = 810–1200
- **vwap**: volume-weighted average price — fair value benchmark
- **order_flow_imbalance (OFI)**: (buy − sell) / total, in [−1, +1]; aggressor balance
- **standalone_cancels**: trader-initiated cancels (mechanical legs excluded)
- **book_imbalance**: (bid depth − ask depth) / total, at the touch; top-of-book only
- **spread**: best ask − best bid (dollars); 0.01 = penny-tight
- **price_bucket / price_bucket_floor**: 10-cent price bins (price_bucket is in dimes)
- All prices in USD. All timestamps in UTC.

## Semantic Model

### Relationships
- `daily_summary[symbol, ts_event_day]` → 1:* to all other tables on same keys
- Create a date dimension table from distinct ts_event_day values
- Mark it as a date table for time intelligence

### Measures (DAX)

Create these measures in the semantic model:

```
Total Volume = SUM(daily_summary[trade_volume])
Total Notional = SUM(daily_summary[notional_volume])
Avg VWAP = AVERAGE(daily_summary[vwap])
Avg OFI = AVERAGE(daily_summary[order_flow_imbalance])
Avg Realized Vol = AVERAGE(daily_summary[realized_vol_bps])
Median Spread Cents = MEDIAN(minute_book[spread]) * 100
Cancel to Trade = DIVIDE(SUM(daily_summary[standalone_cancels]), SUM(daily_summary[trades]))
Large Order Share Pct = SUM(daily_summary[large_order_share]) * 100
VWAP Premium Pct = AVERAGE(daily_summary[vwap_premium]) * 100
Burst Ratio = AVERAGE(daily_summary[burst_ratio])
```

### Calculated Columns

In `minute_metrics`:
```
Time Label = FORMAT(TIME(FLOOR(event_minute/60,0), MOD(event_minute,60), 0), "hh:nn")
Session = SWITCH(TRUE(), event_minute >= 810 && event_minute < 1200, "RTH", "Pre/Post")
```

In `volume_profile`:
```
Price Label = FORMAT(price_bucket_floor, "0.00")
```

## Report Pages

Build three pages. Theme: dark background (#1A1A19), cards with subtle borders, blue #3987E5 for primary series, red #E66767 for negative/sell, orange #D95926 for secondary.

---

### Page 1: Market Overview

**Top row — KPI cards (6 across):**
- Close (last close price), VWAP (avg), Total Volume (sum, format M), Total Notional (sum, format $B), OFI (avg, 3 decimals, +/- color), Realized Vol (avg, "bps" suffix)

**Left half — Price and VWAP (line chart):**
- X: event_minute (from minute_metrics)
- Y: close (line, 2px blue), vwap (line, 1.5px orange, 65% opacity)
- Legend: Last Price (blue), VWAP (orange)
- Visual: VWAP drawn UNDER the close line (order matters for readability)
- Add a slicer for symbol and ts_event_day on this page

**Right half — Aggressor Flow (stacked bar chart):**
- X: event_minute
- Y: taker_buy_volume (blue, above zero), taker_sell_volume (red, below zero — use negative values)
- Title: "Aggressor Flow (buy ↑ / sell ↓)"

**Bottom left — Volume Profile (bar chart, horizontal):**
- X: trade_volume
- Y: Price Label (from volume_profile, sorted ascending)
- Color: single blue
- Title: "Volume Profile (where trading concentrated)"

**Bottom right — Daily comparison (table):**
- Columns: ts_event_day, vwap, trade_volume, notional_volume, realized_vol_bps, order_flow_imbalance, cancel_to_trade_ratio, vwap_premium
- Conditional formatting: OFI color-scaled (blue for positive, red for negative)

---

### Page 2: Surveillance

**Section header:** "1 · SPOOFING — flickering large orders"

**Left — Large Order Cancel Behaviour (clustered column chart):**
- X: event_minute (from spoof_minute)
- Y: large_adds (blue), large_cancelled_60s (red, stacked)
- Title: "Large adds vs cancelled within 60s"

**Right — Cancel Pressure (line chart):**
- X: event_minute (from minute_metrics)
- Y: standalone_cancels (red line), trades (blue line)
- Title: "Standalone cancels vs trades (per minute)"

**KPI row for spoofing:**
- Cancelled Orders (from lifetimes_day), Median Lifetime (p50_lifetime_s), % Gone <60s (within_60s / standalone_cancelled_orders)

**Section header:** "2 · LAYERING — stacked displayed depth"

**Left — Top-of-Book Imbalance (bar chart, diverging):**
- X: event_minute (from minute_book)
- Y: book_imbalance
- Positive values: blue (bid-heavy), negative values: red (ask-heavy)
- Title: "Book Imbalance (bid-heavy ↑ / ask-heavy ↓)"

**Right — Displayed Depth (area chart):**
- X: event_minute
- Y: bid_depth_total (blue area), ask_depth_total (red area)
- Title: "Displayed Depth by Side"

**Section header:** "3 · MARKING THE CLOSE — late-session pressure"

**Left — Order-Flow Imbalance (column chart, diverging):**
- X: event_minute (from minute_metrics)
- Y: order_flow_imbalance
- Positive: blue, negative: red
- Title: "OFI Through the Day (watch the final 30 minutes)"

**Right — Close vs VWAP (bar chart, diverging):**
- X: ts_event_day (from daily_summary)
- Y: vwap_premium * 100 (percentage)
- Positive: blue, negative: red
- Title: "Close vs VWAP Premium (where the close landed vs fair value)"

---

### Page 3: Methodology (text boxes)

No charts. Create text boxes with:
- Title: "Methodology"
- Section 1: "The four questions" — What happened? / What did the market look like? / Was something unusual? / Does this deserve investigation?
- Section 2: "The three screens" — Spoofing, Layering, Marking the Close (one paragraph each)
- Section 3: "Honest limits" — single venue, displayed size only, no participant identities, conduct ≠ intent

---

## Slicers (on every page except Methodology)

- **Symbol**: dropdown, from daily_summary[symbol]
- **Trading Day**: dropdown or date slicer, from daily_summary[ts_event_day]

## Formatting Rules

- Background: #1A1A19 (dark)
- Card background: #232322 with 1px border #383835
- Text primary: #F0EFEC, secondary: #C3C2B7, muted: #898781
- Grid lines: #2C2C2A (solid, hairline)
- All axes: muted text, no axis titles unless non-obvious
- Numbers: no unnecessary decimals; prices to 2dp; percentages to 1dp with % suffix
- Titles: 14px semibold, left-aligned
- Tooltips: enabled on all visuals

## Publishing

After building:
1. Save as `market-surveillance.pbix`
2. File → Publish → Publish to Power BI Service
3. In the Service: File → Embed report → Website or portal
4. Copy the public embed URL
