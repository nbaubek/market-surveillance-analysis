# 07 · Diagrams

Visual companions to docs 01–06. Each diagram says which doc it supports,
so you can either read this page on its own or copy a block into the
matching doc (Mermaid renders natively on GitHub, GitLab and most
Markdown viewers; the order book is a plain SVG).

| # | Diagram | Supports |
|---|---|---|
| 1 | The four questions | README |
| 2 | Order book, spread, aggressor, imbalance | 01, 03 |
| 3 | Order lifecycle | 01 |
| 4 | Message-group anatomy | 02 |
| 5 | "What kind of C is this?" decision tree | 02, 03 |
| 6 | Metric map by market question | 03 |
| 7 | Data lineage | 04 |
| 8 | Replay: how a level's depth is computed | 04 |
| 9 | Strategy → conduct → indicator → alert | 06 |
| 10 | Spoofing as a timeline | 06 |
| 11 | Real interest vs flickering | 06 |

---

## 1 · The four questions (README)

Each question is only credible if the one below it is verified.

```mermaid
flowchart TB
    Q4["04 · SURVEILLANCE<br/>Does this deserve investigation?<br/>explainable candidate alerts 🚧"]
    Q3["03 · UNUSUAL BEHAVIOR<br/>Was something unusual?<br/>cancel rates, OFI, large orders, bursts"]
    Q2["02 · MARKET CONDITIONS<br/>What did the market look like?<br/>OHLC, VWAP, volatility, spread, depth"]
    Q1["01 · MARKET ACTIVITY<br/>What happened?<br/>adds, replaces, cancels, executions, trades"]
    Q1 --> Q2 --> Q3 --> Q4
    classDef built fill:#e3f1e7,stroke:#3f8f55,color:#123;
    classDef direction fill:#fff4d6,stroke:#d4a017,color:#123;
    class Q1,Q2,Q3 built;
    class Q4 direction;
```

---

## 2 · Order book, spread, aggressor, imbalance (01, 03)

![Order book and book_imbalance](diagrams/order-book-and-imbalance.svg)

---

## 3 · Order lifecycle (01)

```mermaid
stateDiagram-v2
    [*] --> Resting: A (add)
    Resting --> Resting: partial fill (F + C reduce size)
    Resting --> Resting: partial standalone cancel
    Resting --> Filled: fully executed
    Resting --> Cancelled: standalone cancel (deliberate)
    Resting --> Replaced: C old order + A new order
    Replaced --> Resting: new order, new ID
    Filled --> [*]
    Cancelled --> [*]
```

Cancelling is free and instant; the standalone cancel is the "tell" that
surveillance cares about.

---

## 4 · Message-group anatomy (02)

One exchange message produces one **group**, identified by
`(ts_event_day, channel_id, sequence)`. Only `C` and `A` change book
state; `T` and `F` are no-ops.

```mermaid
flowchart LR
    subgraph EX["Execution (T optional if non-printable)"]
        direction TB
        T1["T · tape print<br/>aggressor side, order_id = 0"]
        F1["F · resting order fill<br/>real order_id"]
        C1["C · removes filled size<br/>⚙ state-mutating"]
    end
    subgraph RP["Replace (re-price / re-size)"]
        direction TB
        C2["C · old order<br/>⚙ removes"]
        A2["A · new order, new ID<br/>⚙ adds"]
    end
    subgraph SC["Standalone cancel ★"]
        direction TB
        C3["C · alone<br/>⚙ removes size<br/>the only deliberate cancel"]
    end
    subgraph AD["Genuine add"]
        direction TB
        A4["A · alone<br/>⚙ adds"]
    end
    subgraph CR["Cross (auction)"]
        direction TB
        T5["T · side = N<br/>lone print"]
    end
```

Counting both `T` and `F` double-counts each execution, so volume and trade
counts use **T only**.

---

## 5 · "What kind of C is this?" (02, 03)

This is the logic behind `is_standalone_cancel`, the numerator of every
surveillance ratio.

