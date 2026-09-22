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
5. When the TTL expires, it doesn't just vanish: there's a 24h grace period
   (`EXPIRING`) where nothing changes, then it's paused (`PAUSED` — ECS
   scaled to 0, RDS stopped, still reversible) before a final destroy a week
   later if nobody resumes it. Destroy manually at any point and it skips
   straight to teardown. Either way, Terraform tears everything down and the
   record is kept for the audit log.

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

The Terraform/AWS side has already been bootstrapped (S3 state bucket,
DynamoDB lock table, shared ECS cluster, OIDC role) — see
`terraform/README.md` if you're standing up a separate account.

## CLI

```bash
pip install -e ./cli
outpost auth login
outpost teams list
outpost env create --name my-feature --team platform-team --type dev --ttl 24
outpost env list
outpost env pause <env-id>
outpost audit list
```

`auth login` opens your browser and finishes automatically once GitHub
redirects back — no token to copy or paste. Running it over SSH? Use
`outpost auth login --manual` instead. See `cli/README.md` for the full
command reference.

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
Actions workflows, web UI) is built, tested, and deployed. The full
lifecycle — provision, pause, resume, extend TTL, destroy — has been
verified end-to-end against real AWS. The CLI is feature-complete
(`env`, `audit`, `teams`, `auth`) and tested against a live Postgres-backed
API instance; only PyPI/TestPyPI publishing is still outstanding.
