# 06 · The Surveillance Mindmap

How market behavior connects to indicators to candidate detection rules —
the map from question 03 (*was something unusual?*) to question 04
(*does this deserve investigation?*). Question 04 is the project's
direction, not its current state: what exists today is the verified
indicator layer and the beginnings of cross-day context; what is
sketched here is the shape of the detection layer it feeds.

## The causal chain every alert follows

```
strategy (hidden)          observable conduct             indicators
────────────────           ───────────────────            ──────────
spoofing            →      large adds, fast cancels  →    large_order_* ,
(no intent to              on one side, no execution      within-60s rate,
 trade)                                                    standalone_cancels,
                                                           order lifetimes

layering            →      stacked depth on one side  →   book_imbalance extremes,
(manufactured              persisting without          →  depth_total one-sided,
 depth)                     trading, then cascading       burst_ratio spikes,
                                                          cancel_to_trade

marking the close   →      one-sided aggressive        →   last-30m OFI,
(reference price            flow into the close,           volume share late,
 capture)                   premium at the print           vwap_premium
```

No single indicator is an alert. Each strategy's signature is a
*conjunction*: the conduct, its one-sidedness, and its persistence —
checked against the symbol's own norms.

## The three lenses as implemented (dashboard)

**1 · Spoofing** — the flicker screen
- *Definition inputs:* genuine adds > day p95 (`large_order_threshold`),
  fully removed by standalone cancels within 60s (`spoof_minute`).
- *Supporting:* lifetime percentiles, cancel pressure vs trades.
- *Read:* a red fraction riding the blue bars, repeating through the
  day; sub-minute lifetimes on one side.
- *Honest twin:* market making — same signature, but two-sided and
  permanent. One-sidedness over time is the discriminator.

**2 · Layering** — the depth screen
- *Definition inputs:* `book_imbalance` (top of book), `depth_total` per
  side, cancel cascade timing.
- *Read:* imbalance pinned near ±1 while price refuses to move, then
  depth collapse (the cascade) — real one-sided demand trades.
- *Honest twin:* genuine large interest — which either executes or
  moves price; standing untouched at an extreme is the anomaly.

**3 · Marking the close** — the reference-price screen
- *Definition inputs:* last-30-minute OFI, late volume share,
  `vwap_premium`.
- *Read:* strong one-sided late flow *that also* leaves a large
  premium, especially on thin days (see volume profile's pockets).
- *Honest twin:* index rebalancing / MOC imbalances — same-day
  one-sided flow, but expected, and recurring on known dates. This is
  why the earnings-day chip exists on the dashboard.

## Candidate rule sketches (deliberately not yet thresholds)

The detection layer's unit is the **explainable candidate alert**: a
row per (symbol, day, lens) with the evidence attached, not a boolean.
Sketches, pending the baseline layer:

- **Spoofing candidate**: `within_60s_share` z-score > k vs symbol's
  distribution *and* cancelled size concentrated on one side *and*
  cancel_to_trade above the symbol's band → alert with the minute
  series, the threshold, and the day's context attached.
- **Layering candidate**: minutes-with-|imbalance|>0.8 sustained > m
  with no price progress, followed by a depth-collapse burst above the
  symbol's burst band → alert with the depth cascade attached.
- **Close candidate**: last-30m OFI z-score > k *and* premium z-score
  > k on below-median volume day *and* not a known event date →
  alert with the late-flow panel attached.

Every z-score is **per symbol, per time-of-day** — never a global
constant (MSFT's normal cancel_to_trade of ~14 would be a permanent
alarm on AAPL's ~7). This is why the 2-month window matters: baselines
*are* the detection system's missing organ.

## Why wash trading is absent

Identity-blind data cannot distinguish self-trading from genuine
two-sided flow; any "detector" would be theater. Documented exclusion
(doc 05) — a bound, not a gap.

## The honest-limits checklist (applies to every future alert)

1. Single venue (XNAS) — cross-venue strategies invisible.
2. Displayed size only — hidden/iceberg liquidity unmeasured.
3. Anonymous participants — no collusion graphs.
4. Conduct ≠ intent — alerts route humans to look, never conclude.
5. Baselines before thresholds — an alert without a distribution is a
   guess with formatting.

## Open threads (see knowledge-base/06-surveillance-mindmap.md)

- Order-lifecycle metrics (time-to-cancel distributions per order) —
  built at snapshot level; promote to gold when scale lands.
- Hourly/daily spread rollups — trivial aggregation, build when a
  consumer needs them.
- Session splits (pre-market vs RTH behavior) — open question #2.
- The baseline/z-score layer — open question #9-adjacent; the day
  panel's "vs median" column is its embryo.
