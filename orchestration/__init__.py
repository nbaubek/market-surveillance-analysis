"""Dagster project: market surveillance pipeline orchestration.

Entry point Dagster discovers (Definitions). Loads .env for local dev
(no-op on Dagster+ where env vars come from the platform), then constructs
resources from the environment — local and Dagster+ both work unchanged.

Local development:
    export AWS_PROFILE=my-dev-profile
    uv run dagster dev          # http://localhost:3000

Dagster+ deployment:
    Push this repo, connect Dagster+ (see orchestration/README.md).
"""

import os

from dotenv import load_dotenv

load_dotenv()  # .env for local dev; on Dagster+ env vars are native

from dagster import Definitions

from orchestration.assets import (
    bronze_ingestion,
    silver_models,
    gold_models,
    soda_scan,
)
from orchestration.resources import AwsConfig, DbtConfig, PipelineConfig
from orchestration.schedules import daily_catch_up, daily_pipeline

defs = Definitions(
    assets=[bronze_ingestion, silver_models, gold_models, soda_scan],
    resources={
        "pipeline": PipelineConfig(
            symbols=os.environ.get("INGEST_SYMBOLS", "MSFT,AAPL"),
            catch_up_days=int(os.environ.get("CATCH_UP_DAYS", "5")),
        ),
        "aws": AwsConfig(
            aws_profile=os.environ.get("AWS_PROFILE", "default"),
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", ""),
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", ""),
            aws_session_token=os.environ.get("AWS_SESSION_TOKEN", ""),
        ),
        "dbt": DbtConfig(),
    },
    jobs=[daily_pipeline],
    schedules=[daily_catch_up],
)
