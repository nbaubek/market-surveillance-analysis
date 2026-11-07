# 01 · Market Fundamentals

The market mechanics everything else in this project assumes. Read until
"bid, ask, spread, depth" need no conscious thought; everything downstream
(compute metrics, detect manipulation, read a dashboard) is built on this
page.

## The limit order book

A stock exchange runs a continuous auction. Participants submit **orders**;
the exchange keeps the outstanding (unexecuted) ones in the **order book** —
the live list of who is willing to buy and sell, at what price, for how
many shares.

- A **buy order (bid)** states: "I will buy up to N shares at price P or
  lower."
- A **sell order (ask / offer)** states: "I will sell up to N shares at
  price P or higher."

The book is two sorted stacks:

- **Bids**, sorted best-first: highest price on top. The **best bid** is the
  highest price anyone is currently willing to pay.
- **Asks**, sorted best-first: lowest price on top. The **best ask** is the
  lowest price anyone is currently willing to accept.

Orders sit in the book ("rest") until one of three things happens: they
trade, they are cancelled, or they are modified.

**Spread** = best ask − best bid. It is the market's instant transaction
cost: a buyer who must trade immediately pays the ask; a seller receives
the bid; the spread is the gap the market maker keeps. For a liquid name
like MSFT or AAPL the spread is usually the minimum tick — 1 cent
("penny-tight").

**Depth** = the quantity available at a given price (or summed across
prices). Top-of-book depth is the size at the best bid/ask; total depth is
the whole visible side. Depth is *displayed liquidity* — shares the market
promises to anyone hitting that price.

## How trades happen: the aggressor

Prices don't move by themselves. A trade occurs when someone crosses the
spread:

- A buyer sends an order priced **at or above the best ask** → it executes
  immediately against the resting ask. The buyer is the **aggressor**
  (they initiated; they paid the spread).
- A seller hits the bid symmetrically.

The resting order is passive; the incoming order is aggressive. This
distinction powers one of our most important metrics (**order-flow
imbalance**): aggressor side tells you *who wanted the trade*.

Executions can consume multiple resting orders at multiple prices ("walking
the book"), which is how a large aggressive order moves the price.

## Order lifecycle

An order's life: **add → (partial fills) → (modify/replace) → terminal
state** (fully filled, or cancelled).

- **Modify**: change price or size. On Nasdaq a re-price effectively
  becomes a *replace*: the old order is cancelled and a new one (new ID)
  is added. Size reductions can be partial cancels.
- **Cancel**: remove some (partial) or all (delete) of a resting order's
  quantity. Crucially, **cancelling is free and instant** — displayed
  liquidity is a promise the maker can withdraw at any moment. This fact
  is the foundation of order-book manipulation: you can *display* intent
  you never have to honor.

## Displayed vs hidden liquidity

Not all liquidity is visible. **Iceberg/reserve orders** display only part
of their size; **hidden orders** display nothing. Trades can print at
prices that never appeared in the displayed book (midpoint executions,
price improvement, hidden size) — we measured ~7% of prints at sub-penny
prices, which displayed (penny-grid) quotes cannot produce.

Consequence: everything this project computes about the book concerns the
*displayed* book. That is the right target — manipulation of *displayed*
liquidity is precisely the crime — but it bounds what book metrics can
claim (see each metric's Limitations).

## Sessions and the closing price

Nasdaq's day: pre-market from 4:00am ET, the continuous regular session
9:30am–4:00pm ET, after-hours to 8:00pm ET. Activity is thinnest at the
edges.

The **closing price** is not simply "the last trade": the final minutes
feed the **closing cross auction**, whose print sets the official close.
The close matters far beyond one trade: it feeds benchmark indices, ETF
NAVs, option strikes, and fund accounting. That importance is what makes
**marking the close** — pushing the closing print away from fair value —
a manipulative strategy worth a dedicated lens.

## What "manipulation" means here

Three strategies this project can meaningfully address (see
06-surveillance-mindmap.md):

- **Spoofing** — placing orders with intent to cancel, to create a false
  impression of supply/demand. The book is the instrument; the cancel is
  the tell.
- **Layering** — spoofing at multiple price levels simultaneously,
  manufacturing depth rather than a single quote.
- **Marking the close** — trading into the close to drag the reference
  price.

What manipulation is *not*, for us: **wash trading** (trading with
yourself to fake volume) requires participant identity — anonymous
exchange data cannot support it, and we say so rather than pretend
(Honest limits, doc 06).

And the standing rule for every metric in doc 03: these behaviors are
**indicators, not evidence**. Legitimate market making produces fast
cancels and heavy quoting by design. Detection is a human decision; our
job is to make the signal explainable.

## Vocabulary quick-reference

| Term | Meaning |
|---|---|
| bid / ask | resting buy / sell order (or side of the book) |
| best bid / best ask | highest bid, lowest ask — "the touch" |
| spread | best ask − best bid |
| tick | minimum price increment ($0.01 here) |
| depth | quantity displayed at a price level (or side) |
| liquidity | the availability of tradable quantity near the current price |
| aggressor | the order that crossed the spread and caused a trade |
| resting / making | the passive side that was already in the book |
| quote | a displayed bid or ask |
| notional | dollar value (shares × price) |
| bps | basis points, 1/100 of a percent |
| GTC | good-til-cancelled order (persists overnight) |
| cross auction | batch auction at open/close; prints at a single clearing price |
