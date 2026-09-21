# Outpost CLI

A thin `outpost` command over the same REST API the web UI uses. No logic
lives here beyond team-slug resolution and output formatting — every
command maps to one real endpoint in `api/app/routers/`.

## Install

```bash
cd cli
pip install -e .
outpost --version
```

## Configuration

State lives in `~/.outpost/config.yaml` (created for you, `chmod 600`):

```yaml
endpoint: https://outpost-api.othaimeen.dev # or http://localhost:8000 for local dev
token: <short-lived, set by `auth login`>
api_key: <long-lived, set by `auth key generate`>
```

Every command except `auth login`/`auth key generate` uses `api_key` via
the `X-API-Key` header. You only need to do the `auth` steps once per
machine — the key doesn't expire on its own.

## Auth

```bash
outpost auth login                 # opens your browser to GitHub OAuth
# ... complete login, copy the token shown on the frontend's /callback page ...
# Paste the token shown after login completes: <paste here>

outpost auth key generate          # exchanges that token for a permanent API key
```

`login` only gets you a 15-minute bearer token — just long enough to run
`key generate` once. If you wait too long between the two, `key generate`
will tell you to log in again rather than failing silently.

## Teams

Every environment belongs to a team, and you can only create/list against
teams you're a member of (`super_admin` sees all). This CLI doesn't do
team management — that's in the web UI — but `teams list` is enough to
find the slug you need below.

```bash
outpost teams list
```

```
NAME            SLUG            ID
Platform Team   platform-team   adaf4aa6-e513-41e7-86c7-043f4fd2f182
```

## Environments

`--team` on `create`/`list` accepts a slug, display name, or raw ID —
resolved against your own memberships, so passing a team you're not on
fails locally with a clear message instead of a 403 from the API.

### Create

```bash
outpost env create --name my-feature --team platform-team --type dev
outpost env create --name my-feature --team platform-team --type staging --ttl 48 --region us-west-2
```

| Flag       | Required | Default     | Notes                                 |
| ---------- | -------- | ----------- | ------------------------------------- |
| `--name`   | yes      | —           | lowercase, alphanumeric, hyphens only |
| `--team`   | yes      | —           | slug, name, or ID                     |
| `--type`   | yes      | —           | `dev` \| `staging`                    |
| `--ttl`    | no       | `24`        | hours until auto-destroy, 1–168       |
| `--region` | no       | `us-east-1` |                                       |

Returns immediately with `status: PENDING` — Terraform runs
asynchronously in GitHub Actions. Poll with `env status`.

### List

```bash
outpost env list                                    # everything across your teams, DESTROYED excluded
outpost env list --status RUNNING --status FAILED    # repeat --status to pass several
outpost env list --team platform-team --mine
outpost env list --expiring-within 6
outpost env list --include-destroyed
outpost env list --sort-by cost_estimate_usd --sort-dir desc
outpost env list --json                              # for scripting
```

### Status

```bash
outpost env status <env-id>
outpost env status <env-id> --json
```

Shows outputs (ARNs, endpoints), health, cost estimate, and — when
relevant — the grace-period/pause fields (`expiring_since`, `paused_at`,
`pause_expires_at`).

### Pause / resume

Reversible: ECS scaled to 0, RDS stopped — cheaper than running, not
free. Available from `RUNNING` or `EXPIRING`; resuming grants a fresh TTL
window rather than picking up wherever it left off.

```bash
outpost env pause <env-id>
outpost env resume <env-id>
```

### Extend TTL

```bash
outpost env extend <env-id> --hours 24
```

If the environment is in the `EXPIRING` grace period, this also cancels
the grace period and returns it to `RUNNING`.

### Destroy

```bash
outpost env destroy <env-id>          # prompts for confirmation
outpost env destroy <env-id> --yes    # skip the prompt (scripting)
```

Real infrastructure teardown from `RUNNING`/`FAILED`/`EXPIRING`/`PAUSED`
goes through `DESTROYING` and waits for GitHub Actions to confirm. A
still-`PENDING` environment (one that never got a provisioning callback)
is closed immediately instead — see the audit log's `ENV_CANCELLED`
vs. `ENV_DESTROYED` distinction if you're checking `audit list` output.

### Runbook

```bash
outpost env runbook <env-id>                    # rendered to the terminal
outpost env runbook <env-id> -o runbook.md       # saved to a file
```

Only available once the environment has reached `RUNNING` at least once.

## Audit log

Read-only. You see rows for any team you belong to, plus anything you
personally did (even actions with no environment attached, like
`API_KEY_GENERATED`).

```bash
outpost audit list
outpost audit list --env <env-id>
outpost audit list --action ENV_CREATED
outpost audit list --actor-type cron
outpost audit list --page 2 --page-size 20
outpost audit list --json
```

## Scripting

Every `list`/`status`/`audit list` command takes `--json` for raw output
instead of a Rich table — pipe into `jq`, etc. Non-2xx responses print the
API's own error message and exit `1`; a confirmation prompt aborts with
exit `1` too, so `destroy` without `--yes` is safe to leave out of scripts
by accident (it won't silently proceed).

## Not built yet

- `outpost env cost-preview` / cost-snapshots — the read endpoint always
  returns `[]` until the Cost Explorer background job exists.
- Publishing to PyPI/TestPyPI — install from source for now.
