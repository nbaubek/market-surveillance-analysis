# Phase 3 Prototype & Validation Evidence

Ad-hoc Athena queries that took top-of-book reconstruction from an idea to
a validated design, plus the results they produced. Kept as project
evidence: regression reference for `book_state` / `minute_book_metrics`
(production models reconcile EXACTLY to the prototype — 766/766 rows,
0 mismatches on 2019-07-30) and as the record of engineering decisions.

Reference day: **MSFT 2019-07-30** (quietest of the 4 ingested days).
Tables: silver `market_surveillance_silver.itch_mbo_cleaned`, gold
`market_surveillance_gold.*`. Queries ran via boto3 `start_query_execution`
(workgroup `market-surveillance`, region us-east-1).

## What was established

| Step | Query | Result |
|---|---|---|
| 1. Snapshot anatomy | `02_snapshot_anatomy.sql` | Start-of-day "snapshot" = a single R book-clear (~07:07 UTC, sequence 0, no re-injected adds); each day's book builds organically from empty → silver-only replay is exact, no bronze seeding |
| 2. Replay invariants | `01_replay_invariants.sql` | 0 negative level states across 1,261,123 A/C events; 0 timestamp inversions under sequence ordering; A prices penny-gridded |
| 3. Minute book | `03_minute_book_ctas.sql` | 27s CTAS; 766 minute rows; 0 crossed; min spread $0.01 |
| 4. Spread/depth sanity | `04_minute_stats_and_control.sql` | RTH median spread 1¢; wrong-book control (book shifted 1h) at-touch rate 2.3% |
| 5. Event-instant touch | `05_event_instant_touch.sql` | **95.7% of side='B' prints and 99.0% of side='A' prints EXACTLY at the reconstructed touch** (pre-trade book); re-verifies T.side = aggressor |
| 6. Bug hunt | `06_examples.sql` | The example dump that exposed the "all prints at mid" artifact caused by the off-by-one-group interval end |

## The two traps (both bit; both documented in `book_state`)

1. **Timestamps cannot order events.** A trade and its book update (the C)
   share identical `ts_event` — 4,186/4,186 sampled groups. All
   evaluation must be in sequence space.
2. **The interval end convention decides pre-trade vs post-event.**
   `valid_to_seq >= s` includes the level the trade consumed (pre-trade
   book); `>` excludes it. The wrong choice produces a beautiful fake
   pattern: every print at the exact midpoint of a phantom 2¢ spread.

## Regression use

Rebuild `minute_book_metrics` for 2019-07-30 and diff against the
prototype table (still present until its 30-day expiry — drop the Glue
table `prototype_minute_book_20190730` after that):

```sql
-- expect: 766 / 766 / 0
select
  (select count(*) from market_surveillance_gold.prototype_minute_book_20190730) as proto_rows,
  (select count(*) from market_surveillance_gold.minute_book_metrics
    where ts_event_day = date '2019-07-30') as prod_rows,
  (select count(*) from market_surveillance_gold.prototype_minute_book_20190730 p
   full join market_surveillance_gold.minute_book_metrics m
     on cast(p.minute_ts as timestamp) = at_timezone(
          cast(m.ts_event_day as timestamp) + interval '1' minute * m.event_minute, 'UTC')
   where p.minute_ts is null
      or m.best_bid is null or p.best_bid != m.best_bid
      or p.best_ask != m.best_ask or p.live_levels != m.live_levels) as mismatches;
```

Status 2026-11-04: production models `book_state` + `minute_book_metrics`
built and reconciled (0 mismatches); all 35 dbt tests pass, including the
singular invariants (non-negative quantities, well-formed intervals, not
crossed, penny-grid quotes).
