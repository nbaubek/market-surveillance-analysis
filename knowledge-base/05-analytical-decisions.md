# 05 · Analytical Decisions

Every consequential choice, why it was made, and — where one existed —
the alternative that was rejected. This is the project's decision log:
the fastest way to understand why the system looks the way it does.

## Data & semantics

**Verify semantics against the data, not the documentation.** The
Databento reference describes normalization; our queries found two
discrepancies (the R "snapshot" is a single row; the day-boundary
cleanup burst exists nowhere in the docs). Decision: every rule used by
a metric must be empirically verified on the actual feed. This habit
also caught a wrong early belief ("F reduces the resting order" —
false; C does) that would have corrupted the book replay.

**Exclude synthetic bookkeeping in silver (R + day-boundary burst).**
Rejected alternative: keep everything raw and filter in every consumer —
rejected because consumers would each re-implement the exclusion, drift
inevitably. One exclusion, one place, tested.

**Standalone cancels as the churn definition.** Raw cancel counts are
~15% mechanical bookkeeping (execution legs, replace legs). Rejected:
filtering "fast cancels" heuristically — the message-group structure
gives the exact answer, so use it.

**T-only tape metrics.** T and F carry identical size per execution;
counting both double-counts. F survives only as its own metric (catches
non-printable executions).

**Sequence-space ordering, timestamp-space intervals.** Timestamps tie
within message groups (4,186/4,186); only `(channel_id, sequence)`
orders events. Intervals keep both coordinate systems because consumers
need each (minutes vs event instants).

## Replay architecture

**Price-level replay, not per-order.** ΣA−ΣC per (side, price) needs no
cross-order ranking — expressible in one window pass, incremental,
cheap. Per-order replay is deferred until an order-level metric
justifies its cost. Validated: 0 negative states over all events;
95.7/99.0% exact-touch prints (control 2.3%).

**Silver-only replay (no bronze seeding).** The snapshot-anatomy
investigation proved each day starts empty and builds organically — the
"seed from the snapshot" complexity dissolved. Cheap question, big
architectural payoff: ask it before building the hard thing.

**Order-aware classification, price-keyed attribution.** The flags
classify *groups*; the asymmetry (in_replace_group is trivially true
for A rows) once produced a silent all-adds-filtered bug — the fix was
a new flag (in_cancel_group), not a cleverer filter, plus a test that
would catch the class.

**Book metrics displayed with scope tags.** Top-of-book vs all-levels
confusion is a real interpretive risk; the dashboard tags every card
TAPE/BOOK/DERIVED and the imbalance subtitle states its scope.

## Pipeline

**Merge strategy (after two failures).** Bronze: append (immutable log).
Silver/flags/book_state: incremental MERGE on a null-safe surrogate key,
day-aligned dual-mode windows. Rejected first: microbatch (2,640 empty
partitions on a window with no trading days); rejected instinct:
high-water marks (break on backfills).

**Gold = full rebuild.** Outputs are tiny; recomputation is trivially
correct — no merge keys, no window alignment, no double-count class.
The flip condition (scan cost) is documented, and the migration path is
prescribed (window pattern, not high-water).

**message_flags as a model.** Window functions run once per window
instead of once per consumer per rebuild; single source of truth for the
classification. Built when the second consumer arrived (extract-on-
second-use).

**Independent invariant tests.** A test that reads filtered output
cannot see what the filter removed. The non-negativity test recomputes
the running sum from silver; a ts-inversion test guards ordering.

## Detection & scope

**Three lenses, not four.** Spoofing, layering, marking the close —
supported by anonymous single-venue displayed-order data. Wash trading
rejected: needs participant identity; a weak proxy dressed as a
detector would be the least defensible part of the project.

**Indicators, not evidence — everywhere.** Caveats, guides, and this KB
repeat it: market makers legitimately cancel fast. Thresholds become
alerts only as per-symbol, per-time-of-day baselines (planned at
2-month scale) — never global constants.

**Roll/high-low spread approximations: dropped.** Exact reconstruction
proved cheap enough; approximations became strictly worse than the real
thing.

## Infrastructure

**Dagster+ over Lambda (and no EventBridge glue).** Lambda: 15-minute
cap vs multi-minute ingestion and dbt backfills; container packaging;
IAM against the project's no-IAM constraint. Dagster+ provides managed
compute, schedules/sensors (native triggers), and logging; daily
partitions map 1:1 onto the pipeline's day-aligned windows.

**Zero-AWS demo.** The dashboard reads a committed Parquet snapshot via
DuckDB — no credentials, no trial-clock dependency, deployable to HF
Spaces free tier. The medallion contract (dashboards read gold only)
made this a 715 KB export instead of a rewrite.

**FastHTML + ECharts (after evaluating Streamlit/Reflex).** Streamlit
ships fastest but everything defaults to looking like Streamlit;
Reflex's strength (app-grade interactivity) is exactly what the
Power-BI-twin constraint forbids. FastHTML + MonsterUI gives full
design control at ~1.5× Streamlit effort.
