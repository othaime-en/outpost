import { useEffect, useState } from 'react'

function computeLabel(expiresAt: string): { label: string; expired: boolean } {
  const diff = new Date(expiresAt).getTime() - Date.now()
  if (diff <= 0) return { label: 'Expired', expired: true }
  const h = Math.floor(diff / 3_600_000)
  const m = Math.floor((diff % 3_600_000) / 60_000)
  return { label: h > 0 ? `${h}h ${m}m` : `${m}m`, expired: false }
}

/**
 * Ticks once a minute rather than every second — the TTL cron itself only
 * runs every 15 minutes, so second-level precision here would be
 * misleading, not just wasteful.
 */
export default function TTLCountdown({ expiresAt }: { expiresAt: string }) {
  const [{ label, expired }, setState] = useState(() => computeLabel(expiresAt))

  useEffect(() => {
    setState(computeLabel(expiresAt))
    const id = setInterval(() => setState(computeLabel(expiresAt)), 60_000)
    return () => clearInterval(id)
  }, [expiresAt])

  return (
    <span
      className={`font-mono text-sm ${
        expired ? 'text-red-600 dark:text-red-400' : 'text-amber-600 dark:text-amber-400'
      }`}
    >
      {label}
    </span>
  )
}