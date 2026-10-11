import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  BarChart3,
  Database,
  FileText,
  GripVertical,
  Layers3,
  Loader2,
  Maximize2,
  Table,
  TrendingUp,
} from 'lucide-react'
import { toast } from 'react-hot-toast'

import { voiceReportsAPI } from '../../../api/endpoints'
import { withNightEmbedAppearance } from '../../../utils/embedAppearance'
import {
  formatReportStatus,
  getReportStatusBadgeClass,
  isReportCompleted,
  isReportProcessing,
} from '../../../utils/reportStatus'

const CHART_TYPE_META = {
  line: { label: 'Line', Icon: TrendingUp },
  line_multi: { label: 'Multi Line', Icon: Layers3 },
  bar: { label: 'Bar', Icon: BarChart3 },
  bar_grouped: { label: 'Grouped Bar', Icon: Layers3 },
  bar_stacked: { label: 'Stacked Bar', Icon: Layers3 },
  pie: { label: 'Pie', Icon: BarChart3 },
  area: { label: 'Area', Icon: TrendingUp },
  scatter: { label: 'Scatter', Icon: BarChart3 },
  histogram: { label: 'Histogram', Icon: BarChart3 },
  map: { label: 'Map', Icon: Database },
  heatmap: { label: 'Heatmap', Icon: Table },
  combo_line_bar: { label: 'Combo', Icon: Layers3 },
  cumulative_line: { label: 'Cumulative', Icon: TrendingUp },
  card: { label: 'Card', Icon: FileText },
  table: { label: 'Table', Icon: Table },
}

const ARABIC_INDIC_DIGITS = '٠١٢٣٤٥٦٧٨٩'
const EASTERN_ARABIC_INDIC_DIGITS = '۰۱۲۳۴۵۶۷۸۹'

const normalizeLocalizedDigits = (value = '') =>
  String(value)
    .replace(/[٠-٩]/g, (digit) => String(ARABIC_INDIC_DIGITS.indexOf(digit)))
    .replace(/[۰-۹]/g, (digit) => String(EASTERN_ARABIC_INDIC_DIGITS.indexOf(digit)))

const sanitizeDimensionInput = (value = '') =>
  normalizeLocalizedDigits(value).replace(/[^\d]/g, '').slice(0, 3)

const parseDimensionInput = (value = '') => {
  const sanitized = sanitizeDimensionInput(value)
  if (!sanitized) return null
  const parsed = Number.parseInt(sanitized, 10)
  return Number.isFinite(parsed) ? parsed : null
}

const getChartTypeMeta = (chartType, fallbackLabel = '') => {
  const key = String(chartType || '').trim().toLowerCase()
  if (CHART_TYPE_META[key]) return CHART_TYPE_META[key]
  return {
    label: String(fallbackLabel || chartType || 'Chart').trim(),
    Icon: BarChart3,
  }
}

