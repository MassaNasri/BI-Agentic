import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { BarChart3, Loader2, PlusCircle, RefreshCw, AlertCircle, FileText, X } from 'lucide-react'
import { toast } from 'react-hot-toast'
import { useContainerWidth } from 'react-grid-layout'
import ReactGridLayout from 'react-grid-layout/legacy'
import 'react-grid-layout/css/styles.css'
import 'react-resizable/css/styles.css'

import { voiceReportsAPI } from '../../api/endpoints'
import { useAuthStore } from '../../store/auth'
import { AnimatedPage, Button, Card } from '../../components'
import DashboardWidgetCard from './components/DashboardWidgetCard'
import DashboardReportPickerModal from './components/DashboardReportPickerModal'
import {
  BASE_GRID_COLUMNS,
  GRID_MAX_COLUMNS,
  clampLayoutX,
  computeLayoutUpdates,
  getMaxOccupiedColumns,
  resolveEffectiveGridColumns,
} from './dashboardGridLayout'

const GRID_COLUMNS = GRID_MAX_COLUMNS
const GRID_ROW_HEIGHT = 72
const WIDGET_DIMENSION_MAX = 48
const MIN_WIDGET_WIDTH = 1
const MAX_WIDGET_WIDTH = Math.min(GRID_COLUMNS, WIDGET_DIMENSION_MAX)
const MIN_WIDGET_HEIGHT = 1
const MAX_WIDGET_HEIGHT = WIDGET_DIMENSION_MAX
const DEFAULT_WIDGET_WIDTH = 6
const DEFAULT_WIDGET_HEIGHT = 3

const toInteger = (value, fallback = 0) => {
  const number = Number(value)
  if (!Number.isFinite(number)) return fallback
  return Math.trunc(number)
}

const toPositive = (value, fallback = 1) => {
  const number = toInteger(value, fallback)
  return Math.max(1, number)
}

const clamp = (value, min, max) => Math.max(min, Math.min(max, value))

const sortPages = (pages) =>
  [...pages].sort((a, b) => {
    const leftOrder = toInteger(a?.order, 0)
    const rightOrder = toInteger(b?.order, 0)
    if (leftOrder !== rightOrder) return leftOrder - rightOrder
    return toInteger(a?.id, 0) - toInteger(b?.id, 0)
  })

const sortWidgets = (widgets) =>
  [...widgets].sort((a, b) => {
    const leftOrder = toInteger(a?.order, 0)
    const rightOrder = toInteger(b?.order, 0)
    if (leftOrder !== rightOrder) return leftOrder - rightOrder
    return toInteger(a?.id, 0) - toInteger(b?.id, 0)
  })

const listToMap = (reports) =>
  reports.reduce((accumulator, report) => {
    const reportId = toInteger(report?.id, 0)
    if (reportId > 0) {
      accumulator.set(reportId, report)
    }
    return accumulator
  }, new Map())

const findPageByReportId = (pages, reportId) => {
  if (!reportId) return null
  for (const page of pages) {
    const widgets = Array.isArray(page?.widgets) ? page.widgets : []
    if (widgets.some((widget) => toInteger(widget?.report_id, 0) === reportId)) {
      return page
    }
  }
  return null
}

const normalizeWidgetLayout = (widget, maxColumns = GRID_COLUMNS) => {
  const widgetId = toInteger(widget?.id, 0)
  const normalizedMaxColumns = Math.max(BASE_GRID_COLUMNS, toInteger(maxColumns, GRID_COLUMNS))
  const width = clamp(
    toPositive(widget?.width, DEFAULT_WIDGET_WIDTH),
    MIN_WIDGET_WIDTH,
    Math.min(MAX_WIDGET_WIDTH, normalizedMaxColumns)
  )
  const x = clampLayoutX(widget?.x, width, normalizedMaxColumns)
  const height = clamp(toPositive(widget?.height, DEFAULT_WIDGET_HEIGHT), MIN_WIDGET_HEIGHT, MAX_WIDGET_HEIGHT)
  const y = Math.max(0, toInteger(widget?.y, 0))
  return {
    ...widget,
    id: widgetId,
    x,
    y,
    width,
    height,
  }
}

const buildLayout = (widgets, maxColumns = GRID_COLUMNS) =>
  sortWidgets(widgets).map((widget) => {
    const normalizedColumns = Math.max(BASE_GRID_COLUMNS, toInteger(maxColumns, GRID_COLUMNS))
    const normalized = normalizeWidgetLayout(widget, normalizedColumns)
    return {
      i: String(normalized.id),
      x: normalized.x,
      y: normalized.y,
      w: normalized.width,
      h: normalized.height,
      minW: MIN_WIDGET_WIDTH,
      maxW: Math.min(MAX_WIDGET_WIDTH, normalizedColumns),
      minH: MIN_WIDGET_HEIGHT,
      maxH: MAX_WIDGET_HEIGHT,
    }
  })

const getNextWidgetY = (widgets) =>
  widgets.reduce((maxY, widget) => {
    const y = Math.max(0, toInteger(widget?.y, 0))
    const height = clamp(toPositive(widget?.height, DEFAULT_WIDGET_HEIGHT), MIN_WIDGET_HEIGHT, MAX_WIDGET_HEIGHT)
    return Math.max(maxY, y + height)
  }, 0)

const cloneLayoutItems = (layout) =>
  Array.isArray(layout)
    ? layout.map((item) => ({
        ...item,
        i: String(item?.i || ''),
      }))
    : null

const resolveDashboardErrorMessage = (error, fallbackMessage) => {
  const rawMessage = String(error?.response?.data?.error || error?.message || '').trim()
  if (!rawMessage) return fallbackMessage
  if (rawMessage === 'voice_service_unavailable') {
    return 'Dashboard data is taking longer than expected. Please refresh and try again.'
  }
  if (rawMessage === 'invalid_voice_service_response') {
    return 'Dashboard service returned an invalid response. Please refresh and try again.'
  }
  return rawMessage
}

