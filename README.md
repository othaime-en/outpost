# Outpost

Self-service provisioning for short-lived cloud environments. Request a dev or
staging environment, get a running ECS service and RDS database a few minutes
later, and let it tear itself down when the TTL runs out — no ticket, no
waiting on ops.

Built as a full platform: a FastAPI backend, a Terraform + GitHub Actions
provisioning pipeline, a React dashboard, and a CLI.

## How it works

1. You ask for an environment (name, type, TTL) through the UI or CLI.
2. The API writes a `PENDING` row and dispatches a GitHub Actions workflow.
3. Terraform provisions a VPC subnet, security group, ECS service, and RDS
   instance, then calls back to the API with the outputs.
4. The environment moves to `RUNNING`. A runbook is generated automatically —
   connection info, log commands, TTL reminder.
5. When the TTL expires (or you destroy it manually), Terraform tears
   everything down and the record is kept for the audit log.

Every AWS resource is tagged with `env_id`, `team`, and `ttl`, which is how
cost tracking and targeted destroys work.

## Stack

FastAPI · PostgreSQL · SQLAlchemy/Alembic · React + TypeScript + Tailwind ·
Terraform · GitHub Actions · AWS (ECS Fargate, RDS, Secrets Manager,
CloudWatch)

## Running it locally

```bash
cp .env.example .env   # fill in GitHub OAuth credentials
docker compose up
```

API comes up on `:8000`, UI on `:3000`. `docker compose exec api alembic
upgrade head` to apply migrations.

The Terraform/AWS side needs a one-time bootstrap (S3 state bucket, DynamoDB
lock table, shared ECS cluster, OIDC role) before any environment can
actually provision — see `terraform/README.md`.

## CLI

```bash
pip install -e ./cli
outpost auth login
outpost env create --name my-feature --type dev --ttl 24
outpost env list
```

## Why it's built this way

A few decisions worth knowing before reading the code:

- **Provisioning is async.** `POST /environments` returns `202` immediately;
  Terraform runs in GitHub Actions and calls back when it's done. Terraform
  takes minutes, not milliseconds — blocking the request isn't an option.
- **No static AWS credentials anywhere.** GitHub Actions assumes an IAM role
  over OIDC. Nothing to rotate, nothing to leak.
- **One Terraform workspace per environment**, state keyed by `env_id` in S3.
  Destroying one environment can't touch another's resources.
- **Environments are soft-deleted.** The row, audit trail, and cost history
  survive destruction — you can still see what an environment cost and who
  killed it.

## Status

Core platform (auth, RBAC, provisioning API, Terraform modules, GitHub
Actions workflows, web UI) is built and tested. Live AWS provisioning is
blocked on the one-time account bootstrap described above.
