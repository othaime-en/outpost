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
          className="rounded-md border border-gray-700 px-3 py-1.5 text-xs font-medium text-gray-300 hover:bg-gray-800"
        >
          Download .md
        </button>
      </div>
      <div
        className="prose prose-invert prose-sm max-w-none
                   prose-headings:text-white prose-a:text-cyan-400
                   prose-code:font-mono prose-code:text-cyan-300
                   prose-pre:font-mono prose-pre:bg-gray-950 prose-pre:border prose-pre:border-gray-800
                   prose-table:text-sm prose-th:text-gray-300 prose-strong:text-gray-200"
      >
        <ReactMarkdown>{contentMd}</ReactMarkdown>
      </div>
    </div>
  )
}