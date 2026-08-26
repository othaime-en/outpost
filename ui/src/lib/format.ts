/** Truncates a UUID to its first 8 chars for compact display, full value on hover via title=. */
export function shortId(id: string): string {
  return id.slice(0, 8)
}

/** Simple relative-time formatter — "3m ago", "2h ago", "5d ago" — no dependency needed for this scale. */
export function formatRelativeTime(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime()
  const diffSec = Math.floor(diffMs / 1000)
  if (diffSec < 60) return 'just now'
  const diffMin = Math.floor(diffSec / 60)
  if (diffMin < 60) return `${diffMin}m ago`
  const diffHour = Math.floor(diffMin / 60)
  if (diffHour < 24) return `${diffHour}h ago`
  const diffDay = Math.floor(diffHour / 24)
  if (diffDay < 30) return `${diffDay}d ago`
  const diffMonth = Math.floor(diffDay / 30)
  return `${diffMonth}mo ago`
}

/** Formats an ISO timestamp as "YYYY-MM-DD HH:MM UTC", matching the CLI/runbook convention. */
export function formatUTC(iso: string): string {
  return iso.slice(0, 16).replace('T', ' ') + ' UTC'
}

// Grace period length must match app/config.py's expiring_grace_period_hours
// default (24h) — there's no field on Environment carrying this today (it's
// a global platform constant, not per-environment), so it's duplicated
// here the same way PAUSED_MAX_DAYS is duplicated in
// useEnvironmentActions.tsx's pause confirmation copy. If either changes
// on the backend, update both.
const EXPIRING_GRACE_PERIOD_HOURS = 24

/**
 * What to show in an "expires"-style countdown slot for a given
 * environment, and which timestamp it should count down to. Centralizes
 * the per-status logic (see api/app/routers/environments.py's module
 * docstring, "GRACE PERIOD & PAUSE SAFETY NET") in one place so
 * EnvironmentCard and EnvironmentDetail can't reimplement it and drift
 * apart. `targetIso: null` means "no countdown — show a dash instead",
 * which TTLCountdown itself doesn't know how to do (it always expects a
 * real timestamp).
 */
export function expiryDisplay(env: {
  status: string
  expires_at: string
  expiring_since: string | null
  pause_expires_at: string | null
}): { label: string; targetIso: string | null } {
  switch (env.status) {
    case 'DESTROYED':
      return { label: 'destroyed', targetIso: null }
    case 'PAUSED':
    case 'PAUSING':
      // expires_at is frozen while paused (deliberately left untouched —
      // see environment_callback()'s PAUSED branch), so it would show a
      // stale/misleading countdown here. pause_expires_at is the timestamp
      // that actually matters while paused: when the TTL cron will destroy
      // this for real if nobody resumes it.
      return { label: 'auto-destroys in', targetIso: env.pause_expires_at }
    case 'EXPIRING': {
      // Same reasoning in reverse: expires_at is already in the past by
      // definition here (that's what triggered EXPIRING), so counting down
      // to it would just show "Expired" in red — true, but not the
      // countdown that's actually relevant right now, which is how long
      // until the grace period lapses and auto-pause kicks in.
      if (!env.expiring_since) return { label: 'auto-pauses soon', targetIso: null }
      const target = new Date(
        new Date(env.expiring_since).getTime() + EXPIRING_GRACE_PERIOD_HOURS * 3_600_000
      )
      return { label: 'auto-pauses in', targetIso: target.toISOString() }
    }
    case 'RESUMING':
      // A fresh expires_at doesn't exist yet — it's only granted once the
      // RESUMING -> RUNNING callback actually lands.
      return { label: 'resuming…', targetIso: null }
    default:
      return { label: 'expires in', targetIso: env.expires_at }
  }
}