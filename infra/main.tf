module "s3_bucket" {
  source  = "terraform-aws-modules/s3-bucket/aws"
  version = "~> 5.0"

  bucket        = "trading-surveillance-data"
  acl           = "private"
  force_destroy = true

  control_object_ownership = true
  object_ownership         = "ObjectWriter"

  versioning = {
    enabled = false
  }

  lifecycle_rule = [
    {
      id      = "expire-athena-results"
      enabled = true
      filter = {
        prefix = "athena-results/"
      }
      expiration = {
        days = 30
      }
    },
  ]
}
