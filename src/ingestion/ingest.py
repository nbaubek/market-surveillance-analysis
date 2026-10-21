"""Thin CLI for bronze ingestion: Databento -> contract chunks -> Iceberg.

No persistent local staging: DBN files land in a scratch temp directory,
stream through conversion/validation, are appended to the bronze Iceberg
table, and the scratch file is deleted. Idempotent per (symbol, day) via
catalog checks.

Requires infra/ to be applied (S3 bucket, Glue database, Athena workgroup)
and AWS credentials on the default chain.

Run from the repo root:
    uv run --env-file .env python -m src.ingestion.ingest
"""

import tempfile
from pathlib import Path

import click
from pyiceberg.catalog import load_catalog

from src.ingestion.client import DatabentoClient
from src.ingestion.converter import CHUNK_ROWS, DbnChunkConverter
from src.ingestion.extractor import DatabentoExtractor
from src.ingestion.iceberg_sink import IcebergTableSink
from src.ingestion.schema import SchemaContract, build_partition_spec
from src.ingestion.spec import ExtractSpec

DEFAULT_SYMBOLS = ("MSFT",)
DEFAULT_START = "2019-07-30"
DEFAULT_END = "2019-07-31"  # exclusive
DEFAULT_BUCKET = "trading-surveillance-data"
DEFAULT_DATABASE = "market_surveillance_bronze"
DEFAULT_TABLE = "itch_mbo"
DEFAULT_REGION = "us-east-1"


@click.command()
@click.option("--symbols", multiple=True, default=DEFAULT_SYMBOLS, show_default=True)
@click.option("--start", default=DEFAULT_START, show_default=True)
@click.option("--end", default=DEFAULT_END, show_default=True, help="Exclusive bound.")
@click.option("--bucket", default=DEFAULT_BUCKET, show_default=True)
@click.option("--database", default=DEFAULT_DATABASE, show_default=True)
@click.option("--table", default=DEFAULT_TABLE, show_default=True)
@click.option("--region", default=DEFAULT_REGION, show_default=True)
@click.option(
    "--chunk-rows",
    type=int,
    default=CHUNK_ROWS,
    show_default=True,
    help="Rows per Iceberg snapshot; set high (e.g. 10000000) for one snapshot per day.",
)
def ingest(
    symbols: tuple[str, ...],
    start: str,
    end: str,
    bucket: str,
    database: str,
    table: str,
    region: str,
    chunk_rows: int,
) -> None:
    """Stream Databento MBO data into the bronze Iceberg table."""
    spec = ExtractSpec(symbols=list(symbols), start=start, end=end)
    try:
        client = DatabentoClient()
    except RuntimeError as e:
        click.echo(str(e), err=True)
        raise SystemExit(1) from e

    contract = SchemaContract()
    catalog = load_catalog(
        "glue",
        **{
            "type": "glue",
            "warehouse": f"s3://{bucket}",
            "glue.region": region,
            "s3.region": region,
        },
    )
    sink = IcebergTableSink(
        catalog=catalog,
        identifier=f"{database}.{table}",
        location=f"s3://{bucket}/bronze/{table}",
        contract=contract,
        partition_spec_builder=build_partition_spec,
    )
    sink.ensure_table()

    click.echo(f"Estimated cost: ${client.estimate_cost(spec):.2f}")

    extractor = DatabentoExtractor(client, skip_day=sink.has_day, on_event=click.echo)
    converter = DbnChunkConverter(contract, chunk_rows=chunk_rows)

    with tempfile.TemporaryDirectory(prefix="mbo-scratch-") as scratch:
        for item in extractor.extract(spec, Path(scratch)):
            rows = sink.append_chunks(
                converter.stream(item.path),
                snapshot_properties={
                    "pipeline.symbol": item.symbol,
                    "pipeline.day": str(item.day),
                },
            )
            item.path.unlink()
            click.echo(f"ingested {item.symbol} {item.day}: {rows:,} rows")


if __name__ == "__main__":
    ingest()
