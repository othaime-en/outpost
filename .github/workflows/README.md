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

**IAM policy note:** the policy attached to `AWS_ROLE_ARN` includes
`ecs:UpdateService`, `ecs:DescribeServices`, `rds:StopDBInstance`,
`rds:StartDBInstance`, and `rds:DescribeDBInstances` in addition to what
`terraform apply`/`destroy` need — confirmed working via `pause`/`resume`
against real AWS.

## `ttl-cron.yml` now calls `/process-ttl`, not `/expired`

`GET /environments/expired` is deprecated (see its docstring in
`routers/environments.py`) — it only ever handled a single unconditional
`RUNNING` → destroy check with zero grace period, which the grace-period/
pause safety net replaces entirely. `ttl-cron.yml` now calls
`POST /environments/process-ttl` once per run, which does all three
state-machine sweeps server-side and returns `to_pause`/`to_destroy` lists;
the workflow's job is just dispatching `pause.yml`/`destroy.yml` for
whatever comes back — no state-machine logic lives in the shell script.

## Two independent ways to stop TTL enforcement — don't confuse them

**`PATCH /settings/ttl-enforcement`** (super_admin only, via the Settings
page or the API directly — see `routers/settings.py`) is a DB-backed
runtime toggle. With it off, `process_ttl()` returns immediately with
nothing to do — `ttl-cron.yml` still calls the API successfully every 15
minutes and gets a clean, honest empty result back. Use this for a
temporary pause (a demo, an interview walkthrough, a cost-sensitive week)
**while the platform host is still up and reachable**.

**`vars.TTL_CRON_ENABLED`** (a GitHub Actions repository _variable_, not a
secret — `Settings → Secrets and variables → Actions → Variables`) is a
job-level `if:` guard in `ttl-cron.yml` itself. Set it to `"false"` and the
whole job — including the API call — is skipped, showing as a clean grey
"skipped" run instead of a red failure. Use this once the platform host is
**genuinely, permanently decommissioned** and there's no API left to call
at all — the DB toggle can't help there, since it still requires a
successful HTTP round-trip to report "disabled."

## Current status: AWS bootstrap complete, all secrets set

All six secrets above are set in GitHub Actions. Terraform has been applied
against real AWS, and provision, pause, resume, TTL extension, and destroy
have all been exercised end-to-end against live ECS/RDS resources.

All five workflows still start with a **preflight step** that checks for
the required secrets and exits cleanly with an `::notice::` annotation if
any are missing, instead of letting a downstream step (like the OIDC
role-assume) fail with a confusing error. It's no longer covering for a
missing bootstrap — it's now a cheap guard against a secret getting rotated
out or accidentally deleted, so a future run degrades to a clean grey
"skipped" instead of a red failure. (The preflight step comment in each
file says "remove this step once configured" — still optional; there's no
real reason to remove it now.)

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
