# GitHub Actions — Required Repository Secrets

These three workflows (`provision.yml`, `destroy.yml`, `ttl-cron.yml`)
require the following secrets, set under
**Settings → Secrets and variables → Actions**:

| Secret              | Value                                                                                                                                               |
| ------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| `AWS_ROLE_ARN`      | ARN of the IAM role created during the Terraform bootstrap (Section 2.1 / `terraform/README.md`), trusted for OIDC from `repo:othaime-en/idplite:*` |
| `TF_STATE_BUCKET`   | `idp-lite-tfstate`                                                                                                                                  |
| `TF_LOCK_TABLE`     | `idp-lite-tflock`                                                                                                                                   |
| `SHARED_VPC_ID`     | The `vpc_id` output from the one-time VPC bootstrap                                                                                                 |
| `CALLBACK_BASE_URL` | Public base URL of the FastAPI backend (e.g. an ngrok URL for local dev, or the deployed API URL) — **no trailing slash**                           |
| `CALLBACK_SECRET`   | Same value as the `CALLBACK_SECRET` env var read by `app/config.py`                                                                                 |

`GITHUB_TOKEN` for the `ttl-cron.yml` → `destroy.yml` dispatch is the
default token GitHub provides to every workflow run — it does **not** need
to be added manually, but the job does need `permissions: actions: write`
(already set in the workflow) for that token to be allowed to dispatch
another workflow.

## Notes specific to this repo's Terraform (see `terraform/README.md`)

- `backend.tf` is intentionally empty (`backend "s3" { encrypt = true }`) —
  all backend values are supplied via `-backend-config` flags at `terraform
init` time in both `provision.yml` and `destroy.yml`. This is required
  because Terraform backend blocks can't reference `var.env_id`.
- `terraform output -json` nests each output as `{"value": ..., "type": ...}`.
  `provision.yml` flattens this with `jq` before POSTing to `/callback`, so
  the API always receives a flat `{"name": value}` map (matching what the
  Phase 5 runbook template expects).
- The shared ECS cluster (`idp-lite-shared`) referenced by
  `modules/ecs/main.tf` via a `data` source must exist before the first
  `provision.yml` run — see the bootstrap step added in `terraform/README.md`.

## Local testing without a deployed API

Set `CALLBACK_BASE_URL` to an `ngrok http 8000` tunnel pointed at your local
`docker compose up` API, and run the workflows via **Actions → Run workflow**
in the GitHub UI (all three support `workflow_dispatch`).
