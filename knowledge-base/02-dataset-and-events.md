# 02 · The Dataset and Its Events

What Databento's XNAS.ITCH market-by-order data actually is, what each
event means, and — most importantly — the semantics we **verified
empirically** rather than took from documentation. Two documented behaviors
turned out wrong or incomplete; both are flagged in §Traps.

## What the data is

- **XNAS.ITCH**: Nasdaq TotalView-ITCH, the full depth-of-book feed for
  Nasdaq-listed securities, as normalized by Databento.
- **MBO (market-by-order)**, sometimes called L3: one record per *order
  book event* — every add, cancel, execution — with the order's price,
  size, and side. Contrast with trade data (only prints) or market-by-
  price (aggregated levels). MBO is the only grain that supports
  order-lifetime and displayed-liquidity analysis.
- One row per **event record**. Schema (16 columns) in `CLAUDE.md`;
  the analytically decisive fields: `action`, `side`, `price`, `size`,
  `order_id`, `channel_id`, `sequence`, `ts_event`, `ts_recv`, `symbol`.

## The actions — and what they really do

| Action | Naive meaning | **Verified meaning** |
|---|---|---|
| `A` | order added | ✓ genuine new order — *unless* it's the new leg of a replace (see C) |
| `C` | order cancelled | C.size is **always the quantity to remove** at C.(side, price) — standalone (partial or full), execution leg, or replace leg. One uniform rule |
| `T` | trade | the tape print; carries the **aggressor's side** (verified at the event instant: 95.7% of side=B prints land exactly at the best ask); `order_id = 0` — Nasdaq never exposes the aggressor's ID |
| `F` | fill | the resting order's execution; carries the resting order's real `order_id`; **does NOT itself change book state** |
| `R` | "instrument definition" | actually the **book-clear of Databento's synthetic start-of-day snapshot**: exactly one per day (~07:07–07:09 UTC, sequence 0, no price). Excluded from silver — synthetic bookkeeping, not market activity |
| `M` | modify | **zero occurrences** across all inspected days — Nasdaq modifies manifest as C+A replaces |
| `N` | "none" | zero occurrences as an action; side='N' appears only as the *side* of cross prints (auctions) |

## Two entity systems (the key mental model)

Every metric must know which entity it addresses:

**1. The message group** — rows produced by one exchange message.
Identity: `(ts_event_day, channel_id, sequence)`. All normalized records
of one message share a sequence.

**2. The order lifecycle** — one resting order's life, keyed by
`order_id` (real on A/M/C/F; placeholder 0 on all T rows).

Verified group anatomy:

- **Execution** = `T + F + C` in one group (T omitted when the execution
  is non-printable — 11 such F+C groups on MSFT 2019-07-30). Within the
  triple, **C is the only state-mutating record**: the fill is
  accompanied by a cancel that subtracts the filled size. Verified:
  C.size = F.size in 27,350/27,330 groups. T and F are book-state no-ops.
- **Replace** = `C(old order) + A(new order)` in one group — 54,624
  groups on MSFT 2019-07-30 (more numerous than executions).
- **Standalone cancel** = C whose group contains no T/F and no A — the
  only cancel a human or algorithm deliberately chose. This definition
  powers every surveillance ratio in the project.
- **Cross trades** (auctions) = lone `T` with side=N.

Consequences that took real debugging to internalize:

- Counting both T and F double-counts every execution (same size on both
  rows) — volume/trade counts use **T only**.
- The message-group flags (`message_flags` table) classify *rows by their
  group's contents*. Asymmetry trap: `in_replace_group` ("group has an
  A") is trivially TRUE for every A row — its own leg makes it so. To
  classify A rows use `in_cancel_group` ("group has a C").

## Sequences and timestamps

- `sequence` is **channel-wide across all symbols** and resets daily.
  MSFT's first message of a day arrives at sequence ≈ 237k–240k (other
  symbols' messages precede it); AAPL's day spans up to ~282M.
- **Timestamps cannot order events**: a trade and its book update (the
  triple's C) share the *identical* ts_event (verified: 4,186/4,186
  groups). Ordering must use `(channel_id, sequence)`.
- `ts_recv` (capture time) vs `ts_event` (engine time): clock skew
  between them spills ~0.05–0.09% of a day-file's records into the
  adjacent UTC day's partition. Harmless once known; the reason bronze
  row counts differ slightly from ingest logs.

## §Traps — where documentation and data disagreed

**Trap 1 — the "start-of-day snapshot" is just an R.** Documentation
describes a synthetic start-of-day snapshot; we half-expected re-injected
A records that silver would need. Measured: R is a single row, followed
by ~50 minutes of silence, then organic pre-market flow. Each day builds
**from an empty book** — which is exactly why a silver-only replay is
correct and no bronze seeding is needed.

**Trap 2 — the day-boundary cleanup burst.** At 00:00:00.0x UTC Databento
cancels all orders still resting from the previous session (AAPL:
~900–1,300 rows in the first 100ms; MSFT: none). These rows carry
ts_event at day start but **sequence numbers from the prior session's
space**, breaking sequence↔time monotonicity. Replay with sequence
ordering + timestamp-stamped intervals fabricated "live-since-midnight"
phantom levels — 1,425 crossed quotes on AAPL — until we excluded the
burst in silver (alongside R). This is also why the non-negativity test
must recompute the running sum independently: a test on the *filtered*
output table is structurally blind to negative states.

## What the data cannot show

- **Hidden/reserve liquidity** (displayed size only)
- **Participant identity** (MPID attribution stripped; wash trading
  therefore out of scope by design)
- **Other venues** (Nasdaq only — cross-market layering invisible)
- **Intent** — ever, for anyone

These four bounds are restated wherever they change a metric's meaning
(doc 03, Limitations).
