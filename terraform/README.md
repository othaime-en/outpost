# Outpost — Terraform

Provisions one environment's AWS infrastructure: an isolated subnet pair +
security group, an ECS Fargate service, an RDS Postgres instance, and a
Secrets Manager entry tying them together. One Terraform workspace (one
state file, keyed by `env_id`) per environment.

## Updated one-time bootstrap (Section 2.1)

Everything below is created **once**, manually, before any environment is
ever provisioned. It is not managed by this Terraform configuration.

```bash
# Shared VPC
aws ec2 create-vpc --cidr-block 10.0.0.0/16

# S3 bucket for TF state (versioning required)
aws s3api create-bucket --bucket outpost-tfstate --region us-east-1
aws s3api put-bucket-versioning --bucket outpost-tfstate \
    --versioning-configuration Status=Enabled

# DynamoDB table for state locking
aws dynamodb create-table \
    --table-name outpost-tflock \
    --attribute-definitions AttributeName=LockID,AttributeType=S \
    --key-schema AttributeName=LockID,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST

# OIDC provider for GitHub Actions
aws iam create-open-id-connect-provider \
    --url https://token.actions.githubusercontent.com \
    --client-id-list sts.amazonaws.com \
    --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1

# Shared ECS cluster -- ADDED. The plan's bootstrap list never created this,
# but modules/ecs/main.tf looks it up via `data "aws_ecs_cluster"`, so it
# must exist before the first `terraform apply`.
aws ecs create-cluster --cluster-name outpost-shared
```

The GitHub Actions IAM role trust policy is unchanged from the plan
(Section 2.1) — scoped to `repo:YOUR_ORG/outpost:*`.

## Local validation (no real AWS calls)

```bash
cd terraform
terraform init -backend=false   # skips S3 backend, just resolves modules/providers
terraform validate
terraform fmt -check -recursive
```

## Local plan/apply against a real (test) AWS account

```bash
cd terraform
terraform init \
  -backend-config="bucket=outpost-tfstate" \
  -backend-config="key=envs/test-local/terraform.tfstate" \
  -backend-config="region=us-east-1" \
  -backend-config="dynamodb_table=outpost-tflock"

cp terraform.tfvars.example terraform.tfvars   # edit vpc_id, etc.
terraform plan
terraform apply
# verify resources in the AWS console, then:
terraform destroy
```

## Deviations from the written plan (flagged, not silent)

| Area             | Plan said                                             | Implemented instead                                                            | Why                                                                                            |
| ---------------- | ----------------------------------------------------- | ------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------- |
| `backend.tf`     | `key = "envs/${var.env_id}/terraform.tfstate"` inline | Empty/partial `backend "s3" {}`, all values via `-backend-config` flags        | Terraform backend blocks cannot reference input variables — this would fail `terraform init`   |
| Networking       | One subnet per env                                    | Two subnets (two AZs) per env                                                  | `aws_db_subnet_group` requires >= 2 AZs; single-subnet design would fail on RDS creation       |
| Security group   | Only port 8080 ingress from `10.0.0.0/8`              | Added self-referencing port 5432 ingress; tightened 8080 rule to `10.0.0.0/16` | ECS task otherwise has no path to RDS on 5432; `/8` was broader than the VPC itself            |
| ECS task role    | Only a custom `secretsmanager:GetSecretValue` policy  | Added AWS-managed `AmazonECSTaskExecutionRolePolicy`                           | Without it, Fargate can't pull the image or write CloudWatch logs — the task would never start |
| Secret injection | `valueFrom = var.rds_secret_arn` (whole JSON blob)    | `valueFrom = "${secret_arn}:url::"`                                            | Container needs the connection string, not the raw JSON secret                                 |
| Bootstrap (2.1)  | Didn't create the shared ECS cluster                  | Added `aws ecs create-cluster --cluster-name outpost-shared`                  | `data "aws_ecs_cluster"` in the ecs module would fail to resolve otherwise                     |

Everything else (module boundaries, tagging scheme, naming conventions,
`db.t3.micro`, `skip_final_snapshot = true`, `deletion_protection = false`,
OIDC-only AWS auth) follows the plan as written.