function DashboardShell() {
  const { user } = useAuthStore()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()

  const [isBootstrapping, setIsBootstrapping] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [isWidgetsLoading, setIsWidgetsLoading] = useState(false)
  const [isPersistingLayout, setIsPersistingLayout] = useState(false)
  const [isReportsLoading, setIsReportsLoading] = useState(false)
  const [isReportPickerOpen, setIsReportPickerOpen] = useState(false)
  const [isAddingReport, setIsAddingReport] = useState(false)
  const [isSavingPage, setIsSavingPage] = useState(false)
  const [movingWidgetId, setMovingWidgetId] = useState(null)
  const [error, setError] = useState('')
  const [pages, setPages] = useState([])
  const [activePageId, setActivePageId] = useState(null)
  const [pageWidgetsById, setPageWidgetsById] = useState({})
  const [reportsById, setReportsById] = useState(new Map())
  const [liveMaxOccupiedColumns, setLiveMaxOccupiedColumns] = useState(null)
  const [liveGridLayout, setLiveGridLayout] = useState(null)
  const [layoutColumnCommit, setLayoutColumnCommit] = useState(0)
  const [isGridInteracting, setIsGridInteracting] = useState(false)
  const hasBootstrappedRef = useRef(false)
  const embedRefreshInFlightRef = useRef(new Set())
  const { width: gridWidth, mounted: gridMounted, containerRef: gridContainerRef } = useContainerWidth({
    initialWidth: 1280,
  })

  const role = String(user?.role || '').toLowerCase()
  const canManageWidgets = role === 'manager'
  const canSwitchCharts = role === 'manager' || role === 'analyst'
  const selectedReportId = toInteger(searchParams.get('reportId'), 0)
  const requestedPageId = toInteger(searchParams.get('pageId'), 0)

  const activePage = useMemo(
    () => pages.find((page) => toInteger(page.id, 0) === toInteger(activePageId, 0)) || null,
    [activePageId, pages]
  )

  const activeWidgets = useMemo(() => {
    if (!activePage) return []
    const key = toInteger(activePage.id, 0)
    return Array.isArray(pageWidgetsById[key]) ? sortWidgets(pageWidgetsById[key]) : []
  }, [activePage, pageWidgetsById])

  const storedMaxOccupiedColumns = useMemo(
    () => getMaxOccupiedColumns(activeWidgets),
    [activeWidgets]
  )

  const liveLayoutMaxOccupiedColumns = useMemo(
    () => (Array.isArray(liveGridLayout) ? getMaxOccupiedColumns(liveGridLayout) : 0),
    [liveGridLayout]
  )

  const maxOccupiedColumns = useMemo(
    () =>
      Math.max(
        storedMaxOccupiedColumns,
        layoutColumnCommit,
        liveMaxOccupiedColumns && liveMaxOccupiedColumns > 0 ? liveMaxOccupiedColumns : 0,
        liveLayoutMaxOccupiedColumns
      ),
    [
      layoutColumnCommit,
      liveLayoutMaxOccupiedColumns,
      liveMaxOccupiedColumns,
      storedMaxOccupiedColumns,
    ]
  )

  const effectiveGridColumns = useMemo(
    () => resolveEffectiveGridColumns(maxOccupiedColumns),
    [maxOccupiedColumns]
  )

  const dashboardWidgets = useMemo(
    () =>
      activeWidgets.map((widget) => {
        const normalizedWidget = normalizeWidgetLayout(widget, effectiveGridColumns)
        const reportId = toInteger(normalizedWidget?.report_id, 0)
        const report = reportsById.get(reportId)
        return {
          ...normalizedWidget,
          report_id: reportId,
          report_title: String(report?.title || normalizedWidget?.report_title || '').trim(),
          report_status: String(report?.status || normalizedWidget?.report_status || '').trim(),
          report_chart_type: String(report?.chart_type || normalizedWidget?.report_chart_type || '').trim(),
          report_embed_url: String(report?.embed_url || normalizedWidget?.report_embed_url || '').trim(),
          report_render_version: toInteger(
            report?.chart_render_version,
            toInteger(normalizedWidget?.report_render_version, 0)
          ),
        }
      }),
    [activeWidgets, effectiveGridColumns, reportsById]
  )

  const gridLayout = useMemo(
    () => buildLayout(dashboardWidgets, effectiveGridColumns),
    [dashboardWidgets, effectiveGridColumns]
  )

  const displayedGridLayout = useMemo(() => {
    if (!Array.isArray(liveGridLayout) || liveGridLayout.length === 0) {
      return gridLayout
    }

    const baseById = new Map(gridLayout.map((item) => [String(item.i), item]))
    const normalizedLive = liveGridLayout.map((item) => {
      const key = String(item?.i || '')
      const base = baseById.get(key) || {}
      const width = clamp(
        toPositive(item?.w, toPositive(base?.w, DEFAULT_WIDGET_WIDTH)),
        MIN_WIDGET_WIDTH,
        Math.min(MAX_WIDGET_WIDTH, effectiveGridColumns)
      )
      const height = clamp(
        toPositive(item?.h, toPositive(base?.h, DEFAULT_WIDGET_HEIGHT)),
        MIN_WIDGET_HEIGHT,
        MAX_WIDGET_HEIGHT
      )
      const x = clampLayoutX(item?.x ?? base?.x, width, effectiveGridColumns)
      const y = Math.max(0, toInteger(item?.y, toInteger(base?.y, 0)))

      return {
        ...base,
        ...item,
        i: key,
        x,
        y,
        w: width,
        h: height,
        minW: MIN_WIDGET_WIDTH,
        maxW: Math.min(MAX_WIDGET_WIDTH, effectiveGridColumns),
        minH: MIN_WIDGET_HEIGHT,
        maxH: MAX_WIDGET_HEIGHT,
      }
    })

    if (normalizedLive.length === gridLayout.length) {
      return normalizedLive
    }

    const liveIds = new Set(normalizedLive.map((item) => String(item.i)))
    const missingBaseItems = gridLayout.filter((item) => !liveIds.has(String(item.i)))
    return [...normalizedLive, ...missingBaseItems]
  }, [effectiveGridColumns, gridLayout, liveGridLayout])

  const gridCanvasWidth = useMemo(() => {
    const normalizedGridWidth = Math.max(toInteger(gridWidth, 0), 1)
    const baseColumnWidth = normalizedGridWidth / BASE_GRID_COLUMNS
    return Math.max(
      normalizedGridWidth,
      Math.round(baseColumnWidth * effectiveGridColumns)
    )
  }, [effectiveGridColumns, gridWidth])

  const attachedReportIds = useMemo(
    () =>
      new Set(
        dashboardWidgets
          .map((widget) => toInteger(widget?.report_id, 0))
          .filter((reportId) => reportId > 0)
      ),
    [dashboardWidgets]
  )

  const reports = useMemo(
    () =>
      Array.from(reportsById.values()).sort(
        (left, right) => toInteger(right?.id, 0) - toInteger(left?.id, 0)
      ),
    [reportsById]
  )

  const syncPageQuery = useCallback(
    (pageId) => {
      const nextParams = new URLSearchParams(searchParams)
      if (pageId) {
        nextParams.set('pageId', String(pageId))
      } else {
        nextParams.delete('pageId')
      }
      setSearchParams(nextParams, { replace: true })
    },
    [searchParams, setSearchParams]
  )

  const setWidgetsForPage = useCallback((pageId, widgets) => {
    const normalizedPageId = toInteger(pageId, 0)
    if (!normalizedPageId) return
    const normalizedWidgets = Array.isArray(widgets) ? sortWidgets(widgets).map(normalizeWidgetLayout) : []
    setPageWidgetsById((previous) => ({
      ...previous,
      [normalizedPageId]: normalizedWidgets,
    }))
    if (normalizedPageId === toInteger(activePageId, 0)) {
      setLayoutColumnCommit((previous) =>
        Math.max(previous, getMaxOccupiedColumns(normalizedWidgets))
      )
    }
  }, [activePageId])

  const loadWidgetsForPage = useCallback(async (pageId, { silent = false } = {}) => {
    const normalizedPageId = toInteger(pageId, 0)
    if (!normalizedPageId) return
    if (!silent) setIsWidgetsLoading(true)
    try {
      const response = await voiceReportsAPI.listDashboardPageWidgets(normalizedPageId)
      const widgets = Array.isArray(response?.data?.widgets) ? response.data.widgets : []
      setWidgetsForPage(normalizedPageId, widgets)
    } catch (loadError) {
      const shouldRetry =
        toInteger(loadError?.response?.status, 0) === 503 ||
        String(loadError?.response?.data?.error || '').trim() === 'voice_service_unavailable'

      if (shouldRetry) {
        try {
          const retryResponse = await voiceReportsAPI.listDashboardPageWidgets(normalizedPageId)
          const retryWidgets = Array.isArray(retryResponse?.data?.widgets) ? retryResponse.data.widgets : []
          setWidgetsForPage(normalizedPageId, retryWidgets)
          return
        } catch (retryError) {
          console.error('Failed to load page widgets after retry:', retryError)
          setError(resolveDashboardErrorMessage(retryError, 'Failed to load dashboard widgets.'))
          return
        }
      }

      console.error('Failed to load page widgets:', loadError)
      setError(resolveDashboardErrorMessage(loadError, 'Failed to load dashboard widgets.'))
    } finally {
      if (!silent) setIsWidgetsLoading(false)
    }
  }, [setWidgetsForPage])

  const loadReportsCatalog = useCallback(async () => {
    if (isReportsLoading) return
    setIsReportsLoading(true)
    try {
      const response = await voiceReportsAPI.listReports({ lite: true })
      const fetchedReports =
        response?.data?.success && Array.isArray(response?.data?.reports)
          ? response.data.reports
          : []
      setReportsById(listToMap(fetchedReports))
    } catch (loadError) {
      console.error('Failed to load reports catalog:', loadError)
      const message = resolveDashboardErrorMessage(loadError, 'Failed to load reports catalog.')
      setError(message)
      toast.error(message)
    } finally {
      setIsReportsLoading(false)
    }
  }, [isReportsLoading])

  const bootstrapDashboard = useCallback(
    async ({ refresh = false } = {}) => {
      if (refresh) {
        setIsRefreshing(true)
      } else {
        setIsBootstrapping(true)
      }
      setError('')

      try {
        const includeWidgetsInBootstrap = selectedReportId > 0
        const pagesResponse = await voiceReportsAPI.listDashboardPages({
          include_widgets: includeWidgetsInBootstrap,
        })

        const fetchedPages = sortPages(
          Array.isArray(pagesResponse?.data?.pages) ? pagesResponse.data.pages : []
        )

        const widgetsMap = {}
        if (includeWidgetsInBootstrap) {
          fetchedPages.forEach((page) => {
            const pageId = toInteger(page?.id, 0)
            const widgets = Array.isArray(page?.widgets) ? page.widgets.map(normalizeWidgetLayout) : []
            if (pageId > 0) {
              widgetsMap[pageId] = sortWidgets(widgets)
            }
          })
        }

        setPages(fetchedPages)
        setPageWidgetsById(widgetsMap)

        if (fetchedPages.length === 0) {
          setActivePageId(null)
          syncPageQuery(null)
          return
        }

        const validPageIds = new Set(fetchedPages.map((page) => toInteger(page.id, 0)))
        const matchingPage = findPageByReportId(fetchedPages, selectedReportId)

        let nextPageId = null
        if (validPageIds.has(requestedPageId)) {
          nextPageId = requestedPageId
        } else if (matchingPage) {
          nextPageId = toInteger(matchingPage.id, 0)
        } else if (validPageIds.has(toInteger(activePageId, 0))) {
          nextPageId = toInteger(activePageId, 0)
        } else {
          nextPageId = toInteger(fetchedPages[0].id, 0)
        }

        setActivePageId(nextPageId)
        syncPageQuery(nextPageId)
      } catch (loadError) {
        console.error('Failed to bootstrap dashboard shell:', loadError)
        setError(resolveDashboardErrorMessage(loadError, 'Failed to load dashboard pages.'))
      } finally {
        setIsBootstrapping(false)
        setIsRefreshing(false)
      }
    },
    [activePageId, requestedPageId, selectedReportId, syncPageQuery]
  )

  useEffect(() => {
    if (hasBootstrappedRef.current) return
    hasBootstrappedRef.current = true
    bootstrapDashboard()
  }, [bootstrapDashboard])

  useEffect(() => {
    const currentPageId = toInteger(activePageId, 0)
    if (!currentPageId) return
    if (Array.isArray(pageWidgetsById[currentPageId])) return
    loadWidgetsForPage(currentPageId)
  }, [activePageId, loadWidgetsForPage, pageWidgetsById])

  useEffect(() => {
    setLiveMaxOccupiedColumns(null)
    setLiveGridLayout(null)
    setLayoutColumnCommit(0)
  }, [activePageId])

  const handleSwitchPage = (pageId) => {
    const normalizedId = toInteger(pageId, 0)
    if (!normalizedId || normalizedId === toInteger(activePageId, 0)) {
      return
    }
    setActivePageId(normalizedId)
    syncPageQuery(normalizedId)
  }

  const handleCreatePage = useCallback(async () => {
    if (!canManageWidgets) return
    const existingNames = new Set(
      pages.map((page) => String(page?.name || '').trim().toLowerCase()).filter(Boolean)
    )
    let counter = pages.length + 1
    let pageName = `Sheet${counter}`
    while (existingNames.has(pageName.toLowerCase())) {
      counter += 1
      pageName = `Sheet${counter}`
    }

    setIsSavingPage(true)
    setError('')
    try {
      const response = await voiceReportsAPI.createDashboardPage({ name: pageName })
      const createdPage = response?.data?.page
      if (!response?.data?.success || !createdPage) {
        throw new Error(response?.data?.error || 'Failed to create dashboard page.')
      }

      const normalizedPageId = toInteger(createdPage?.id, 0)
      setPages((previous) => {
        const withoutCurrent = previous.filter(
          (page) => toInteger(page?.id, 0) !== normalizedPageId
        )
        return sortPages([...withoutCurrent, createdPage])
      })
      setPageWidgetsById((previous) => ({
        ...previous,
        [normalizedPageId]: [],
      }))
      setActivePageId(normalizedPageId)
      syncPageQuery(normalizedPageId)
      toast.success(`Page "${pageName}" created.`)
    } catch (createError) {
      console.error('Failed to create dashboard page:', createError)
      const message = resolveDashboardErrorMessage(createError, 'Failed to create page.')
      setError(message)
      toast.error(message)
    } finally {
      setIsSavingPage(false)
    }
  }, [canManageWidgets, pages, syncPageQuery])

  const handleRenamePage = useCallback(async (page) => {
    if (!canManageWidgets) return
    const normalizedPageId = toInteger(page?.id, 0)
    if (!normalizedPageId) return
    const currentName = String(page?.name || '').trim()
    const rawName = window.prompt('Rename dashboard page:', currentName)
    if (rawName === null) return
    const pageName = String(rawName).trim()
    if (!pageName) {
      toast.error('Page name is required.')
      return
    }
    if (pageName === currentName) return

    setIsSavingPage(true)
    setError('')
    try {
      const response = await voiceReportsAPI.updateDashboardPage(normalizedPageId, { name: pageName })
      const updatedPage = response?.data?.page
      if (!response?.data?.success || !updatedPage) {
        throw new Error(response?.data?.error || 'Failed to rename dashboard page.')
      }

      setPages((previous) =>
        sortPages(
          previous.map((page) =>
            toInteger(page?.id, 0) === normalizedPageId ? { ...page, ...updatedPage } : page
          )
        )
      )
      toast.success('Dashboard page renamed.')
    } catch (renameError) {
      console.error('Failed to rename dashboard page:', renameError)
      const message = resolveDashboardErrorMessage(renameError, 'Failed to rename page.')
      setError(message)
      toast.error(message)
    } finally {
      setIsSavingPage(false)
    }
  }, [canManageWidgets])

  const handleDeletePage = useCallback(async (page) => {
    if (!canManageWidgets) return
    const normalizedPageId = toInteger(page?.id, 0)
    if (!normalizedPageId) return

    const pageName = String(page?.name || `Page ${normalizedPageId}`).trim()
    const shouldDelete = window.confirm(`Delete "${pageName}"? This will remove all widgets in this page.`)
    if (!shouldDelete) return

    const currentPages = sortPages([...pages])
    const deletedIndex = currentPages.findIndex(
      (currentPage) => toInteger(currentPage?.id, 0) === normalizedPageId
    )

    setIsSavingPage(true)
    setError('')
    try {
      const response = await voiceReportsAPI.deleteDashboardPage(normalizedPageId)
      if (response?.data?.success === false) {
        throw new Error(response?.data?.error || 'Failed to delete dashboard page.')
      }

      const remainingPages = sortPages(
        currentPages.filter((currentPage) => toInteger(currentPage?.id, 0) !== normalizedPageId)
      )
      setPages(remainingPages)
      setPageWidgetsById((previous) => {
        const next = { ...previous }
        delete next[normalizedPageId]
        return next
      })

      const wasActive = normalizedPageId === toInteger(activePageId, 0)
      if (wasActive) {
        const fallbackPage =
          remainingPages[Math.min(Math.max(deletedIndex, 0), Math.max(remainingPages.length - 1, 0))] || null
        const fallbackPageId = fallbackPage ? toInteger(fallbackPage?.id, 0) : null
        setActivePageId(fallbackPageId)
        syncPageQuery(fallbackPageId)
      } else if (remainingPages.length === 0) {
        setActivePageId(null)
        syncPageQuery(null)
      }

      toast.success(`Page "${pageName}" deleted.`)
    } catch (deleteError) {
      console.error('Failed to delete dashboard page:', deleteError)
      const message = resolveDashboardErrorMessage(deleteError, 'Failed to delete page.')
      setError(message)
      toast.error(message)
    } finally {
      setIsSavingPage(false)
    }
  }, [activePageId, canManageWidgets, pages, syncPageQuery])

  const openReportForRole = useCallback((reportId) => {
    if (!reportId) return
    if (role === 'manager') {
      navigate(`/dashboard/voice-reports?reportId=${reportId}`)
      return
    }
    if (role === 'analyst') {
      navigate(`/dashboard/sql-editor?reportId=${reportId}`)
      return
    }
    navigate(`/dashboard?reportId=${reportId}`)
  }, [navigate, role])

  const openReportPicker = useCallback(() => {
    if (!canManageWidgets) return
    setIsReportPickerOpen(true)
    if (reportsById.size === 0) {
      loadReportsCatalog()
    }
  }, [canManageWidgets, loadReportsCatalog, reportsById.size])

  const handleCreateReportFromPage = useCallback(() => {
    const normalizedPageId = toInteger(activePageId, 0)
    if (!normalizedPageId) return
    const returnTo = `/dashboard?pageId=${normalizedPageId}`
    navigate(
      `/dashboard/voice-reports?attachPageId=${normalizedPageId}&returnTo=${encodeURIComponent(returnTo)}`
    )
  }, [activePageId, navigate])

  const handleAttachReportToActivePage = useCallback(async (reportId) => {
    if (!canManageWidgets) return
    const normalizedPageId = toInteger(activePageId, 0)
    const normalizedReportId = toInteger(reportId, 0)
    if (!normalizedPageId || !normalizedReportId) return

    setIsAddingReport(true)
    setError('')
    try {
      const nextY = getNextWidgetY(dashboardWidgets)
      const response = await voiceReportsAPI.createDashboardWidget(normalizedPageId, {
        report_id: normalizedReportId,
        x: 0,
        y: nextY,
        width: DEFAULT_WIDGET_WIDTH,
        height: DEFAULT_WIDGET_HEIGHT,
        order: dashboardWidgets.length,
      })

      if (!response?.data?.success || !response?.data?.widget) {
        throw new Error(response?.data?.error || 'Failed to attach report to page.')
      }

      const attachedWidget = normalizeWidgetLayout(response.data.widget)
      setPageWidgetsById((previous) => {
        const existing = Array.isArray(previous[normalizedPageId]) ? previous[normalizedPageId] : []
        const withoutCurrent = existing.filter(
          (widget) => toInteger(widget?.id, 0) !== toInteger(attachedWidget?.id, 0)
        )
        return {
          ...previous,
          [normalizedPageId]: sortWidgets([...withoutCurrent, attachedWidget]).map(normalizeWidgetLayout),
        }
      })

      toast.success(
        response?.data?.created === false
          ? 'Report was already on this page. Widget layout updated.'
          : 'Report added to dashboard page.'
      )
    } catch (attachError) {
      console.error('Failed to attach report to page:', attachError)
      const message = resolveDashboardErrorMessage(attachError, 'Failed to add report.')
      setError(message)
      toast.error(message)
    } finally {
      setIsAddingReport(false)
    }
  }, [activePageId, canManageWidgets, dashboardWidgets])

  const handleMoveWidgetToPage = useCallback(async (widget, targetPageId) => {
    if (!canManageWidgets) return
    const widgetId = toInteger(widget?.id, 0)
    const sourcePageId = toInteger(activePageId, 0)
    const destinationPageId = toInteger(targetPageId, 0)
    if (!widgetId || !sourcePageId || !destinationPageId || sourcePageId === destinationPageId) {
      return
    }

    const destinationWidgets = Array.isArray(pageWidgetsById[destinationPageId])
      ? pageWidgetsById[destinationPageId]
      : []
    const requestedOrder = destinationWidgets.length

    setMovingWidgetId(widgetId)
    setError('')
    try {
      const response = await voiceReportsAPI.updateDashboardWidget(widgetId, {
        page_id: destinationPageId,
        order: requestedOrder,
      })
      if (!response?.data?.success || !response?.data?.widget) {
        throw new Error(response?.data?.error || 'Failed to move widget.')
      }

      const movedWidget = normalizeWidgetLayout(response.data.widget)
      setPageWidgetsById((previous) => {
        const sourceWidgets = Array.isArray(previous[sourcePageId]) ? previous[sourcePageId] : []
        const nextSource = sourceWidgets.filter(
          (candidate) => toInteger(candidate?.id, 0) !== widgetId
        )

        const existingDestination = Array.isArray(previous[destinationPageId])
          ? previous[destinationPageId]
          : []
        const nextDestination = existingDestination.filter(
          (candidate) => toInteger(candidate?.id, 0) !== widgetId
        )

        return {
          ...previous,
          [sourcePageId]: sortWidgets(nextSource).map(normalizeWidgetLayout),
          [destinationPageId]: sortWidgets([...nextDestination, movedWidget]).map(normalizeWidgetLayout),
        }
      })
      toast.success('Widget moved to selected page.')
    } catch (moveError) {
      console.error('Failed to move widget between pages:', moveError)
      const message = resolveDashboardErrorMessage(moveError, 'Failed to move widget.')
      setError(message)
      toast.error(message)
      await loadWidgetsForPage(sourcePageId, { silent: true })
      await loadWidgetsForPage(destinationPageId, { silent: true })
    } finally {
      setMovingWidgetId(null)
    }
  }, [activePageId, canManageWidgets, loadWidgetsForPage, pageWidgetsById])

  const handleSetWidgetExactSize = useCallback(async (widget, size) => {
    if (!canManageWidgets) {
      return { success: false, message: 'Only managers can resize widgets.' }
    }

    const widgetId = toInteger(widget?.id, 0)
    const normalizedPageId = toInteger(activePageId, 0)
    if (!widgetId || !normalizedPageId) {
      return { success: false, message: 'Invalid widget context.' }
    }

    const nextWidth = clamp(
      toPositive(size?.width, toInteger(widget?.width, DEFAULT_WIDGET_WIDTH)),
      MIN_WIDGET_WIDTH,
      MAX_WIDGET_WIDTH
    )
    const nextHeight = clamp(
      toPositive(size?.height, toInteger(widget?.height, DEFAULT_WIDGET_HEIGHT)),
      MIN_WIDGET_HEIGHT,
      MAX_WIDGET_HEIGHT
    )

    setPageWidgetsById((previous) => {
      const existing = Array.isArray(previous[normalizedPageId]) ? previous[normalizedPageId] : []
      const nextWidgets = existing.map((candidate) => {
        if (toInteger(candidate?.id, 0) !== widgetId) return candidate
        return normalizeWidgetLayout({
          ...candidate,
          width: nextWidth,
          height: nextHeight,
        })
      })
      return {
        ...previous,
        [normalizedPageId]: sortWidgets(nextWidgets).map(normalizeWidgetLayout),
      }
    })

    try {
      const response = await voiceReportsAPI.updateDashboardWidget(widgetId, {
        width: nextWidth,
        height: nextHeight,
      })
      const updatedWidget = response?.data?.widget
      if (!response?.data?.success || !updatedWidget) {
        throw new Error(response?.data?.error || 'Failed to apply widget size.')
      }

      const normalizedUpdatedWidget = normalizeWidgetLayout(updatedWidget)
      setPageWidgetsById((previous) => {
        const existing = Array.isArray(previous[normalizedPageId]) ? previous[normalizedPageId] : []
        const nextWidgets = existing.map((candidate) =>
          toInteger(candidate?.id, 0) === widgetId ? normalizedUpdatedWidget : candidate
        )
        return {
          ...previous,
          [normalizedPageId]: sortWidgets(nextWidgets).map(normalizeWidgetLayout),
        }
      })

      return { success: true }
    } catch (resizeError) {
      console.error('Failed to set exact widget size:', resizeError)
      await loadWidgetsForPage(normalizedPageId, { silent: true })
      return {
        success: false,
        message: resolveDashboardErrorMessage(resizeError, 'Failed to update widget size.'),
      }
    }
  }, [activePageId, canManageWidgets, loadWidgetsForPage])

  const handlePersistLayout = useCallback(async (layout) => {
    if (!canManageWidgets) return
    const normalizedPageId = toInteger(activePageId, 0)
    if (!normalizedPageId) return
    if (!Array.isArray(layout)) {
      setLiveMaxOccupiedColumns(null)
      setLiveGridLayout(null)
      setIsGridInteracting(false)
      return
    }

    const widgetsById = dashboardWidgets.reduce((accumulator, widget) => {
      accumulator.set(String(toInteger(widget?.id, 0)), widget)
      return accumulator
    }, new Map())
    const { updates, persistGridColumns } = computeLayoutUpdates({ layout, widgetsById })

    if (updates.length === 0) {
      setLayoutColumnCommit((previous) =>
        Math.max(previous, getMaxOccupiedColumns(layout))
      )
      setLiveMaxOccupiedColumns(null)
      setLiveGridLayout(null)
      setIsGridInteracting(false)
      return
    }

    setLayoutColumnCommit((previous) =>
      Math.max(previous, getMaxOccupiedColumns(layout))
    )

    setPageWidgetsById((previous) => {
      const existing = Array.isArray(previous[normalizedPageId]) ? previous[normalizedPageId] : []
      const updateMap = new Map(updates.map((update) => [toInteger(update.widget_id, 0), update]))
      const nextWidgets = existing.map((widget) => {
        const update = updateMap.get(toInteger(widget?.id, 0))
        if (!update) return widget
        return normalizeWidgetLayout(
          {
            ...widget,
            x: update.x,
            y: update.y,
            width: update.width,
            height: update.height,
          },
          persistGridColumns
        )
      })
      return {
        ...previous,
        [normalizedPageId]: sortWidgets(nextWidgets).map((widget) =>
          normalizeWidgetLayout(widget, persistGridColumns)
        ),
      }
    })
    setIsPersistingLayout(true)
    setError('')
    try {
      const response = await voiceReportsAPI.batchUpdateDashboardWidgets({ updates })
      const updatedWidgets = Array.isArray(response?.data?.widgets) ? response.data.widgets : []
      if (updatedWidgets.length > 0) {
        setPageWidgetsById((previous) => {
          const existing = Array.isArray(previous[normalizedPageId]) ? previous[normalizedPageId] : []
          const optimisticLayoutMap = new Map(
            updates.map((update) => [toInteger(update?.widget_id, 0), update])
          )
          const updateMap = new Map(
            updatedWidgets.map((updatedWidget) => {
              const widgetId = toInteger(updatedWidget?.id, 0)
              const optimistic = optimisticLayoutMap.get(widgetId)
              const normalizedServerWidget = normalizeWidgetLayout(updatedWidget, persistGridColumns)
              const mergedWidget = optimistic
                ? normalizeWidgetLayout(
                    {
                      ...normalizedServerWidget,
                      x: optimistic.x,
                      y: optimistic.y,
                      width: optimistic.width,
                      height: optimistic.height,
                    },
                    persistGridColumns
                  )
                : normalizedServerWidget
              return [widgetId, mergedWidget]
            })
          )

          const merged = existing.map((widget) => {
            const widgetId = toInteger(widget?.id, 0)
            return updateMap.get(widgetId) || widget
          })
          return {
            ...previous,
            [normalizedPageId]: sortWidgets(merged).map((widget) =>
              normalizeWidgetLayout(widget, persistGridColumns)
            ),
          }
        })
        setLayoutColumnCommit((previous) =>
          Math.max(previous, getMaxOccupiedColumns(updatedWidgets))
        )
      }
    } catch (persistError) {
      console.error('Failed to persist dashboard widget layout:', persistError)
      const message = resolveDashboardErrorMessage(persistError, 'Failed to save widget layout.')
      setError(message)
      toast.error(message)
      await loadWidgetsForPage(normalizedPageId, { silent: true })
    } finally {
      setLiveMaxOccupiedColumns(null)
      setLiveGridLayout(null)
      setIsGridInteracting(false)
      setIsPersistingLayout(false)
    }
  }, [activePageId, canManageWidgets, dashboardWidgets, loadWidgetsForPage])

  const handleGridInteractStart = useCallback(() => {
    setIsGridInteracting(true)
  }, [])

  const handleGridStop = useCallback((layout) => {
    const clonedLayout = cloneLayoutItems(layout)
    const nextOccupiedColumns = getMaxOccupiedColumns(clonedLayout)
    setLiveGridLayout(clonedLayout)
    setLiveMaxOccupiedColumns((previous) => {
      if (!previous || previous <= 0) return nextOccupiedColumns
      return Math.max(previous, nextOccupiedColumns)
    })
    handlePersistLayout(clonedLayout || layout)
  }, [handlePersistLayout])

  const handleGridInteract = useCallback((layout) => {
    const clonedLayout = cloneLayoutItems(layout)
    const nextOccupiedColumns = getMaxOccupiedColumns(clonedLayout)
    setLiveGridLayout(clonedLayout)
    setLiveMaxOccupiedColumns((previous) =>
      isGridInteracting && previous && previous > 0
        ? Math.max(previous, nextOccupiedColumns)
        : nextOccupiedColumns
    )
  }, [isGridInteracting])

  const handleWidgetEmbedError = useCallback(async (reportId) => {
    const normalizedReportId = toInteger(reportId, 0)
    if (!normalizedReportId) return
    if (embedRefreshInFlightRef.current.has(normalizedReportId)) return

    embedRefreshInFlightRef.current.add(normalizedReportId)
    try {
      const response = await voiceReportsAPI.getReport(normalizedReportId)
      const refreshedReport = response?.data?.report
      const refreshedEmbedUrl = String(refreshedReport?.embed_url || '').trim()
      if (!refreshedEmbedUrl) return

      setPageWidgetsById((previous) => {
        const next = {}
        Object.entries(previous).forEach(([pageId, widgets]) => {
          next[pageId] = Array.isArray(widgets)
            ? widgets.map((widget) =>
                toInteger(widget?.report_id, 0) === normalizedReportId
                  ? { ...widget, report_embed_url: refreshedEmbedUrl }
                  : widget
              )
            : widgets
        })
        return next
      })
    } catch (refreshError) {
      console.error('Failed to refresh widget embed URL:', refreshError)
    } finally {
      embedRefreshInFlightRef.current.delete(normalizedReportId)
    }
  }, [])

  const handleWidgetChartTypeChanged = useCallback((reportId, payload = {}) => {
    const normalizedReportId = toInteger(reportId, 0)
    if (!normalizedReportId) return
    const nextChartType = String(payload?.chart_type || '').trim()
    const nextEmbedUrl = String(payload?.embed_url || '').trim()

    setReportsById((previous) => {
      const next = new Map(previous)
      const current = next.get(normalizedReportId) || { id: normalizedReportId }
      const currentVersion = toInteger(current?.chart_render_version, 0)
      next.set(normalizedReportId, {
        ...current,
        chart_type: nextChartType || current.chart_type || '',
        embed_url: nextEmbedUrl || current.embed_url || '',
        chart_render_version: currentVersion + 1,
      })
      return next
    })

    setPageWidgetsById((previous) => {
      const next = {}
      Object.entries(previous).forEach(([pageId, widgets]) => {
        next[pageId] = Array.isArray(widgets)
          ? widgets.map((widget) => {
              if (toInteger(widget?.report_id, 0) !== normalizedReportId) return widget
              return {
                ...widget,
                report_chart_type: nextChartType || String(widget?.report_chart_type || '').trim(),
                report_embed_url: nextEmbedUrl || String(widget?.report_embed_url || '').trim(),
                report_render_version: toInteger(widget?.report_render_version, 0) + 1,
              }
            })
          : widgets
      })
      return next
    })
  }, [])

  if (isBootstrapping) {
    return (
      <AnimatedPage className="max-w-7xl mx-auto">
        <Card>
          <div className="flex flex-col items-center justify-center py-24 text-[var(--c-muted)]">
            <Loader2 className="w-9 h-9 animate-spin mb-4" />
            <p className="text-sm">Loading dashboard pages...</p>
          </div>
        </Card>
      </AnimatedPage>
    )
  }

  return (
    <AnimatedPage className="max-w-7xl mx-auto space-y-6 pb-24">
      {error ? (
        <Card className="border border-red-200">
          <div className="flex items-center gap-3 text-red-700">
            <AlertCircle className="w-5 h-5" />
            <p className="text-sm">{error}</p>
          </div>
        </Card>
      ) : null}

      {pages.length === 0 ? (
        <Card>
          <div className="py-20 text-center">
            <FileText className="w-12 h-12 mx-auto text-brand-300/60 mb-4" />
            <h2 className="text-xl font-semibold text-white">No Dashboard Pages Yet</h2>
            <p className="text-[var(--c-muted)] mt-2">
              Managers can create dashboard pages and attach reports. Analysts and executives will see them here.
            </p>
            {canManageWidgets ? (
              <div className="mt-6">
                <Button type="button" onClick={handleCreatePage} loading={isSavingPage}>
                  <PlusCircle className="w-4 h-4" />
                  <span>Create First Page</span>
                </Button>
              </div>
            ) : null}
          </div>
        </Card>
      ) : (
        <>
          <Card className="dashboard-grid-surface">
            <div className="flex items-center justify-between mb-4 gap-3">
              <div>
                <h2 className="text-lg font-semibold text-white">
                  {activePage?.name || 'Selected Page'}
                </h2>
                <span className="text-xs uppercase tracking-[0.12em] text-brand-300/80">
                  {dashboardWidgets.length} widget{dashboardWidgets.length === 1 ? '' : 's'}
                </span>
                {activePage?.description ? (
                  <p className="mt-1 text-sm text-[var(--c-muted)]">{activePage.description}</p>
                ) : null}
              </div>

              <div className="flex items-center gap-2">
                {isPersistingLayout ? (
                  <span className="text-xs text-brand-300/80 inline-flex items-center gap-1">
                    <Loader2 className="w-3 h-3 animate-spin" />
                    Saving layout...
                  </span>
                ) : null}
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => bootstrapDashboard({ refresh: true })}
                  loading={isRefreshing}
                  disabled={isBootstrapping || isSavingPage}
                >
                  <RefreshCw className="w-4 h-4" />
                  <span>Refresh</span>
                </Button>
                {canManageWidgets ? (
                  <>
                    <Button
                      type="button"
                      variant="secondary"
                      onClick={openReportPicker}
                    >
                      <PlusCircle className="w-4 h-4" />
                      <span>Add Report</span>
                    </Button>
                    <Button type="button" onClick={handleCreateReportFromPage}>
                      <PlusCircle className="w-4 h-4" />
                      <span>Create Report</span>
                    </Button>
                  </>
                ) : null}
              </div>
            </div>

            {isWidgetsLoading ? (
              <div className="flex items-center justify-center py-20 text-brand-300/80">
                <Loader2 className="w-6 h-6 animate-spin mr-2" />
                <span>Loading page widgets...</span>
              </div>
            ) : dashboardWidgets.length === 0 ? (
              <div className="py-20 text-center">
                <BarChart3 className="w-10 h-10 text-brand-300/60 mx-auto mb-3" />
                <p className="text-brand-300 font-medium">This page has no widgets yet.</p>
                <p className="text-sm text-brand-300/80 mt-1">
                  Attached reports will appear here as dashboard widgets.
                </p>
                {canManageWidgets ? (
                  <div className="mt-6 flex items-center justify-center gap-2">
                    <Button
                      type="button"
                      variant="secondary"
                      onClick={openReportPicker}
                    >
                      <PlusCircle className="w-4 h-4" />
                      <span>Add Existing Report</span>
                    </Button>
                    <Button type="button" onClick={handleCreateReportFromPage}>
                      <PlusCircle className="w-4 h-4" />
                      <span>Create Report</span>
                    </Button>
                  </div>
                ) : null}
              </div>
            ) : (
              <div ref={gridContainerRef} className="overflow-x-auto overflow-y-visible pb-2">
                {gridMounted ? (
                  <div className="dashboard-grid-canvas min-w-full" style={{ width: `${gridCanvasWidth}px` }}>
                    <ReactGridLayout
                      width={gridCanvasWidth}
                      layout={displayedGridLayout}
                      cols={effectiveGridColumns}
                      rowHeight={GRID_ROW_HEIGHT}
                      margin={[16, 16]}
                      containerPadding={[0, 0]}
                      compactType={null}
                      isDraggable={canManageWidgets}
                      isResizable={canManageWidgets}
                      draggableHandle=".dashboard-widget-drag-handle"
                      resizeHandles={['se']}
                      onDragStart={handleGridInteractStart}
                      onDrag={handleGridInteract}
                      onResizeStart={handleGridInteractStart}
                      onResize={handleGridInteract}
                      onDragStop={handleGridStop}
                      onResizeStop={handleGridStop}
                    >
                      {dashboardWidgets.map((widget) => (
                        <div key={String(toInteger(widget?.id, 0))} className="h-full overflow-hidden">
                          <DashboardWidgetCard
                            widget={widget}
                            pages={pages}
                            currentPageId={toInteger(activePageId, 0)}
                            canManageWidgets={canManageWidgets}
                            canSwitchCharts={canSwitchCharts}
                            isMoving={toInteger(movingWidgetId, 0) === toInteger(widget?.id, 0)}
                          onOpenReport={openReportForRole}
                          onMoveWidget={handleMoveWidgetToPage}
                          onResizeWidget={handleSetWidgetExactSize}
                          onEmbedError={handleWidgetEmbedError}
                          onChartTypeChanged={handleWidgetChartTypeChanged}
                        />
                        </div>
                      ))}
                    </ReactGridLayout>
                  </div>
                ) : (
                  <div className="flex items-center justify-center py-16 text-brand-300/80">
                    <Loader2 className="w-5 h-5 animate-spin mr-2" />
                    <span>Preparing dashboard grid...</span>
                  </div>
                )}
              </div>
            )}
          </Card>
        </>
      )}

      {pages.length > 0 ? (
        <div className="fixed left-0 right-0 bottom-0 z-20 border-t border-brand-700/30 bg-[var(--c-card-bg)] backdrop-blur-sm">
          <div className="max-w-7xl mx-auto px-4">
            <div className="overflow-x-auto">
              <div className="flex items-stretch min-w-max">
                {pages.map((page) => {
                  const pageId = toInteger(page?.id, 0)
                  const isActive = pageId === toInteger(activePageId, 0)
                  return (
                    <div
                      key={pageId}
                      className={`group relative border-r border-brand-700/30 ${
                        isActive ? 'bg-[rgba(255,255,255,0.07)]' : 'bg-[var(--c-card-bg)] hover:bg-[rgba(255,255,255,0.04)]'
                      }`}
                    >
                      <button
                        type="button"
                        onClick={() => handleSwitchPage(pageId)}
                        onDoubleClick={() => handleRenamePage(page)}
                        className={`
                          px-4 py-3 text-sm transition-colors select-none whitespace-nowrap
                          ${canManageWidgets ? 'pr-10' : ''}
                          ${isActive ? 'text-white font-semibold' : 'text-brand-300'}
                        `}
                        title={canManageWidgets ? 'Double-click to rename page' : ''}
                      >
                        {String(page?.name || `Page ${pageId}`)}
                      </button>

                      {canManageWidgets ? (
                        <button
                          type="button"
                          onClick={(event) => {
                            event.stopPropagation()
                            handleDeletePage(page)
                          }}
                          disabled={isSavingPage}
                          className={`
                            absolute right-2 top-1/2 -translate-y-1/2 h-6 w-6
                            items-center justify-center rounded-full border bg-[var(--c-card-bg)]
                            text-brand-300/60 transition hidden group-hover:flex
                            hover:text-red-600 hover:border-red-200 disabled:opacity-50
                          `}
                          title={`Delete ${String(page?.name || `Page ${pageId}`)}`}
                          aria-label={`Delete ${String(page?.name || `Page ${pageId}`)}`}
                        >
                          <X className="w-3.5 h-3.5" />
                        </button>
                      ) : null}
                    </div>
                  )
                })}

                {canManageWidgets ? (
                  <button
                    type="button"
                    onClick={handleCreatePage}
                    disabled={isSavingPage}
                    className="px-4 py-3 text-lg border-r border-brand-700/30 bg-[var(--c-card-bg)] text-brand-300 hover:bg-[rgba(255,255,255,0.04)] disabled:opacity-60"
                    title="Add page"
                  >
                    {isSavingPage ? <Loader2 className="w-4 h-4 animate-spin" /> : '+'}
                  </button>
                ) : null}
              </div>
            </div>
          </div>
        </div>
      ) : null}

      <DashboardReportPickerModal
        isOpen={isReportPickerOpen}
        onClose={() => setIsReportPickerOpen(false)}
        reports={reports}
        attachedReportIds={attachedReportIds}
        isLoading={isReportsLoading}
        isAddingReport={isAddingReport}
        onAttachReport={handleAttachReportToActivePage}
        canCreateReport={canManageWidgets}
        onCreateReport={handleCreateReportFromPage}
      />
    </AnimatedPage>
  )
}

export default DashboardShell
