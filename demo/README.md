# Market Surveillance — Demo Dashboard

Zero-AWS demo of the project's gold layer: FastHTML + MonsterUI + ECharts
reading a Parquet snapshot via DuckDB. No credentials, no live AWS — the
snapshot is exported from Athena by `src/export/gold_snapshot.py` and
committed under `data/`.

## Pages

- **Overview** — KPI tiles (close, VWAP/TWAP, volume/notional, order-flow
  imbalance, realized vol, median reconstructed spread), price vs VWAP,
  aggressor flow (buy up / sell down), volume profile, days-side-by-side table.
- **Surveillance** — the three defensible manipulation lenses:
  1. *Spoofing*: large adds (day p95, replace legs excluded) vs those fully
     removed by standalone cancels within 60s; cancel pressure vs trades;
     order-lifetime tiles.
  2. *Layering*: top-of-book imbalance (diverging), displayed depth by side.
  3. *Marking the close*: per-minute order-flow imbalance, last-30-minute
     OFI / volume-share tiles, close-vs-VWAP premium by day.
- **Methodology** — pipeline, verified semantics, and the honest limits
  (single venue, displayed size, conduct ≠ intent).

## Run locally

```
cd demo
uv sync
uv run python app.py       # http://localhost:7860
```

## Refresh the snapshot

From the repo root (needs AWS_PROFILE with Athena access):

```
AWS_PROFILE=my-dev-profile uv run python -m src.export.gold_snapshot
```

## Deploy to Hugging Face Spaces

1. Create a Space (type: Docker, SDK: custom).
2. Push this directory as the Space repo root — `Dockerfile`, `app.py`,
   `data/`, `pyproject.toml`, `uv.lock` (the build pins the uv binary and
   installs from the lockfile: `uv sync --frozen`).
3. Space serves on port 7860 (already configured).

The Dockerfile builds the same environment as local development
(Python 3.13, uv, locked deps), so the Space behaves identically.
