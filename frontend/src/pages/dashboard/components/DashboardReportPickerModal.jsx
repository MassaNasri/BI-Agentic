import { useMemo, useState } from 'react'
import { Loader2, Search } from 'lucide-react'

import { Button, Modal } from '../../../components'
import { formatReportStatus, getReportStatusBadgeClass } from '../../../utils/reportStatus'

function DashboardReportPickerModal({
  isOpen,
  onClose,
  reports,
  attachedReportIds,
  isLoading,
  isAddingReport,
  onAttachReport,
  canCreateReport,
  onCreateReport,
}) {
  const [searchTerm, setSearchTerm] = useState('')

  const normalizedQuery = String(searchTerm || '').trim().toLowerCase()
  const filteredReports = useMemo(() => {
    if (!normalizedQuery) return reports
    return reports.filter((report) => {
      const title = String(report?.title || '').toLowerCase()
      const transcription = String(report?.transcription || '').toLowerCase()
      const idText = String(report?.id || '')
      return (
        title.includes(normalizedQuery) ||
        transcription.includes(normalizedQuery) ||
        idText.includes(normalizedQuery)
      )
    })
  }, [normalizedQuery, reports])

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Add Report To Page" size="xl">
      <div className="space-y-4">
        <div className="flex items-center justify-between gap-3">
          <div className="relative flex-1">
            <Search className="w-4 h-4 text-brand-300/60 absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              value={searchTerm}
              onChange={(event) => setSearchTerm(event.target.value)}
              placeholder="Search reports by title, report ID, or query text..."
              className="w-full border border-brand-700/30 rounded-lg pl-9 pr-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400/30"
            />
          </div>

          {canCreateReport ? (
            <Button type="button" onClick={onCreateReport}>
              Create New Report
            </Button>
          ) : null}
        </div>

        {isLoading ? (
          <div className="rounded-lg border border-brand-700/30 py-12 text-center text-brand-300/80 text-sm">
            <Loader2 className="w-5 h-5 animate-spin mx-auto mb-2" />
            Loading reports...
          </div>
        ) : filteredReports.length === 0 ? (
          <div className="rounded-lg border border-brand-700/30 py-12 text-center text-brand-300/80 text-sm">
            No reports found for your search.
          </div>
        ) : (
          <div className="space-y-2 max-h-[520px] overflow-y-auto pr-1">
            {filteredReports.map((report) => {
              const reportId = Number(report?.id || 0)
              const isAttached = attachedReportIds.has(reportId)
              const reportTitle = String(report?.title || '').trim() || `Report #${reportId}`
              const reportStatus = String(report?.status || '').trim() || 'unknown'
              const previewText = String(report?.transcription || '').trim()

              return (
                <div key={reportId} className="border border-brand-700/30 rounded-lg p-3 bg-[var(--c-card-bg)]">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="text-sm font-semibold text-white truncate">{reportTitle}</p>
                      <div className="mt-1 flex items-center gap-2">
                        <span className={`px-2 py-1 rounded-full text-[11px] font-medium ${getReportStatusBadgeClass(reportStatus)}`}>
                          {formatReportStatus(reportStatus)}
                        </span>
                        <span className="text-xs text-brand-300/80">ID #{reportId}</span>
                      </div>
                      {previewText ? (
                        <p className="mt-2 text-xs text-[var(--c-muted)] line-clamp-2">{previewText}</p>
                      ) : null}
                    </div>

                    <Button
                      type="button"
                      size="sm"
                      variant={isAttached ? 'secondary' : 'primary'}
                      disabled={isAttached || isAddingReport}
                      onClick={() => onAttachReport(reportId)}
                    >
                      {isAttached ? 'Added' : 'Add'}
                    </Button>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </Modal>
  )
}

export default DashboardReportPickerModal
