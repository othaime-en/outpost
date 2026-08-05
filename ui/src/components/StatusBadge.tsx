import type { EnvStatus } from '../api/client'

// Colors match Section 6.1 of the implementation plan exactly.
const STATUS_STYLES: Record<EnvStatus, string> = {
  PENDING: 'bg-gray-800 text-gray-400',
  PROVISIONING: 'bg-blue-900 text-blue-300 animate-pulse',
  RUNNING: 'bg-green-900 text-green-300',
  DESTROYING: 'bg-amber-900 text-amber-300 animate-pulse',
  DESTROYED: 'bg-gray-800 text-gray-500',
  FAILED: 'bg-red-900 text-red-300',
}

export default function StatusBadge({ status }: { status: EnvStatus }) {
  return (
    <span
      className={`inline-block rounded px-2 py-0.5 text-xs font-mono font-semibold tracking-wide ${STATUS_STYLES[status]}`}
    >
      {status}
    </span>
  )
}