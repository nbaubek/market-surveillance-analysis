# Glue Data Catalog databases — one per medallion layer, so the Athena
# editor's database selector doubles as the layer selector.
# The tables themselves (itch_mbo, itch_mbo_cleaned, hourly_liquidity_metrics)
# are created by the pipeline (PyIceberg/Athena DDL/dbt) — an Iceberg table
# needs metadata files that Terraform cannot bootstrap on its own.
resource "aws_glue_catalog_database" "bronze" {
  name         = "market_surveillance_bronze"
  location_uri = "s3://trading-surveillance-data/bronze/"
}

resource "aws_glue_catalog_database" "silver" {
  name         = "market_surveillance_silver"
  location_uri = "s3://trading-surveillance-data/silver/"
}

resource "aws_glue_catalog_database" "gold" {
  name         = "market_surveillance_gold"
  location_uri = "s3://trading-surveillance-data/gold/"
}
