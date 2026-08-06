import type { HealthStatus } from '../api/client'

const HEALTH_STYLES: Record<HealthStatus, string> = {
  HEALTHY: 'bg-green-400',
  DEGRADED: 'bg-amber-400 animate-pulse',
  UNKNOWN: 'bg-gray-500',
}

const HEALTH_LABELS: Record<HealthStatus, string> = {
  HEALTHY: 'Healthy',
  DEGRADED: 'Degraded',
  UNKNOWN: 'Health unknown',
}

export default function HealthIndicator({ status }: { status: HealthStatus }) {
  return (
    <span
      className={`inline-block h-2 w-2 shrink-0 rounded-full ${HEALTH_STYLES[status]}`}
      title={HEALTH_LABELS[status]}
      aria-label={HEALTH_LABELS[status]}
    />
  )
}