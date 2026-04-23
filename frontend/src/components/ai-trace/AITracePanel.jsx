import { useMemo, useState } from 'react'
import { ChevronDown, ChevronUp, Play, RotateCcw, Save } from 'lucide-react'

const statusClasses = {
  success: 'bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-200',
  degraded: 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200',
  warning: 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200',
  error: 'bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-200',
  skipped: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200',
}

function StageBadge({ status }) {
  const normalized = String(status || 'skipped').toLowerCase()
  return (
    <span className={`rounded-full px-2 py-1 text-xs font-semibold ${statusClasses[normalized] || statusClasses.skipped}`}>
      {normalized}
    </span>
  )
}

function StagePanel({ title, status, defaultOpen = false, children }) {
  const [isOpen, setIsOpen] = useState(defaultOpen)
  return (
    <div className="rounded-lg border border-slate-200 dark:border-slate-700">
      <button
        type="button"
        className="flex w-full items-center justify-between px-4 py-3 text-left"
        onClick={() => setIsOpen((prev) => !prev)}
      >
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">{title}</span>
          <StageBadge status={status} />
        </div>
        {isOpen ? <ChevronUp className="h-4 w-4 text-slate-500" /> : <ChevronDown className="h-4 w-4 text-slate-500" />}
      </button>
      {isOpen && <div className="border-t border-slate-200 p-4 dark:border-slate-700">{children}</div>}
    </div>
  )
}

function KeyValueGrid({ items }) {
  return (
    <div className="grid gap-3 md:grid-cols-2">
      {items.map((item) => (
        <div key={item.label} className="rounded-md bg-slate-50 p-3 dark:bg-slate-900/30">
          <p className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">{item.label}</p>
          <p className="mt-1 break-words text-sm text-slate-800 dark:text-slate-100">{item.value ?? '-'}</p>
        </div>
      ))}
    </div>
  )
}

function JsonBlock({ value }) {
  return (
    <pre className="overflow-x-auto rounded-md bg-slate-900 p-3 text-xs text-slate-100">
      {JSON.stringify(value ?? {}, null, 2)}
    </pre>
  )
}

