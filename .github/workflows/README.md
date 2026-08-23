# GitHub Actions — Required Repository Secrets

These three workflows (`provision.yml`, `destroy.yml`, `ttl-cron.yml`)
require the following secrets, set under
**Settings → Secrets and variables → Actions**:

| Secret              | Value                                                                                                                                               |
| ------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| `AWS_ROLE_ARN`      | ARN of the IAM role created during the Terraform bootstrap (Section 2.1 / `terraform/README.md`), trusted for OIDC from `repo:othaime-en/outpost:*` |
| `TF_STATE_BUCKET`   | `outpost-tfstate`                                                                                                                                  |
| `TF_LOCK_TABLE`     | `outpost-tflock`                                                                                                                                   |
| `SHARED_VPC_ID`     | The `vpc_id` output from the one-time VPC bootstrap                                                                                                 |
| `CALLBACK_BASE_URL` | Public base URL of the FastAPI backend (e.g. an ngrok URL for local dev, or the deployed API URL) — **no trailing slash**                           |
| `CALLBACK_SECRET`   | Same value as the `CALLBACK_SECRET` env var read by `app/config.py`                                                                                 |

`GITHUB_TOKEN` for the `ttl-cron.yml` → `destroy.yml` dispatch is the
default token GitHub provides to every workflow run — it does **not** need
to be added manually, but the job does need `permissions: actions: write`
(already set in the workflow) for that token to be allowed to dispatch
another workflow.

## Current status: AWS bootstrap not done yet

None of the six secrets above are set yet — the AWS account side (Section
2.1 bootstrap: VPC, S3 bucket, DynamoDB table, OIDC provider, IAM role,
shared ECS cluster) is still pending. Terraform itself has only been
validated locally (`terraform validate` / `plan` against local state), not
applied to real AWS infra.

To avoid `ttl-cron.yml` failing every 15 minutes (it's the only one of the
three with a `schedule` trigger — `provision.yml` and `destroy.yml` are
`workflow_dispatch`-only, so they're inert until someone runs them
manually), all three workflows start with a **preflight step** that checks
for the required secrets and exits cleanly with an `::notice::` annotation
if any are missing, instead of letting a downstream step (like the OIDC
role-assume) fail with a confusing error. Runs will show green with the
remaining steps skipped, not red.

**Once the AWS bootstrap is done and the secrets above are set, no code
change is needed** — the preflight step will detect they're present and
the workflows will run normally. (The preflight step comment in each file
says "remove this step once configured" — that's optional cleanup, not
required; leaving it in is harmless and makes future secret rotation/loss
fail the same graceful way.)

## Notes specific to this repo's Terraform (see `terraform/README.md`)

- `backend.tf` is intentionally empty (`backend "s3" { encrypt = true }`) —
  all backend values are supplied via `-backend-config` flags at `terraform
init` time in both `provision.yml` and `destroy.yml`. This is required
  because Terraform backend blocks can't reference `var.env_id`.
- `terraform output -json` nests each output as `{"value": ..., "type": ...}`.
  `provision.yml` flattens this with `jq` before POSTing to `/callback`, so
  the API always receives a flat `{"name": value}` map (matching what the
  Phase 5 runbook template expects).
- The shared ECS cluster (`outpost-shared`) referenced by
  `modules/ecs/main.tf` via a `data` source must exist before the first
  `provision.yml` run — see the bootstrap step added in `terraform/README.md`.

## Local testing without a deployed API

Set `CALLBACK_BASE_URL` to an `ngrok http 8000` tunnel pointed at your local
`docker compose up` API, and run the workflows via **Actions → Run workflow**
in the GitHub UI (all three support `workflow_dispatch`).
