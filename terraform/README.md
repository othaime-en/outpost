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

## Pause/Resume are deliberately NOT managed by Terraform

The grace-period/pause safety net (see `routers/environments.py`'s module
docstring, "GRACE PERIOD & PAUSE SAFETY NET", in the API) scales the ECS
service to 0 and stops the RDS instance for a paused environment, then
reverses both on resume. This is handled entirely by
`.github/workflows/pause.yml` / `resume.yml` calling the AWS CLI directly —
`aws ecs update-service --desired-count 0/1`, `aws rds stop-db-instance` /
`start-db-instance` — never by `terraform apply`.

This is intentional, not a shortcut: `aws_ecs_service.env.desired_count` in
`modules/ecs/main.tf` is hardcoded to `1`. If pause/resume went through
Terraform instead, the very next real `terraform apply` against that
workspace (there isn't one in the current design, but if one were ever
added — a config change to an already-RUNNING environment, say) would just
reconcile `desired_count` back to `1` and silently undo a pause. Scale/stop
state is runtime, operational state, not something this project wants
Terraform treating as declarative infrastructure config. `terraform
destroy` still works correctly on a paused environment regardless of
current desired_count/RDS status — AWS allows deleting a stopped RDS
instance and a zero-task ECS service without issue.

**IAM implication:** the GitHub Actions role (`AWS_ROLE_ARN`) needs
`ecs:UpdateService`, `ecs:DescribeServices`, `rds:StopDBInstance`,
`rds:StartDBInstance`, and `rds:DescribeDBInstances` in addition to
whatever policy already covers `terraform apply`/`destroy` — not yet
written since the AWS bootstrap (Section 2.1 above) hasn't happened. Flag
this when that policy finally gets written; it's an easy one to miss since
`provision.yml`/`destroy.yml` never needed it.

## Deviations from the written plan (flagged, not silent)

| Area             | Plan said                                             | Implemented instead                                                            | Why                                                                                            |
| ---------------- | ----------------------------------------------------- | ------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------- |
| `backend.tf`     | `key = "envs/${var.env_id}/terraform.tfstate"` inline | Empty/partial `backend "s3" {}`, all values via `-backend-config` flags        | Terraform backend blocks cannot reference input variables — this would fail `terraform init`   |
| Networking       | One subnet per env                                    | Two subnets (two AZs) per env                                                  | `aws_db_subnet_group` requires >= 2 AZs; single-subnet design would fail on RDS creation       |
| Security group   | Only port 8080 ingress from `10.0.0.0/8`              | Added self-referencing port 5432 ingress; tightened 8080 rule to `10.0.0.0/16` | ECS task otherwise has no path to RDS on 5432; `/8` was broader than the VPC itself            |
| ECS task role    | Only a custom `secretsmanager:GetSecretValue` policy  | Added AWS-managed `AmazonECSTaskExecutionRolePolicy`                           | Without it, Fargate can't pull the image or write CloudWatch logs — the task would never start |
| Secret injection | `valueFrom = var.rds_secret_arn` (whole JSON blob)    | `valueFrom = "${secret_arn}:url::"`                                            | Container needs the connection string, not the raw JSON secret                                 |
| Bootstrap (2.1)  | Didn't create the shared ECS cluster                  | Added `aws ecs create-cluster --cluster-name outpost-shared`                   | `data "aws_ecs_cluster"` in the ecs module would fail to resolve otherwise                     |

Everything else (module boundaries, tagging scheme, naming conventions,
`db.t3.micro`, `skip_final_snapshot = true`, `deletion_protection = false`,
OIDC-only AWS auth) follows the plan as written.
