export default function CostBadge({ costUsd }: { costUsd: number | null }) {
  if (costUsd === null) {
    return <span className="font-mono text-xs text-gray-500 dark:text-gray-600">cost n/a</span>
  }
  return (
    <span className="font-mono text-xs text-gray-500 dark:text-gray-400">
      ~<span className="text-gray-700 dark:text-gray-300">${costUsd.toFixed(2)}</span>/mo
    </span>
  )
}