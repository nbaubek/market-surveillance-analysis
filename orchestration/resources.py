"""Dagster resources: external services and environment configuration.

Resources make configuration explicit, visible in the Dagster UI, and
testable (mockable in unit tests). Defaults are sensible; environment
variables override at Definitions construction time (see __init__.py),
so local dev (dagster dev with .env) and Dagster+ Serverless (platform
env vars) both work without code changes.
"""

import os

from dagster import ConfigurableResource


class PipelineConfig(ConfigurableResource):
    """Pipeline-wide settings: which symbols, how far back to catch up."""

    symbols: str = "MSFT,AAPL"
    catch_up_days: int = 5

    @property
    def symbol_list(self) -> list[str]:
        return [s.strip() for s in self.symbols.split(",") if s.strip()]


class AwsConfig(ConfigurableResource):
    """AWS authentication for S3/Glue/Athena.

    Two modes (auto-detected by what's in the environment):
    - Local: AWS_PROFILE=my-dev-profile (default chain via ~/.aws)
    - Dagster+: direct keys injected as environment variables
    """

    aws_profile: str = "default"
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_session_token: str = ""
    region: str = "us-east-1"

    @property
    def subprocess_env(self) -> dict[str, str]:
        """Environment variables for subprocess calls (ingestion, dbt).

        Prefers direct keys (Dagster+ pattern) over profile (local pattern)
        so both work without branching in the assets.
        """
        env = os.environ.copy()
        if self.aws_access_key_id and self.aws_secret_access_key:
            # Dagster+ / CI: direct credentials
            env["AWS_ACCESS_KEY_ID"] = self.aws_access_key_id
            env["AWS_SECRET_ACCESS_KEY"] = self.aws_secret_access_key
            if self.aws_session_token:
                env["AWS_SESSION_TOKEN"] = self.aws_session_token
            env.pop("AWS_PROFILE", None)  # profile would take precedence
        else:
            # Local: named profile via the default chain
            env["AWS_PROFILE"] = self.aws_profile
        env["AWS_DEFAULT_REGION"] = self.region
        return env


class DbtConfig(ConfigurableResource):
    """dbt project location and execution settings."""

    project_dir: str = "dbt"
    target: str = "dev"
    threads: int = 4