function DashboardWidgetCard({
  widget,
  pages,
  currentPageId,
  canManageWidgets,
  canSwitchCharts,
  isMoving,
  onOpenReport,
  onMoveWidget,
  onResizeWidget,
  onEmbedError,
  onChartTypeChanged,
}) {
  const reportId = Number(widget?.report_id || 0)
  const embedUrl = withNightEmbedAppearance(widget?.report_embed_url)
  const reportStatus = String(widget?.report_status || '').trim()
  const chartType = String(widget?.report_chart_type || '').trim()
  const renderVersion = Number(widget?.report_render_version || 0)
  const reportTitle = String(widget?.report_title || '').trim() || `Report #${reportId}`
  const widgetWidth = Number(widget?.width || 1)
  const widgetHeight = Number(widget?.height || 1)

  const hasMultiplePages = Array.isArray(pages) && pages.length > 1
  const frameRef = useRef(null)
  const chartPickerRef = useRef(null)
  const [shouldLoadEmbed, setShouldLoadEmbed] = useState(false)
  const [hasEmbedError, setHasEmbedError] = useState(false)
  const [retryRequested, setRetryRequested] = useState(false)
  const [isChartPickerOpen, setIsChartPickerOpen] = useState(false)
  const [chartTypeOptions, setChartTypeOptions] = useState([])
  const [isChartTypeOptionsLoading, setIsChartTypeOptionsLoading] = useState(false)
  const [switchingChartType, setSwitchingChartType] = useState('')
  const [chartTypePickerError, setChartTypePickerError] = useState('')
  const [sizeWidthInput, setSizeWidthInput] = useState(String(Math.max(1, widgetWidth)))
  const [sizeHeightInput, setSizeHeightInput] = useState(String(Math.max(1, widgetHeight)))
  const [isApplyingExactSize, setIsApplyingExactSize] = useState(false)
  const [sizeEditorError, setSizeEditorError] = useState('')
  const canManualSwitch = Boolean(canSwitchCharts) && reportId > 0

  useEffect(() => {
    setHasEmbedError(false)
    setRetryRequested(false)
    setShouldLoadEmbed(false)
    setIsChartPickerOpen(false)
    setChartTypeOptions([])
    setIsChartTypeOptionsLoading(false)
    setSwitchingChartType('')
    setChartTypePickerError('')
  }, [embedUrl, reportId])

  useEffect(() => {
    setSizeWidthInput(String(Math.max(1, Number(widgetWidth || 1))))
    setSizeHeightInput(String(Math.max(1, Number(widgetHeight || 1))))
    setSizeEditorError('')
    setIsApplyingExactSize(false)
  }, [widgetHeight, widgetWidth])

  useEffect(() => {
    if (!embedUrl || shouldLoadEmbed) return
    if (typeof window === 'undefined' || !('IntersectionObserver' in window)) {
      setShouldLoadEmbed(true)
      return
    }

    const observer = new window.IntersectionObserver(
      (entries) => {
        const [entry] = entries
        if (entry?.isIntersecting) {
          setShouldLoadEmbed(true)
          observer.disconnect()
        }
      },
      {
        root: null,
        rootMargin: '360px',
        threshold: 0.01,
      }
    )

    if (frameRef.current) {
      observer.observe(frameRef.current)
    } else {
      setShouldLoadEmbed(true)
    }

    return () => observer.disconnect()
  }, [embedUrl, shouldLoadEmbed])

  useEffect(() => {
    if (!isChartPickerOpen) return undefined
    const handlePointerDown = (event) => {
      const target = event.target
      if (chartPickerRef.current && target instanceof Node && !chartPickerRef.current.contains(target)) {
        setIsChartPickerOpen(false)
      }
    }
    document.addEventListener('mousedown', handlePointerDown)
    return () => document.removeEventListener('mousedown', handlePointerDown)
  }, [isChartPickerOpen])

  useEffect(() => {
    if (!chartTypeOptions.length) return
    const normalizedCurrentType = String(chartType || '').trim().toLowerCase()
    setChartTypeOptions((previous) =>
      previous.map((option) => ({
        ...option,
        selected: String(option?.type || '').trim().toLowerCase() === normalizedCurrentType,
      }))
    )
  }, [chartType, chartTypeOptions.length])

  const chartTypeGroups = useMemo(() => {
    if (!Array.isArray(chartTypeOptions)) return []
    return chartTypeOptions.map((option) => {
      const type = String(option?.type || '').trim().toLowerCase()
      const fallbackLabel = String(option?.label || '').trim()
      const { label, Icon } = getChartTypeMeta(type, fallbackLabel)
      return {
        ...option,
        type,
        label,
        Icon,
      }
    })
  }, [chartTypeOptions])

  const loadChartTypeOptions = useCallback(async ({ force = false } = {}) => {
    if (!canManualSwitch || isChartTypeOptionsLoading) return
    if (chartTypeOptions.length > 0 && !force) return

    setIsChartTypeOptionsLoading(true)
    setChartTypePickerError('')
    try {
      const response = await voiceReportsAPI.getReportChartTypeCapabilities(reportId)
      const options = Array.isArray(response?.data?.chart_types) ? response.data.chart_types : []
      setChartTypeOptions(options)
    } catch (error) {
      const message =
        String(error?.response?.data?.error || '').trim() ||
        'Failed to load chart options.'
      setChartTypePickerError(message)
    } finally {
      setIsChartTypeOptionsLoading(false)
    }
  }, [canManualSwitch, chartTypeOptions.length, isChartTypeOptionsLoading, reportId])

  const handleToggleChartTypePicker = useCallback(async (event) => {
    event.stopPropagation()
    if (!canManualSwitch) return
    const nextOpen = !isChartPickerOpen
    setIsChartPickerOpen(nextOpen)
    if (nextOpen && chartTypeOptions.length === 0) {
      await loadChartTypeOptions()
    }
  }, [canManualSwitch, chartTypeOptions.length, isChartPickerOpen, loadChartTypeOptions])

  const handleSwitchChartType = useCallback(async (targetOption) => {
    if (!canManualSwitch) return
    const targetType = String(targetOption?.type || '').trim().toLowerCase()
    if (!targetType) return
    if (switchingChartType) return

    if (!targetOption?.supported) {
      const unsupportedMessage =
        String(targetOption?.unsupported_reason || '').trim() ||
        'This chart type is not supported for the current data.'
      setChartTypePickerError(unsupportedMessage)
      return
    }

    setChartTypePickerError('')
    setSwitchingChartType(targetType)
    try {
      const response = await voiceReportsAPI.switchReportChartType(reportId, targetType)
      const payload = response?.data || {}
      const nextChartType = String(payload?.chart_type || targetType).trim().toLowerCase()
      const nextEmbedUrl = String(payload?.embed_url || embedUrl || '').trim()

      setChartTypeOptions((previous) =>
        previous.map((option) => ({
          ...option,
          selected: String(option?.type || '').trim().toLowerCase() === nextChartType,
        }))
      )
      if (typeof onChartTypeChanged === 'function') {
        onChartTypeChanged(reportId, {
          chart_type: nextChartType,
          embed_url: nextEmbedUrl,
        })
      }
      setIsChartPickerOpen(false)
      toast.success('Chart type updated.')
    } catch (error) {
      const unsupportedReason = String(error?.response?.data?.unsupported_reason || '').trim()
      const message =
        unsupportedReason ||
        String(error?.response?.data?.details || error?.response?.data?.error || '').trim() ||
        'Failed to switch chart type.'
      setChartTypePickerError(message)
      toast.error(message)
    } finally {
      setSwitchingChartType('')
    }
  }, [canManualSwitch, embedUrl, onChartTypeChanged, reportId, switchingChartType])

  const handleApplyExactSize = useCallback(async () => {
    if (!canManageWidgets || typeof onResizeWidget !== 'function') return
    const requestedWidth = parseDimensionInput(sizeWidthInput)
    const requestedHeight = parseDimensionInput(sizeHeightInput)

    if (requestedWidth === null || requestedHeight === null) {
      setSizeEditorError('Please enter valid numeric width and height.')
      return
    }

    const nextWidth = Math.max(1, Math.min(48, Math.trunc(requestedWidth)))
    const nextHeight = Math.max(1, Math.min(48, Math.trunc(requestedHeight)))
    setSizeEditorError('')
    setIsApplyingExactSize(true)

    try {
      const result = await onResizeWidget(widget, { width: nextWidth, height: nextHeight })
      if (!result?.success) {
        const message = String(result?.message || 'Failed to update widget size.')
        setSizeEditorError(message)
        toast.error(message)
        return
      }
      setSizeWidthInput(String(nextWidth))
      setSizeHeightInput(String(nextHeight))
      toast.success('Widget size updated.')
    } finally {
      setIsApplyingExactSize(false)
    }
  }, [canManageWidgets, onResizeWidget, sizeHeightInput, sizeWidthInput, widget])

  return (
    <div className="h-full border border-brand-700/30 rounded-lg bg-[var(--c-card-bg)] overflow-hidden shadow-sm flex flex-col">
      <div className="px-3 py-2 border-b bg-[rgba(255,255,255,0.04)] flex items-center justify-between gap-2">
        <div className="min-w-0 flex items-center gap-2">
          {canManageWidgets ? (
            <span className="dashboard-widget-drag-handle text-brand-300/60 cursor-move hover:text-[var(--c-muted)]" title="Drag widget">
              <GripVertical className="w-4 h-4" />
            </span>
          ) : null}
          <div className="min-w-0">
            <p className="text-sm font-medium text-white truncate">{reportTitle}</p>
            {chartType ? (
              canManualSwitch ? (
                <button
                  type="button"
                  onClick={handleToggleChartTypePicker}
                  className="text-xs text-brand-300/80 truncate hover:text-brand-300"
                  title="Change chart type"
                >
                  {chartType} chart
                </button>
              ) : (
                <p className="text-xs text-brand-300/80 truncate">{chartType} chart</p>
              )
            ) : null}
          </div>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <span className={`px-2 py-1 rounded-full text-[11px] font-medium ${getReportStatusBadgeClass(reportStatus)}`}>
            {formatReportStatus(reportStatus || 'unknown')}
          </span>
          {canManualSwitch ? (
            <button
              type="button"
              onClick={handleToggleChartTypePicker}
              className="h-7 w-7 rounded-full border border-brand-700/30 bg-[var(--c-card-bg)] text-[var(--c-muted)] hover:text-brand-300 hover:border-brand-700/40 inline-flex items-center justify-center"
              title="Change chart type"
              aria-label="Change chart type"
            >
              <BarChart3 className="w-3.5 h-3.5" />
            </button>
          ) : null}
          {reportId ? (
            <button
              type="button"
              onClick={() => onOpenReport(reportId)}
              className="text-xs font-medium text-brand-500 hover:text-brand-300"
            >
              Open
            </button>
          ) : null}
        </div>
      </div>

      {canManageWidgets && hasMultiplePages ? (
        <div className="px-3 py-2 border-b bg-[var(--c-card-bg)] flex items-center gap-2">
          <label className="text-xs text-brand-300/80 uppercase tracking-[0.1em]">Move To</label>
          <select
            value={String(currentPageId)}
            onChange={(event) => onMoveWidget(widget, Number(event.target.value))}
            disabled={isMoving}
            className="text-xs border border-brand-700/30 rounded-md px-2 py-1 bg-[var(--c-card-bg)] text-brand-300 disabled:opacity-60"
          >
            {pages.map((page) => (
              <option key={page.id} value={String(page.id)}>
                {page.name}
              </option>
            ))}
          </select>
        </div>
      ) : null}

      {canManageWidgets ? (
        <div className="px-3 py-2 border-b bg-[var(--c-card-bg)]">
          <div className="flex flex-wrap items-end gap-2">
            <div>
              <label className="block text-[10px] uppercase tracking-[0.1em] text-brand-300/80 mb-1">W</label>
              <input
                type="text"
                inputMode="numeric"
                pattern="[0-9]*"
                dir="ltr"
                value={sizeWidthInput}
                onChange={(event) => {
                  setSizeWidthInput(sanitizeDimensionInput(event.target.value))
                }}
                onBlur={() => {
                  const parsed = parseDimensionInput(sizeWidthInput)
                  const nextValue = parsed === null ? Math.max(1, widgetWidth) : Math.max(1, Math.min(48, parsed))
                  setSizeWidthInput(String(nextValue))
                }}
                className="w-20 text-xs border border-brand-700/30 rounded-md px-2 py-1 bg-[var(--c-card-bg)] text-brand-300"
              />
            </div>
            <div>
              <label className="block text-[10px] uppercase tracking-[0.1em] text-brand-300/80 mb-1">H</label>
              <input
                type="text"
                inputMode="numeric"
                pattern="[0-9]*"
                dir="ltr"
                value={sizeHeightInput}
                onChange={(event) => {
                  setSizeHeightInput(sanitizeDimensionInput(event.target.value))
                }}
                onBlur={() => {
                  const parsed = parseDimensionInput(sizeHeightInput)
                  const nextValue = parsed === null ? Math.max(1, widgetHeight) : Math.max(1, Math.min(48, parsed))
                  setSizeHeightInput(String(nextValue))
                }}
                className="w-20 text-xs border border-brand-700/30 rounded-md px-2 py-1 bg-[var(--c-card-bg)] text-brand-300"
              />
            </div>
            <button
              type="button"
              onClick={handleApplyExactSize}
              disabled={isApplyingExactSize}
              className="h-7 px-2 rounded-md border border-brand-700/30 bg-[var(--c-card-bg)] text-xs text-brand-300 hover:border-brand-400/60 hover:text-brand-300 disabled:opacity-60 inline-flex items-center gap-1"
              title="Apply exact width and height"
            >
              {isApplyingExactSize ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Maximize2 className="w-3.5 h-3.5" />}
              <span>Apply</span>
            </button>
          </div>
          {sizeEditorError ? (
            <p className="mt-1 text-[11px] text-red-600">{sizeEditorError}</p>
          ) : null}
        </div>
      ) : null}

      <div className="flex-1 min-h-0 bg-[var(--c-report-bg)] relative" ref={frameRef}>
        {canManualSwitch && isChartPickerOpen ? (
          <div
            ref={chartPickerRef}
            className="absolute right-3 top-3 z-30 w-[22rem] max-w-[calc(100%-1.5rem)] rounded-xl border border-brand-700/30 bg-[var(--c-card-bg)] shadow-2xl p-3"
          >
            {isChartTypeOptionsLoading ? (
              <div className="py-8 text-center text-brand-300/80 text-sm">
                <Loader2 className="w-5 h-5 animate-spin mx-auto mb-2" />
                Loading chart types...
              </div>
            ) : (
              <>
                <div className="grid grid-cols-4 gap-2">
                  {chartTypeGroups.map((option) => {
                    const isSelected = Boolean(option?.selected)
                    const isSupported = Boolean(option?.supported)
                    const isSwitching = switchingChartType === option.type
                    const buttonTitle = isSupported
                      ? option.label
                      : String(option?.unsupported_reason || 'Not supported for this data')
                    return (
                      <button
                        key={option.type}
                        type="button"
                        onClick={() => handleSwitchChartType(option)}
                        disabled={isSwitching}
                        title={buttonTitle}
                        className={[
                          'group rounded-lg border px-2 py-2 text-center transition-colors',
                          isSelected ? 'border-brand-400 bg-brand-900/30' : 'border-brand-700/30 bg-[var(--c-card-bg)]',
                          isSupported ? 'hover:border-brand-400/60' : 'opacity-50',
                          isSwitching ? 'cursor-wait' : '',
                        ].join(' ')}
                      >
                        <span className="mx-auto mb-1 inline-flex h-8 w-8 items-center justify-center rounded-md bg-[rgba(255,255,255,0.07)] text-brand-300 group-hover:bg-brand-700/30">
                          {isSwitching ? (
                            <Loader2 className="w-4 h-4 animate-spin" />
                          ) : (
                            <option.Icon className="w-4 h-4" />
                          )}
                        </span>
                        <span className="block text-[11px] leading-tight text-brand-300 truncate">
                          {option.label}
                        </span>
                      </button>
                    )
                  })}
                </div>

                {chartTypePickerError ? (
                  <p className="mt-2 text-xs text-red-600">{chartTypePickerError}</p>
                ) : null}
              </>
            )}
          </div>
        ) : null}

        {embedUrl && shouldLoadEmbed && !hasEmbedError ? (
          <iframe
            key={`${reportId}-${embedUrl}-${renderVersion}`}
            src={embedUrl}
            width="100%"
            height="100%"
            frameBorder="0"
            className="bg-[var(--c-report-bg)] w-full h-full"
            title={`Dashboard widget report ${reportId}`}
            loading="lazy"
            onError={() => {
              setHasEmbedError(true)
              if (!retryRequested && typeof onEmbedError === 'function' && reportId > 0) {
                setRetryRequested(true)
                onEmbedError(reportId)
              }
            }}
          />
        ) : embedUrl && !shouldLoadEmbed ? (
          <div className="h-full flex flex-col items-center justify-center text-brand-300/80 px-4 text-center">
            <Loader2 className="w-5 h-5 animate-spin mb-2 text-brand-300/60" />
            <p className="text-sm">Scroll to load visualization...</p>
          </div>
        ) : embedUrl && hasEmbedError ? (
          <div className="h-full flex flex-col items-center justify-center text-amber-400 px-4 text-center">
            <BarChart3 className="w-6 h-6 mb-2 text-amber-500" />
            <p className="text-sm font-medium">Could not load visualization.</p>
            <p className="text-xs mt-1 text-amber-400">Refreshing embed token...</p>
          </div>
        ) : isReportProcessing(reportStatus) || isReportCompleted(reportStatus) ? (
          <div className="h-full flex flex-col items-center justify-center text-brand-300/80">
            <Loader2 className="w-5 h-5 animate-spin mb-2" />
            <p className="text-sm">Visualization is loading...</p>
          </div>
        ) : (
          <div className="h-full flex flex-col items-center justify-center text-brand-300/80 px-4 text-center">
            <BarChart3 className="w-6 h-6 mb-2 text-brand-300/60" />
            <p className="text-sm">No visualization available yet.</p>
          </div>
        )}
      </div>
    </div>
  )
}

export default memo(DashboardWidgetCard)
