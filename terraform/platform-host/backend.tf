terraform {
  # Values supplied via -backend-config flags at `terraform init` time —
  # same reasoning as terraform/backend.tf: this block can't reference input variables.
  # Suggested: terraform init -backend-config="bucket=<your-tf-state-bucket>" \
  #   -backend-config="key=platform-host/terraform.tfstate" \
  #   -backend-config="region=<aws_region>" \
  #   -backend-config="dynamodb_table=<your-lock-table>"
  backend "s3" {}
}