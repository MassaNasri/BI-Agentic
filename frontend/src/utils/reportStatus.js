const COMPLETED_STATUSES = new Set([
  'visualization_created',
  'executed',
  'completed',
])

const PROCESSING_STATUSES = new Set([
  'uploaded',
  'transcribing',
  'transcribed',
  'generating_sql',
  'sql_generated',
  'pending',
  'processing',
  'pending_execution',
  'executing',
])

const FAILED_STATUSES = new Set(['failed'])

export const normalizeReportStatus = (status) => (status || '').toLowerCase()

export const isReportCompleted = (status) =>
  COMPLETED_STATUSES.has(normalizeReportStatus(status))

export const isReportProcessing = (status) =>
  PROCESSING_STATUSES.has(normalizeReportStatus(status))

export const isReportFailed = (status) =>
  FAILED_STATUSES.has(normalizeReportStatus(status))

export const formatReportStatus = (status) =>
  normalizeReportStatus(status).replace(/_/g, ' ')

export const getReportStatusBadgeClass = (status) => {
  if (isReportCompleted(status)) {
    return 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400'
  }
  if (isReportFailed(status)) {
    return 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400'
  }
  if (isReportProcessing(status)) {
    return 'bg-amber-500/20 text-amber-400 dark:bg-amber-400/30 dark:text-amber-400'
  }
  return 'bg-[rgba(255,255,255,0.07)] text-[var(--c-text)] dark:bg-brand-800/70 dark:text-brand-200/70'
}