```mermaid
flowchart TD
    Start(["C row arrives"]) --> Q1{"Does its message group<br/>contain T or F?"}
    Q1 -- yes --> EX["Execution leg<br/>mechanical bookkeeping"]
    Q1 -- no --> Q2{"Does its group<br/>contain an A?"}
    Q2 -- yes --> RP["Replace leg<br/>mechanical bookkeeping"]
    Q2 -- no --> SC["★ Standalone cancel<br/>a deliberate decision"]
    EX --> RAW["counted in raw cancels only<br/>(~15% of raw C)"]
    RP --> RAW
    SC --> BOTH["counted in raw cancels<br/>AND standalone_cancels"]
    BOTH --> USE["used in cancel_to_trade,<br/>lifetimes, spoof_minute"]
    classDef good fill:#e3f1e7,stroke:#3f8f55;
    classDef mech fill:#eee,stroke:#999;
    class SC,BOTH,USE good;
    class EX,RP,RAW mech;
```

Mirror trap for **A** rows: `in_replace_group` is always true for an A
(its own leg). Use `in_cancel_group` to tell replace-adds from genuine adds.

---

## 6 · Metric map by market question (03)

```mermaid
mindmap
  root((Metrics))
    1 Activity
      messages
      adds
      raw cancels
      standalone_cancels ★
      trades and fills
    2 Volume
      trade_volume
      notional_volume ★
      cross_volume
    3 Price
      OHLC
      vwap ★
      twap
      range_bps and realized_vol_bps ★
      vwap_premium
      avg_trade_size
    4 Order flow
      taker buy and sell volume
      order_flow_imbalance ★
    5 Cancellation
      cancel_to_add_ratio
      cancel_to_trade_ratio ★
      large_order threshold count share ★
      order lifetimes ★
    6 Intensity
      messages_per_minute
      burst_ratio ★
      live_levels
    7 Displayed liquidity
      best bid ask spread
      depth top and total
      book_imbalance ★
    8 Price distribution
      volume profile
```

★ = headline metric. Sources: tape metrics come from `T` rows; groups 5, 7
need `message_flags` or `book_state`.

---

## 7 · Data lineage (04)

```mermaid
flowchart TD
    API["Databento API<br/>XNAS.ITCH batch files"]
    ING["src/ingestion/<br/>streamed, contract-validated,<br/>idempotent per symbol-day"]
    BR[("BRONZE · itch_mbo<br/>append, raw 1:1")]
    SI[("SILVER · itch_mbo_cleaned<br/>dedup, drops R and<br/>day-boundary burst")]
    FL[("SILVER · message_flags<br/>group classification")]
    G1["GOLD · hourly / minute / daily<br/>volume_profile<br/>tape aggregates, full rebuild"]
    BS[("GOLD · book_state<br/>price-level intervals<br/>incremental MERGE")]
    MB["GOLD · minute_book_metrics<br/>spread, depth, imbalance"]
    EXP["EXPORT · gold_snapshot.py<br/>parquet, about 715 KB"]
    DEMO["DEMO · FastHTML + DuckDB + ECharts<br/>zero-AWS"]

    API --> ING --> BR --> SI --> FL
    SI --> G1
    FL --> G1
    SI --> BS
    BS --> MB
    G1 --> EXP
    MB --> EXP
    EXP --> DEMO

    classDef bronze fill:#f4e3d3,stroke:#a0693a;
    classDef silver fill:#e6e9ef,stroke:#7a8599;
    classDef gold fill:#fff4d6,stroke:#d4a017;
    class BR bronze;
    class SI,FL silver;
    class G1,BS,MB gold;
```

Dashboards read gold only, which is the medallion contract that made the
zero-AWS demo a simple export.

---

## 8 · Replay: from events to depth at a price (04, 05)

Replay works per `(side, price)` level: depth is a running sum of adds
minus cancels, ordered by `sequence` (never timestamp).

```mermaid
sequenceDiagram
    participant Feed as Events (by sequence)
    participant Lvl as Level: BID 140.25
    participant Int as book_state intervals
    Feed->>Lvl: seq 101 · A +500
    Note over Lvl: net 500
    Lvl->>Int: interval from seq 101, qty 500
    Feed->>Lvl: seq 140 · A +300
    Note over Lvl: net 800
    Lvl->>Int: close previous, open interval qty 800
    Feed->>Lvl: seq 177 · C -800 (standalone cancel)
    Note over Lvl: net 0
    Lvl->>Int: close interval, level no longer live
```