function DataTable({ columns = [], rows = [] }) {
  if (!columns.length || !rows.length) {
    return <p className="text-sm text-slate-500 dark:text-slate-400">No sample rows available.</p>
  }

  return (
    <div className="overflow-x-auto rounded-md border border-slate-200 dark:border-slate-700">
      <table className="min-w-full divide-y divide-slate-200 text-sm dark:divide-slate-700">
        <thead className="bg-slate-50 dark:bg-slate-900/30">
          <tr>
            {columns.map((column) => (
              <th key={column} className="px-3 py-2 text-left font-semibold text-slate-700 dark:text-slate-200">
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-200 dark:divide-slate-700">
          {rows.map((row, index) => (
            <tr key={index}>
              {columns.map((column) => (
                <td key={`${index}-${column}`} className="px-3 py-2 text-slate-700 dark:text-slate-200">
                  {String(row?.[column] ?? '-')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ForecastPreview({ historical = [], forecast = [] }) {
  const points = useMemo(() => {
    const all = [...historical, ...forecast]
      .map((item) => Number(item?.value))
      .filter((value) => Number.isFinite(value))
    if (!all.length) {
      return null
    }
    const min = Math.min(...all)
    const max = Math.max(...all)
    const normalize = (value) => {
      if (max === min) return 50
      return 90 - ((value - min) / (max - min)) * 80
    }

    const buildPath = (series, xStart, xStep) =>
      series
        .map((item, index) => {
          const x = xStart + index * xStep
          const y = normalize(Number(item?.value) || 0)
          return `${index === 0 ? 'M' : 'L'} ${x} ${y}`
        })
        .join(' ')

    return {
      historicalPath: buildPath(historical, 5, historical.length > 1 ? 70 / (historical.length - 1) : 0),
      forecastPath: buildPath(forecast, 75, forecast.length > 1 ? 20 / (forecast.length - 1) : 0),
    }
  }, [historical, forecast])

  if (!points) {
    return <p className="text-sm text-slate-500 dark:text-slate-400">No forecast preview available.</p>
  }

  return (
    <svg viewBox="0 0 100 100" className="h-32 w-full rounded-md border border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-900/30">
      <path d="M 75 5 L 75 95" stroke="#cbd5e1" strokeDasharray="2 2" fill="none" />
      <path d={points.historicalPath} stroke="#0ea5e9" strokeWidth="2" fill="none" />
      <path d={points.forecastPath} stroke="#f97316" strokeWidth="2" fill="none" />
    </svg>
  )
}

function _yesNo(value) {
  return value ? 'YES' : 'NO'
}

function _formatPreprocessingChanges(changes) {
  const list = Array.isArray(changes) ? changes : []
  return list
    .map((change) => {
      if (!change || typeof change !== 'object') return ''
      const from = String(change.original || change.from || '').trim()
      const to = String(change.cleaned || change.to || '').trim()
      if (from && to && from !== to) return `${from} -> ${to}`
      const message = String(change.description || change.message || change.type || '').trim()
      return message
    })
    .filter(Boolean)
}

function _extractCorrections(preHigh) {
  const direct = Array.isArray(preHigh?.corrections) ? preHigh.corrections : []
  if (direct.length) {
    return direct
      .map((item) => {
        const source = String(item?.from || '').trim()
        const target = String(item?.to || '').trim()
        if (!source || !target || source === target) return ''
        return `${source} -> ${target}`
      })
      .filter(Boolean)
  }

  const termCorrections = Array.isArray(preHigh?.term_corrections) ? preHigh.term_corrections : []
  const compact = termCorrections
    .map((item) => {
      const source = String(item?.from || item?.source || '').trim()
      const target = String(item?.to || item?.target || '').trim()
      if (!source || !target || source === target) return ''
      return `${source} -> ${target}`
    })
    .filter(Boolean)
  return Array.from(new Set(compact))
}

function _humanIntent(intent) {
  const payload = intent?.validated_intent && Object.keys(intent.validated_intent).length
    ? intent.validated_intent
    : (intent?.extracted_intent || {})
  const operations = Array.isArray(payload?.operations) ? payload.operations : []
  const dimensions = Array.isArray(payload?.dimensions) ? payload.dimensions : []
  const metrics = Array.isArray(payload?.metrics) ? payload.metrics : []
  const directColumns = Array.isArray(payload?.columns) ? payload.columns : []
  const columns = Array.from(
    new Set([
      ...directColumns.map(String),
      ...dimensions.map(String),
      ...metrics.map(String),
      String(payload?.target_column || '').trim(),
    ].filter(Boolean))
  )
  const intentType = String(intent?.intent_type || payload?.intent || payload?.analysis_mode || '').trim()
  const operationText = operations.length ? operations.map((item) => String(item)).join(', ') : 'Compare relationship between variables'
  const timeRange = String(payload?.time_range || payload?.period || payload?.date_range || 'All time').trim() || 'All time'

  return {
    intentType: intentType || 'Analytical',
    columns,
    operationText,
    timeRange,
    ambiguities: Array.isArray(intent?.ambiguities) ? intent.ambiguities : [],
  }
}

function AITracePanel({
  trace,
  editableQuestion = '',
  onQuestionChange,
  onRerunQuestion,
  isRerunningQuestion = false,
  editableSQL,
  onSQLChange,
  onRunQuery,
  onSaveQuery,
  isSavingSQL = false,
  isRunningQuery = false,
  hasSQLChanges = false,
}) {
  if (!trace) {
    return null
  }

  const preLow = trace.preprocessing_low || {}
  const preHigh = trace.preprocessing_high || {}
  const classification = trace.classification || {}
  const intent = trace.intent_extraction || trace.intent || {}
  const sql = trace.sql || {}
  const execution = trace.execution || {}
  const routing = trace.routing || {}
  const forecasting = trace.forecasting || null
  const shouldShowForecasting = Boolean(
    classification.question_type === 'predictive' ||
    classification.requires_forecast === true ||
    routing.route === 'forecasting' ||
    routing.next_step === 'forecasting' ||
    forecasting?.requires_forecast === true
  )
  const visualization = trace.visualization || {}
  const errors = Array.isArray(trace.errors) ? trace.errors : []
  const lowChanges = _formatPreprocessingChanges(preLow.detected_changes)
  const highCorrections = _extractCorrections(preHigh)
  const intentView = _humanIntent(intent)
  const classificationError = Boolean(classification.error)
  const currentQuestion = typeof editableQuestion === 'string'
    ? editableQuestion
    : String(trace.original_question?.text || '')
  const questionEditable = typeof onQuestionChange === 'function'
  const questionRerunnable = typeof onRerunQuestion === 'function'
  const currentSQL = typeof editableSQL === 'string' ? editableSQL : (sql.reviewed_sql || sql.generated_sql || '')
  const sqlEditable = typeof onSQLChange === 'function'

  return (
    <div className="space-y-3">
      <h3 className="text-lg font-semibold text-slate-900 dark:text-slate-100">AI Trace</h3>

      <StagePanel title="1. Original Question" status={trace.original_question?.status || 'success'} defaultOpen>
        <textarea
          value={currentQuestion}
          onChange={(event) => onQuestionChange?.(event.target.value)}
          readOnly={!questionEditable}
          className="h-24 w-full rounded-md border border-slate-300 bg-white p-3 text-sm text-slate-800 dark:border-slate-700 dark:bg-slate-900/40 dark:text-slate-100"
          spellCheck={false}
        />
        <div className="mt-3 flex justify-end">
          <button
            type="button"
            onClick={() => onRerunQuestion?.()}
            disabled={!questionRerunnable || !currentQuestion.trim() || isRerunningQuestion}
            className="inline-flex items-center gap-1 rounded-md bg-indigo-600 px-3 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50"
          >
            <RotateCcw className={`h-4 w-4 ${isRerunningQuestion ? 'animate-spin' : ''}`} />
            Re-run
          </button>
        </div>
      </StagePanel>

      <StagePanel title="2. Preprocessing Low" status={preLow.status || 'skipped'}>
        <KeyValueGrid
          items={[
            { label: 'Original Sentence', value: preLow.original_text || '-' },
            { label: 'Cleaned Sentence', value: preLow.cleaned_text || '-' },
          ]}
        />
        <div className="mt-3">
          <p className="mb-2 text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">Changes</p>
          {lowChanges.length ? (
            <ul className="space-y-1 text-sm text-slate-700 dark:text-slate-200">
              {lowChanges.map((item, index) => <li key={`${item}-${index}`}>- {item}</li>)}
            </ul>
          ) : (
            <p className="text-sm text-slate-500 dark:text-slate-400">No significant changes.</p>
          )}
        </div>
      </StagePanel>

      <StagePanel title="3. Classification" status={classification.status || 'skipped'}>
        <KeyValueGrid
          items={[
            { label: 'Analytical?', value: _yesNo(Boolean(classification.is_analytical)) },
            { label: 'Predictive?', value: _yesNo(Boolean(classification.is_predictive || classification.question_type === 'predictive')) },
            { label: 'Error?', value: _yesNo(classificationError) },
            { label: 'confidence', value: classification.confidence ?? '-' },
            { label: 'reasoning', value: classification.reasoning || classification.error_reason || '-' },
          ]}
        />
      </StagePanel>

      <StagePanel title="4. Preprocessing High" status={preHigh.status || 'skipped'}>
        <KeyValueGrid
          items={[
            { label: 'Selected Table', value: preHigh.selected_table || '-' },
            {
              label: 'Selected Columns',
              value: Array.isArray(preHigh.selected_columns) && preHigh.selected_columns.length
                ? preHigh.selected_columns.join(', ')
                : '-',
            },
          ]}
        />
        <div className="mt-3">
          <p className="mb-2 text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">Corrections</p>
          {highCorrections.length ? (
            <ul className="space-y-1 text-sm text-slate-700 dark:text-slate-200">
              {highCorrections.map((item, index) => <li key={`${item}-${index}`}>- {item}</li>)}
            </ul>
          ) : (
            <p className="text-sm text-slate-500 dark:text-slate-400">No corrections applied.</p>
          )}
        </div>
        {Array.isArray(preHigh.user_friendly_messages) && preHigh.user_friendly_messages.length > 0 && (
          <div className="mt-3 rounded-md bg-amber-50 p-3 text-sm text-amber-800 dark:bg-amber-900/20 dark:text-amber-200">
            {preHigh.user_friendly_messages.map((message, index) => (
              <p key={`${message}-${index}`}>- {String(message)}</p>
            ))}
          </div>
        )}
      </StagePanel>

      <StagePanel title="5. Intent Extraction" status={intent.status || 'skipped'}>
        <div className="space-y-2 text-sm text-slate-700 dark:text-slate-200">
          <p><span className="font-semibold">Intent:</span> {intentView.intentType}</p>
          <div>
            <p className="font-semibold">Columns:</p>
            {intentView.columns.length ? (
              <ul className="mt-1 space-y-1">
                {intentView.columns.map((column, index) => <li key={`${column}-${index}`}>- {column}</li>)}
              </ul>
            ) : (
              <p className="text-slate-500 dark:text-slate-400">- None inferred</p>
            )}
          </div>
          <p><span className="font-semibold">Operation:</span> {intentView.operationText}</p>
          <p><span className="font-semibold">Time Range:</span> {intentView.timeRange}</p>
        </div>
      </StagePanel>

      <StagePanel title="6. SQL Generation" status={sql.status || 'skipped'}>
        <textarea
          value={currentSQL}
          onChange={(event) => onSQLChange?.(event.target.value)}
          readOnly={!sqlEditable}
          className="h-56 w-full rounded-md bg-slate-900 p-3 font-mono text-xs text-green-300"
          spellCheck={false}
        />
        <div className="mt-3 flex gap-2">
          <button
            type="button"
            onClick={() => onRunQuery?.()}
            disabled={!onRunQuery || isRunningQuery}
            className="inline-flex items-center gap-1 rounded-md bg-green-600 px-3 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Play className="h-4 w-4" />
            Run Query
          </button>
          <button
            type="button"
            onClick={() => onSaveQuery?.()}
            disabled={!onSaveQuery || isSavingSQL || !hasSQLChanges}
            className="inline-flex items-center gap-1 rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Save className="h-4 w-4" />
            Save Query
          </button>
        </div>
      </StagePanel>

      <StagePanel title="7. Execution" status={execution.status || 'skipped'}>
        <KeyValueGrid
          items={[
            { label: 'execution_time_ms', value: execution.execution_time_ms ?? '-' },
            { label: 'row_count', value: execution.row_count ?? 0 },
          ]}
        />
        <div className="mt-3">
          <DataTable columns={execution.columns || []} rows={execution.sample_rows || []} />
        </div>
      </StagePanel>

      {shouldShowForecasting && (
        <StagePanel title="Forecasting" status={forecasting?.forecast_status || 'skipped'}>
          <KeyValueGrid
            items={[
              { label: 'requires_forecast', value: String(forecasting?.requires_forecast ?? true) },
              { label: 'model_used', value: forecasting?.model_used || '-' },
              { label: 'detected_time_column', value: forecasting?.detected_time_column || '-' },
              { label: 'detected_value_column', value: forecasting?.detected_value_column || '-' },
              { label: 'horizon', value: forecasting?.horizon ?? '-' },
              { label: 'granularity', value: forecasting?.granularity || '-' },
              { label: 'fallback', value: forecasting?.fallback || '-' },
              { label: 'reason', value: forecasting?.reason || '-' },
            ]}
          />
          <div className="mt-3">
            <p className="mb-1 text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">Validation Notes</p>
            <JsonBlock value={forecasting?.validation_notes || []} />
          </div>
          <div className="mt-3">
            <p className="mb-1 text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">Actual vs Forecast Preview</p>
            <ForecastPreview
              historical={forecasting?.historical_series_sample || []}
              forecast={forecasting?.forecast_output_sample || []}
            />
          </div>
        </StagePanel>
      )}

      <StagePanel title="8. Visualization" status={visualization.status || 'skipped'}>
        <KeyValueGrid
          items={[
            { label: 'chart_type', value: visualization.chart_type || '-' },
            { label: 'metabase_question_id', value: visualization.metabase_question_id ?? '-' },
            { label: 'metabase_dashboard_id', value: visualization.metabase_dashboard_id ?? '-' },
          ]}
        />
      </StagePanel>

      <StagePanel title="Errors" status={errors.length ? 'error' : 'success'}>
        {errors.length ? <JsonBlock value={errors} /> : <p className="text-sm text-slate-600 dark:text-slate-300">No stage errors reported.</p>}
      </StagePanel>
    </div>
  )
}

export default AITracePanel
