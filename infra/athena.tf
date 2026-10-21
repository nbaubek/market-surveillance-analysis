# Athena workgroup: query surface for the medallion layers.
# Query results land under a dedicated prefix (auto-cleaned by the bucket
# lifecycle rule in main.tf).
resource "aws_athena_workgroup" "market_surveillance" {
  name = "market-surveillance"

  configuration {
    result_configuration {
      output_location = "s3://trading-surveillance-data/athena-results/"
    }
  }
}
