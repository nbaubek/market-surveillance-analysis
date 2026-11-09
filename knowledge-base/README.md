# Knowledge Base — The Thinking Framework

Everything there is to know about how this project thinks: market concepts,
the data's true semantics, every metric's meaning and limits, where each
number comes from, why the analytical decisions were made, and how market
behavior maps to surveillance.

Written to be read by a person (you, a reviewer, a future you) — not as
reference trivia but as the reasoning chain from "an exchange emitted a
message" to "this behavior deserves a human look."

## The conceptual structure — four questions

The whole project answers an escalating sequence of questions. Every
document, metric, and dashboard panel belongs to exactly one of them.

| # | Question | What lives here | Status |
|---|---|---|---|
| **01 · Market activity** | What happened? | Orders added, replaced, cancelled, executed; trades at prices and quantities | ✅ fully built |
| **02 · Market conditions** | What did the market look like? | Price (OHLC, VWAP), volume, volatility, spread, depth, imbalance | ✅ fully built |
| **03 · Unusual behavior** | Was something unusual? | Cancellation rates, order-flow imbalance, large orders, bursts — measured against the symbol's own norms | ✅ indicators built; baselines need the longer window |
| **04 · Surveillance** | Does this deserve investigation? | Explainable candidate alerts combining indicators + context, for human review | 🚧 direction, not destination — the detection layer is deliberately the *last* thing, built on verified foundations |

The discipline this ordering enforces: **no alert is credible unless the
metrics under it are verified, and no metric is trusted unless the data
semantics under it were proven against the actual feed** — not the
documentation's claims, the actual bytes.

## The documents

| Doc | What you'll learn |
|---|---|
| [01-market-fundamentals.md](01-market-fundamentals.md) | Orders, trades, bid/ask, liquidity, the order book, executions — the market mechanics everything else assumes |
| [02-dataset-and-events.md](02-dataset-and-events.md) | XNAS.ITCH, market-by-order data, the A/C/T/F/R/N actions, order IDs, sequences, message groups — with the semantics we *verified empirically*, including the traps |
| [03-metrics-and-indicators.md](03-metrics-and-indicators.md) | Every metric: concept, formula, worked example, interpretation, surveillance relevance, limitations — grouped by the market question it answers |
| [04-data-lineage.md](04-data-lineage.md) | How each metric originates from raw messages and flows through ingestion → bronze → silver → gold → dashboard |
| [05-analytical-decisions.md](05-analytical-decisions.md) | Why each approach was chosen and what alternatives were rejected (with the failure that motivated the choice, where there was one) |
| [06-surveillance-mindmap.md](06-surveillance-mindmap.md) | How market behavior connects to indicators and candidate detection rules — the map from question 03 to question 04 |
| [07-diagrams.md](07-diagrams.md) | Visual companions: the four questions, order-book mechanics, message-group anatomy, decision trees, replay, strategy→alert maps |
| [prototype-evidence/](prototype-evidence/) | The receipts: the actual validation queries and results that back the book-replay claims (wrong-book control, event-instant touch, the bug hunt) |

## How to read it (the learning path)

Don't learn metrics alphabetically — learn them by the market question they
answer. Suggested order:

1. **Fundamentals first** (doc 01) until "bid/ask/spread/depth" need no thought.
2. **The dataset** (doc 02) — especially the verified rules; they are what
   make this project's numbers mean what they say.
3. **Metrics by group** (doc 03), one group per sitting, in this order:
   Activity → Volume → Price → Order flow → Cancellation → Intensity →
   Displayed liquidity → Price distribution. For each metric follow the
   six-step loop: *concept → plain English → numerical example → dbt source
   → what it can tell us → what it cannot.*
4. **Lineage** (doc 04) to connect each metric back to raw messages.
5. **Decisions** (doc 05) to understand why the pipeline is shaped as it is.
6. **The mindmap** (doc 06) last — it is where the project is going.

## Standing principles (the short version)

- **Indicators, not evidence.** A high cancel ratio or short order lifetime
  is a signal to investigate, never proof — market makers legitimately
  cancel fast for a living.
- **Verify semantics against data, not docs.** Every rule in doc 02 was
  tested with queries against the actual feed; two "documented" behaviors
  turned out to be wrong or incomplete (see 02 §traps).
- **The tape and the book are different instruments.** Trades show what
  happened; displayed orders show what was *offered*. Never let a chart
  imply one is the other.
- **One venue, displayed size, no identities.** Nasdaq only, hidden depth
  invisible, participants anonymous — these bounds define what is
  detectable at all (and why wash trading is out of scope).

## Relationship to the rest of the repo

- `knowledge-base/03-metrics-and-indicators.md` — the compact technical catalog (this KB is the
  explanatory layer above it)
- `knowledge-base/02-dataset-and-events.md` — engineering plan, phase history, open questions
- `dataset-info.md` — Databento's own dataset reference (source material)
- `demo/` — the dashboard; its "How to read this" guides are distilled
  versions of doc 03's entries
- `knowledge-base/prototype-evidence/` — the validation evidence behind the book metrics
