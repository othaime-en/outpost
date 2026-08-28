# GitHub Actions — Required Repository Secrets

Five workflows now live here: `provision.yml`, `destroy.yml`, `pause.yml`,
`resume.yml`, and `ttl-cron.yml`. Required secrets, set under
**Settings → Secrets and variables → Actions**:

| Secret              | Value                                                                                                                                               | Needed by                                |
| ------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------- |
| `AWS_ROLE_ARN`      | ARN of the IAM role created during the Terraform bootstrap (Section 2.1 / `terraform/README.md`), trusted for OIDC from `repo:othaime-en/outpost:*` | provision, destroy, pause, resume        |
| `TF_STATE_BUCKET`   | `outpost-tfstate`                                                                                                                                   | provision, destroy only — see note below |
| `TF_LOCK_TABLE`     | `outpost-tflock`                                                                                                                                    | provision, destroy only                  |
| `SHARED_VPC_ID`     | The `vpc_id` output from the one-time VPC bootstrap                                                                                                 | provision, destroy only                  |
| `CALLBACK_BASE_URL` | Public base URL of the FastAPI backend (e.g. an ngrok URL for local dev, or the deployed API URL) — **no trailing slash**                           | all five                                 |
| `CALLBACK_SECRET`   | Same value as the `CALLBACK_SECRET` env var read by `app/config.py`                                                                                 | all five                                 |

`GITHUB_TOKEN` for `ttl-cron.yml`'s dispatch of `pause.yml`/`destroy.yml` is
the default token GitHub provides to every workflow run — it does **not**
need to be added manually, but the job does need `permissions: actions:
write` (already set in the workflow) for that token to be allowed to
dispatch other workflows.

## `pause.yml` / `resume.yml` need fewer secrets than provision/destroy

They never run `terraform init`/`apply`/`destroy` — they call the AWS CLI
directly against the already-provisioned ECS service and RDS instance (see
`terraform/README.md`'s "Pause/Resume are deliberately NOT managed by
Terraform" section for the full rationale). So they only need
`AWS_ROLE_ARN` + the two `CALLBACK_*` secrets, not `TF_STATE_BUCKET` /
`TF_LOCK_TABLE` / `SHARED_VPC_ID`.

**IAM policy note:** whatever policy gets attached to `AWS_ROLE_ARN` during
the eventual bootstrap needs `ecs:UpdateService`, `ecs:DescribeServices`,
`rds:StopDBInstance`, `rds:StartDBInstance`, and `rds:DescribeDBInstances`
in addition to whatever `terraform apply`/`destroy` already require — easy
to miss since provision/destroy never needed these specific actions.

## `ttl-cron.yml` now calls `/process-ttl`, not `/expired`

`GET /environments/expired` is deprecated (see its docstring in
`routers/environments.py`) — it only ever handled a single unconditional
`RUNNING` → destroy check with zero grace period, which the grace-period/
pause safety net replaces entirely. `ttl-cron.yml` now calls
`POST /environments/process-ttl` once per run, which does all three
state-machine sweeps server-side and returns `to_pause`/`to_destroy` lists;
the workflow's job is just dispatching `pause.yml`/`destroy.yml` for
whatever comes back — no state-machine logic lives in the shell script.

## Current status: AWS bootstrap not done yet

None of the secrets above are set yet — the AWS account side (Section 2.1
bootstrap: VPC, S3 bucket, DynamoDB table, OIDC provider, IAM role, shared
ECS cluster) is still pending. Terraform itself has only been validated
locally (`terraform validate` / `plan` against local state), not applied to
real AWS infra, and pause/resume haven't been exercised against real ECS/
RDS resources either.

To avoid `ttl-cron.yml` failing every 15 minutes (it's the only one of the
five with a `schedule` trigger — the other four are `workflow_dispatch`-only,
so they're inert until someone runs them manually), all five workflows
start with a **preflight step** that checks for the required secrets and
exits cleanly with an `::notice::` annotation if any are missing, instead of
letting a downstream step (like the OIDC role-assume) fail with a confusing
error. Runs will show green with the remaining steps skipped, not red.

**Once the AWS bootstrap is done and the secrets above are set, no code
change is needed** — the preflight step will detect they're present and the
workflows will run normally. (The preflight step comment in each file says
"remove this step once configured" — that's optional cleanup, not required;
leaving it in is harmless and makes future secret rotation/loss fail the
same graceful way.)

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
- `pause.yml`/`resume.yml` reconstruct the ECS service name
  (`outpost-{env_id}`) and RDS instance identifier
  (`outpost-{first 8 chars of env_id}`) directly in bash rather than reading
  them from Terraform state/outputs — they never run `terraform init`, so
  there's no state to read. If either module's naming convention ever
  changes, these two workflow files need updating in lockstep.

## Local testing without a deployed API

Set `CALLBACK_BASE_URL` to an `ngrok http 8000` tunnel pointed at your local
`docker compose up` API, and run the workflows via **Actions → Run workflow**
in the GitHub UI (all five support `workflow_dispatch`).