Querying "what was the book at minute M?" means picking the interval that
covers M (`[ts_from, ts_to)`). Pre-trade state at an event uses
`valid_to_seq >= s`. The invariant test recomputes these sums from silver
and asserts they are never negative.

---

## 9 · Strategy → conduct → indicator → alert (06)

```mermaid
flowchart LR
    subgraph HIDDEN["Hidden (intent)"]
        SP["Spoofing"]
        LY["Layering"]
        MC["Marking the close"]
    end
    subgraph CONDUCT["Observable conduct"]
        C1["Large adds, fast cancels,<br/>one side, no execution"]
        C2["Stacked one-sided depth,<br/>no trading, then cascade"]
        C3["One-sided aggressive flow<br/>into the close"]
    end
    subgraph IND["Indicators"]
        I1["large_order_*<br/>within-60s share<br/>standalone_cancels<br/>lifetimes"]
        I2["book_imbalance extremes<br/>depth_total one-sided<br/>burst_ratio<br/>cancel_to_trade"]
        I3["last-30m OFI<br/>late volume share<br/>vwap_premium"]
    end
    BASE{{"Per-symbol, per-time-of-day<br/>baseline (z-score)"}}
    AL["Explainable candidate alert<br/>symbol · day · lens<br/>+ evidence attached"]
    HUM(["Human review"])

    SP --> C1 --> I1
    LY --> C2 --> I2
    MC --> C3 --> I3
    I1 --> BASE
    I2 --> BASE
    I3 --> BASE
    BASE --> AL --> HUM
    classDef next fill:#fff4d6,stroke:#d4a017;
    class BASE,AL next;
```

No single indicator is an alert. An alert needs the conjunction of conduct,
one-sidedness and persistence, judged against the symbol's own norms. The
baseline layer (yellow) is the part still to be built.

---

## 10 · Spoofing as a timeline (06)

```mermaid
sequenceDiagram
    autonumber
    participant S as Spoofer
    participant B as Displayed book
    participant M as Other participants
    participant T as Tape
    S->>B: Real order: SELL 200 (small, wants to execute)
    S->>B: Large BID adds, above p95 size (no intent to trade)
    B-->>M: Book looks bid-heavy, imbalance up
    M->>B: Buyers join, price edges up
    M->>T: Buy hits the real sell at a better price
    S->>B: Standalone cancels of the large bids within 60s
    B-->>M: Imbalance collapses
    Note over S,T: Signature: large adds → fast cancels,<br/>one side, repeated through the day,<br/>with little execution on the large orders
```

---

## 11 · Real interest vs flickering (06)

How the "honest twin" is told apart from the suspicious pattern.

```mermaid
flowchart TD
    OBS["Large resting orders observed<br/>(above symbol-day p95)"] --> Q1{"What happens to them?"}
    Q1 -- "they trade, or price moves<br/>to meet them" --> REAL["Genuine interest"]
    Q1 -- "withdrawn quickly<br/>(standalone cancels)" --> Q2{"Is flow two-sided<br/>and permanent?"}
    Q2 -- "yes, both sides,<br/>all day, every day" --> MM["Likely market making<br/>(honest twin)"]
    Q2 -- "no, one side,<br/>episodic, repeated" --> Q3{"Beyond the symbol's<br/>own baseline?"}
    Q3 -- no --> NORM["Within normal range"]
    Q3 -- yes --> CAND["⚠ Candidate alert<br/>route to a human"]
    classDef ok fill:#e3f1e7,stroke:#3f8f55;
    classDef warn fill:#fde8e8,stroke:#c94a4a;
    class REAL,MM,NORM ok;
    class CAND warn;
```

Same shape applies to the other two lenses: layering's honest twin is
genuine large interest that trades, and the close-marking twin is index
rebalancing or MOC imbalance on known dates.
