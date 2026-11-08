"""CLI runner for Athena-plane Soda scans (silver / gold).

Credentials are resolved from the default boto3 chain (AWS_PROFILE etc.)
and injected into the Soda configuration programmatically — nothing
secret is ever written to disk. Exits 1 on check failures so CI or a
Dagster asset check can gate on it.
"""

import sys

import click
from soda.scan import Scan

STAGING = "s3://trading-surveillance-data/athena-results/"
REGION = "us-east-1"
TARGETS = {
    "silver": ("market_surveillance_silver", "silver.yml"),
    "gold": ("market_surveillance_gold", "gold.yml"),
}


def build_configuration(database: str) -> str:
    """Athena data-source config via the named AWS profile (no keys on disk).

    Property names are the plugin's own (soda/execution/data_sources/
    athena_data_source.py): staging_dir, session_token, profile_name.
    """
    import os

    profile = os.environ.get("AWS_PROFILE", "default")
    return "\n".join([
        "data_source athena:",
        "  type: athena",
        f"  profile_name: {profile}",
        f"  region_name: {REGION}",
        f"  staging_dir: {STAGING}",
        f"  database: {database}",
        f"  schema: {database}",
    ])



def _check_entry(check: dict) -> dict:
    return {
        "name": check.get("name") or check.get("identity") or "check",
        "status": str(check.get("outcome", "unknown")),
    }


def persist_results(target: str, scan: Scan) -> None:
    """Append this run to the demo monitor's results file (JSON lines)."""
    import json
    from datetime import datetime, timezone
    from pathlib import Path

    out = Path(__file__).resolve().parents[2] / "demo" / "data" / "soda_results.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    run = {
        "target": target,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "checks": [_check_entry(c) for c in scan.get_scan_results().get("checks", [])],
    }
    with out.open("a") as fh:
        fh.write(json.dumps(run) + "\n")


def run(target: str) -> int:
    from pathlib import Path

    database, checks_file = TARGETS[target]
    checks_path = Path(__file__).parent / "checks" / checks_file

    scan = Scan()
    scan.set_scan_definition_name(f"market-surveillance-{target}")
    scan.set_data_source_name("athena")
    scan.add_configuration_yaml_str(build_configuration(database))
    scan.add_sodacl_yaml_file(str(checks_path))
    scan.execute()

    print(scan.get_logs_text())
    persist_results(target, scan)
    if scan.has_check_fails() or scan.has_error_logs():
        print(f"RESULT: FAIL ({target})")
        return 1
    print(f"RESULT: PASS ({target})")
    return 0


@click.command()
@click.argument("target", type=click.Choice(list(TARGETS)))
def main(target: str) -> None:
    """Run Soda observability scans: TARGET is silver or gold."""
    sys.exit(run(target))


if __name__ == "__main__":
    main()
