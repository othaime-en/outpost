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