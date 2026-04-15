import { useMemo, useState } from 'react'
import { ChevronDown, ChevronUp, Sparkles } from 'lucide-react'

import TextDiffViewer from './TextDiffViewer'
import TermCorrectionsList from './TermCorrectionsList'
import SchemaUsageViewer from './SchemaUsageViewer'

const lowChangeClassByType = {
  removed_noise: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-200',
  normalized: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/40 dark:text-yellow-200',
  reduced_repetition: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/40 dark:text-yellow-200',
}

const normalizeLow = (payload) => {
  const originalText = String(payload?.original_text || '')
  const cleanedText = String(payload?.cleaned_text || originalText)
  const changes = Array.isArray(payload?.changes) ? payload.changes : []
  return {
    original_text: originalText,
    cleaned_text: cleanedText,
    changes,
  }
}

const normalizeHigh = (payload) => {
  const selectedTable = String(payload?.selected_table || '').trim()
  const selectedColumns = Array.isArray(payload?.selected_columns)
    ? payload.selected_columns.filter((item) => String(item || '').trim())
    : []
  const rawSchemaUsed = payload?.schema_used || {}
  const tables = Array.isArray(rawSchemaUsed?.tables)
    ? rawSchemaUsed.tables.filter((item) => String(item || '').trim())
    : []
  const columns = Array.isArray(rawSchemaUsed?.columns)
    ? rawSchemaUsed.columns.filter((item) => String(item || '').trim())
    : []
  const normalizedTables = tables.length > 0 ? tables : (selectedTable ? [selectedTable] : [])
  const normalizedColumns = columns.length > 0
    ? columns
    : selectedColumns.map((column) => (selectedTable ? `${selectedTable}.${column}` : column))

  return {
    corrected_query: String(payload?.corrected_query || payload?.final_query || ''),
    term_corrections: Array.isArray(payload?.term_corrections) ? payload.term_corrections : [],
    schema_used: {
      tables: normalizedTables,
      columns: normalizedColumns,
    },
    schema_adjustments: Array.isArray(payload?.schema_adjustments) ? payload.schema_adjustments : [],
    selected_table: selectedTable,
    selected_columns: selectedColumns,
  }
}

function SectionToggle({ title, isOpen, onToggle }) {
  return (
    <button
      type="button"
      className="flex w-full items-center justify-between rounded-lg bg-slate-50 px-4 py-3 text-left hover:bg-slate-100 dark:bg-slate-900/30 dark:hover:bg-slate-900/50"
      onClick={onToggle}
    >
      <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">{title}</span>
      {isOpen ? (
        <ChevronUp className="h-4 w-4 text-slate-500" />
      ) : (
        <ChevronDown className="h-4 w-4 text-slate-500" />
      )}
    </button>
  )
}

function PreprocessingDetailsPanel({ preprocessingLow, preprocessingHigh }) {
  const [isPanelOpen, setIsPanelOpen] = useState(false)
  const [isLowOpen, setIsLowOpen] = useState(true)
  const [isHighOpen, setIsHighOpen] = useState(true)

  const normalizedLow = useMemo(() => normalizeLow(preprocessingLow), [preprocessingLow])
  const normalizedHigh = useMemo(() => normalizeHigh(preprocessingHigh), [preprocessingHigh])

  return (
    <div className="rounded-xl border border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-900/20">
      <button
        type="button"
        className="flex w-full items-center justify-between px-4 py-4 text-left"
        onClick={() => setIsPanelOpen((prev) => !prev)}
      >
        <div className="flex items-center gap-2">
          <Sparkles className="h-5 w-5 text-blue-600" />
          <span className="text-base font-semibold text-slate-900 dark:text-slate-100">
            Preprocessing Details
          </span>
        </div>
        {isPanelOpen ? (
          <ChevronUp className="h-5 w-5 text-slate-500" />
        ) : (
          <ChevronDown className="h-5 w-5 text-slate-500" />
        )}
      </button>

      {isPanelOpen && (
        <div className="space-y-4 border-t border-slate-200 px-4 py-4 dark:border-slate-700">
          <div className="space-y-3 rounded-lg border border-slate-200 p-3 dark:border-slate-700">
            <SectionToggle
              title="Preprocessing Low (Text Cleaning)"
              isOpen={isLowOpen}
              onToggle={() => setIsLowOpen((prev) => !prev)}
            />
            {isLowOpen && (
              <div className="space-y-4">
                <TextDiffViewer
                  originalText={normalizedLow.original_text}
                  cleanedText={normalizedLow.cleaned_text}
                />

                <div>
                  <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                    Detected Changes
                  </p>
                  {normalizedLow.changes.length > 0 ? (
                    <div className="space-y-2">
                      {normalizedLow.changes.map((change, index) => (
                        <div
                          key={`${change.type}-${index}`}
                          className="rounded-lg border border-slate-200 bg-white p-3 text-sm dark:border-slate-700 dark:bg-slate-900/40"
                        >
                          <span
                            className={`mb-2 inline-flex rounded-full px-2 py-1 text-xs font-medium ${
                              lowChangeClassByType[change.type] || lowChangeClassByType.normalized
                            }`}
                          >
                            {String(change.type || 'normalized').replace('_', ' ')}
                          </span>
                          <div className="grid gap-2 md:grid-cols-2">
                            <div>
                              <p className="text-xs font-semibold uppercase text-slate-500 dark:text-slate-400">
                                Before
                              </p>
                              <p className="text-slate-700 dark:text-slate-200">{change.before || '-'}</p>
                            </div>
                            <div>
                              <p className="text-xs font-semibold uppercase text-slate-500 dark:text-slate-400">
                                After
                              </p>
                              <p className="text-slate-700 dark:text-slate-200">{change.after || '-'}</p>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-sm text-slate-500 dark:text-slate-400">No text cleaning changes detected.</p>
                  )}
                </div>
              </div>
            )}
          </div>

          <div className="space-y-3 rounded-lg border border-slate-200 p-3 dark:border-slate-700">
            <SectionToggle
              title="Preprocessing High (Schema-Aware Correction)"
              isOpen={isHighOpen}
              onToggle={() => setIsHighOpen((prev) => !prev)}
            />
            {isHighOpen && (
              <div className="space-y-4">
                <div>
                  <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                    Corrected Query
                  </p>
                  <div className="rounded-lg border border-green-200 bg-green-50 p-3 text-sm text-green-800 dark:border-green-900/40 dark:bg-green-900/20 dark:text-green-200">
                    {normalizedHigh.corrected_query || 'No corrected query available.'}
                  </div>
                </div>

                <div>
                  <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                    Term Corrections
                  </p>
                  <TermCorrectionsList corrections={normalizedHigh.term_corrections} />
                </div>

                <SchemaUsageViewer
                  schemaUsed={normalizedHigh.schema_used}
                  adjustments={normalizedHigh.schema_adjustments}
                  selectedTable={normalizedHigh.selected_table}
                  selectedColumns={normalizedHigh.selected_columns}
                />
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

export default PreprocessingDetailsPanel
