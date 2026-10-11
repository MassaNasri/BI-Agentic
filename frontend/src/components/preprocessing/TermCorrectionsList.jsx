import { ArrowRight } from 'lucide-react'

function TermCorrectionsList({ corrections = [] }) {
  if (!Array.isArray(corrections) || corrections.length === 0) {
    return (
      <p className="rounded-lg border border-brand-700/30 bg-[rgba(255,255,255,0.04)] p-3 text-sm text-[var(--c-muted)] dark:border-brand-700/40 dark:bg-brand-950/30 dark:text-brand-200/70">
        No explicit term corrections were required.
      </p>
    )
  }

  return (
    <div className="space-y-2">
      {corrections.map((item, index) => (
        <div
          key={`${item.original}-${item.corrected}-${index}`}
          className="rounded-lg border border-brand-700/30 bg-[var(--c-card-bg)] p-3 dark:border-brand-700/40 dark:bg-brand-950/40"
        >
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="rounded bg-red-100 px-2 py-1 text-red-700 dark:bg-red-900/40 dark:text-red-200">
              {item.original || '-'}
            </span>
            <ArrowRight className="h-4 w-4 text-brand-300/60" />
            <span className="rounded bg-green-100 px-2 py-1 text-green-800 dark:bg-green-900/40 dark:text-green-200">
              {item.corrected || '-'}
            </span>
            <span className="rounded bg-green-50 px-2 py-1 text-xs font-medium text-green-700 dark:bg-green-900/20 dark:text-green-300">
              {item.matched_column || '-'}
            </span>
          </div>
        </div>
      ))}
    </div>
  )
}

export default TermCorrectionsList
