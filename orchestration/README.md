# Dagster Orchestration

The pipeline as Dagster assets: bronze ingestion → silver dbt merge → gold
rebuild → Soda observability scan. Daily partitions map 1:1 to the
pipeline's day-aligned windows.

## Asset graph

```
bronze_ingestion [daily]  →  silver_models [daily]  →  gold_models [daily]
                                                          ↓
                                                    soda_scan
```

Each asset wraps the existing CLI tools via subprocess — the same commands
you'd run manually, with Dagster providing scheduling, retries, logging,
and laptop-free execution on Dagster+ compute.

## Local development

```bash
# from the repo root
export AWS_PROFILE=my-dev-profile
uv run dagster dev          # webserver at http://localhost:3000
```

The `.env` file (Databento API key) is loaded automatically by
`orchestration/__init__.py` via python-dotenv.

In the Dagster UI:
1. Go to **Overview → Jobs → daily_pipeline**
2. Click **Materialize** to run for the latest partition
3. Or go to **Deployment → Schedules** to see the weekday catch-up

## Deploy to Dagster+ (Serverless)

1. **Sign up** at [dagster.io](https://dagster.io) (free tier available)
2. **Create a new Deployment** → choose **Serverless**
3. **Connect your GitHub repo** (`nbaubek/market-surveillance-analysis`)
   - Branch: `main`
   - Dagster project path: `/` (repo root — Dagster finds `orchestration/` package)
   - Code location name: `market_surveillance`
4. **Set environment variables** (Deployment → Settings → Environment Variables):

   | Variable | Value | Notes |
   |---|---|---|
   | `DATABENTO_API_KEY` | your Databento key | from your .env |
   | `AWS_ACCESS_KEY_ID` | your AWS access key | from `aws configure get aws_access_key_id --profile my-dev-profile` |
   | `AWS_SECRET_ACCESS_KEY` | your AWS secret key | from `aws configure get aws_secret_access_key --profile my-dev-profile` |
   | `AWS_SESSION_TOKEN` | your session token | if using temporary creds; omit for permanent keys |
   | `AWS_DEFAULT_REGION` | `us-east-1` | |
   | `INGEST_SYMBOLS` | `MSFT,AAPL` | or the full slate: `MSFT,AAPL,TSLA,MU,ROKU,TTD` |
   | `CATCH_UP_DAYS` | `5` | lookback window for the schedule |

5. **Deploy** — Dagster+ builds the code location from the repo's
   `pyproject.toml` dependencies and starts the schedule.

## How the catch-up works

The `daily_catch_up` schedule runs at 06:00 UTC on weekdays and creates a
`RunRequest` for each of the last `CATCH_UP_DAYS` trading days. Each
request materializes the `daily_pipeline` job for that partition:

- **bronze_ingestion**: the ingestion CLI checks the catalog (has_day);
  already-ingested days are skipped without a Databento job
- **silver_models**: dbt re-merges the day's window (idempotent — matched
  rows update in place with identical values)
- **gold_models**: full rebuild (all gold tables; idempotent)
- **soda_scan**: post-build quality verification

Repeated runs are safe: every step is idempotent.

## Backfilling a date range

1. In the Dagster UI: **Overview → Assets → all assets → Materialize**
2. Select a partition range (e.g., `2019-08-12` to `2019-08-30`)
3. **Deselect `gold_models`** for large backfills (it rebuilds everything
   on each partition run — wasteful for 20+ days)
4. After the backfill completes, materialize `gold_models` once

Or via CLI:
```bash
# backfill silver only for Aug 12-30
dagster job backfill daily_pipeline \
  --partitions-start 2019-08-12 --partitions-end 2019-08-30 \
  --selection bronze_ingestion silver_models
```

## The laptop-free pattern

This is the reason Dagster+ exists here:

1. Push code, close laptop
2. Dagster+ schedule fires at 06:00 UTC on its own compute
3. Jobs poll Databento, download, convert, append to S3/Glue — all on
   Dagster's servers
4. Open the Dagster UI from any browser to see results
