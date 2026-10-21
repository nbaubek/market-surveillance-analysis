output "bucket_arn" {
  description = "ARN of the S3 data bucket"
  value       = module.s3_bucket.s3_bucket_arn
}

output "bucket_name" {
  description = "Name of the S3 data bucket"
  value       = module.s3_bucket.s3_bucket_id
}

output "glue_databases" {
  description = "Glue catalog databases, one per medallion layer"
  value = {
    bronze = aws_glue_catalog_database.bronze.name
    silver = aws_glue_catalog_database.silver.name
    gold   = aws_glue_catalog_database.gold.name
  }
}

output "athena_workgroup_name" {
  description = "Athena workgroup for querying the medallion layers"
  value       = aws_athena_workgroup.market_surveillance.name
}
