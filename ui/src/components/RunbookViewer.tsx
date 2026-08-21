import ReactMarkdown from 'react-markdown'

export default function RunbookViewer({
  envName,
  contentMd,
}: {
  envName: string
  contentMd: string
}) {
  function download() {
    const blob = new Blob([contentMd], { type: 'text/markdown' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${envName}-runbook.md`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div>
      <div className="mb-4 flex justify-end">
        <button
          onClick={download}
          className="rounded-md border border-gray-300 dark:border-gray-700 px-3 py-1.5 text-xs font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800"
        >
          Download .md
        </button>
      </div>
      {/*
        prose-invert was unconditional before — correct when the app was
        dark-only, but it would make markdown text dark-on-white (unreadable)
        in light mode. dark:prose-invert lets the base `prose` preset (which
        @tailwindcss/typography tunes for light backgrounds) apply in light
        mode, and only flips to the inverted/dark preset under `.dark`.
      */}
      <div
        className="prose prose-sm dark:prose-invert max-w-none
                   prose-headings:text-gray-900 dark:prose-headings:text-white
                   prose-a:text-cyan-600 dark:prose-a:text-cyan-400
                   prose-code:font-mono prose-code:text-cyan-700 dark:prose-code:text-cyan-300
                   prose-pre:font-mono prose-pre:bg-gray-100 dark:prose-pre:bg-gray-950
                   prose-pre:border prose-pre:border-gray-200 dark:prose-pre:border-gray-800
                   prose-table:text-sm prose-th:text-gray-700 dark:prose-th:text-gray-300
                   prose-strong:text-gray-800 dark:prose-strong:text-gray-200"
      >
        <ReactMarkdown>{contentMd}</ReactMarkdown>
      </div>
    </div>
  )
}