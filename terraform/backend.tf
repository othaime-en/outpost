# Partial backend configuration.
#
# NOTE: Terraform backend blocks cannot reference input variables (not even
# var.env_id) -- HCL evaluates backend config before any variables are
# resolved. The plan's original backend.tf tried to interpolate var.env_id
# into `key`, which is invalid and would fail `terraform init`.
#
# Instead, all values are supplied at init time via -backend-config flags,
# which is exactly what provision.yml / destroy.yml already do:
#
#   terraform init \
#     -backend-config="bucket=idp-lite-tfstate" \
#     -backend-config="key=envs/<env_id>/terraform.tfstate" \
#     -backend-config="region=us-east-1" \
#     -backend-config="dynamodb_table=idp-lite-tflock"
#
# For local development against a single scratch environment, see
# terraform/README.md for an equivalent local command.
terraform {
  backend "s3" {
    encrypt = true
  }
}
