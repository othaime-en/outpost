import type { ReactNode } from 'react'

export default function Modal({
  title,
  onClose,
  children,
}: {
  title: string
  onClose: () => void
  children: ReactNode
}) {
  return (
    <div
      className="fixed inset-0 z-20 flex items-center justify-center bg-black/60 px-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-sm rounded-xl border border-gray-800 bg-gray-900 p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="mb-4 text-lg font-semibold text-white">{title}</h2>
        {children}
      </div>
    </div>
  )
}