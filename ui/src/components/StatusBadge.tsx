import type { EnvStatus } from '../api/client'

// Dark-mode values match the previous presets.
// Light-mode values use the same hue at lower saturation/higher lightness
// (100/700 instead of 900/300) rather than a literal inversion, since a
// straight invert of e.g. green-900/green-300 reads as barely-there on a
// white background.
const STATUS_STYLES: Record<EnvStatus, string> = {
  PENDING: 'bg-gray-200 text-gray-700 dark:bg-gray-800 dark:text-gray-400',
  PROVISIONING: 'bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300 animate-pulse',
  RUNNING: 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300',
  // EXPIRING/PAUSING/PAUSED/RESUMING — see api/app/routers/environments.py's
  // module docstring, "GRACE PERIOD & PAUSE SAFETY NET". EXPIRING keeps a
  // distinct orange hue from DESTROYING's amber — it's a much lower-stakes
  // state (nothing has stopped yet, there's a full grace period left) and
  // shouldn't visually alarm the same way. PAUSED gets violet, since it's
  // deliberately NOT on the RUNNING(green) -> DESTROYED(gray) axis at all —
  // it's a genuinely different, reversible resting state.
  EXPIRING: 'bg-orange-100 text-orange-700 dark:bg-orange-900 dark:text-orange-300 animate-pulse',
  PAUSING: 'bg-violet-100 text-violet-700 dark:bg-violet-900 dark:text-violet-300 animate-pulse',
  PAUSED: 'bg-violet-100 text-violet-700 dark:bg-violet-900 dark:text-violet-400',
  RESUMING: 'bg-cyan-100 text-cyan-700 dark:bg-cyan-900 dark:text-cyan-300 animate-pulse',
  DESTROYING: 'bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300 animate-pulse',
  DESTROYED: 'bg-gray-200 text-gray-500 dark:bg-gray-800 dark:text-gray-500',
  FAILED: 'bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300',
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