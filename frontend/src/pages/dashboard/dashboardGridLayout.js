export const BASE_GRID_COLUMNS = 12
export const GRID_MAX_COLUMNS = 120
export const GRID_RIGHT_BUFFER_COLUMNS = 2
export const DEFAULT_WIDGET_WIDTH = 6
export const DEFAULT_WIDGET_HEIGHT = 4

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

/** Widest column edge (x + width) across widgets or RGL layout items. */
export const getMaxOccupiedColumns = (items) => {
  if (!Array.isArray(items) || items.length === 0) return 0
  return items.reduce((maxColumn, item) => {
    const x = clamp(toInteger(item?.x, 0), 0, GRID_MAX_COLUMNS - 1)
    const width = clamp(
      toPositive(item?.w ?? item?.width, DEFAULT_WIDGET_WIDTH),
      1,
      GRID_MAX_COLUMNS
    )
    return Math.max(maxColumn, x + width)
  }, 0)
}

/** Column count passed to react-grid-layout (includes right drag buffer). */
export const resolveEffectiveGridColumns = (...occupiedExtents) => {
  const maxOccupied = occupiedExtents.reduce(
    (max, extent) => Math.max(max, toInteger(extent, 0)),
    0
  )
  return clamp(
    Math.max(maxOccupied + GRID_RIGHT_BUFFER_COLUMNS, BASE_GRID_COLUMNS),
    BASE_GRID_COLUMNS,
    GRID_MAX_COLUMNS
  )
}

export const clampLayoutX = (x, width, maxColumns = GRID_MAX_COLUMNS) => {
  const normalizedColumns = Math.max(BASE_GRID_COLUMNS, toInteger(maxColumns, GRID_MAX_COLUMNS))
  const normalizedWidth = clamp(toPositive(width, DEFAULT_WIDGET_WIDTH), 1, normalizedColumns)
  let normalizedX = clamp(toInteger(x, 0), 0, normalizedColumns - 1)
  if (normalizedX + normalizedWidth > normalizedColumns) {
    normalizedX = Math.max(0, normalizedColumns - normalizedWidth)
  }
  return normalizedX
}

export const computeLayoutUpdates = ({ layout, widgetsById }) => {
  if (!Array.isArray(layout)) {
    return { updates: [], persistGridColumns: BASE_GRID_COLUMNS }
  }

  const persistGridColumns = resolveEffectiveGridColumns(getMaxOccupiedColumns(layout))
  const updates = []

  layout.forEach((layoutItem) => {
    const key = String(layoutItem?.i || '')
    const widget = widgetsById.get(key)
    if (!widget) return

    const nextWidth = clamp(toPositive(layoutItem?.w, widget.width), 1, GRID_MAX_COLUMNS)
    const nextX = clampLayoutX(layoutItem?.x, nextWidth, GRID_MAX_COLUMNS)
    const nextHeight = clamp(toPositive(layoutItem?.h, widget.height), 1, 48)
    const nextY = Math.max(0, toInteger(layoutItem?.y, widget.y))

    if (
      nextX !== toInteger(widget?.x, 0) ||
      nextY !== toInteger(widget?.y, 0) ||
      nextWidth !== toInteger(widget?.width, DEFAULT_WIDGET_WIDTH) ||
      nextHeight !== toInteger(widget?.height, DEFAULT_WIDGET_HEIGHT)
    ) {
      updates.push({
        widget_id: toInteger(widget?.id, 0),
        x: nextX,
        y: nextY,
        width: nextWidth,
        height: nextHeight,
      })
    }
  })

  return { updates, persistGridColumns }
}
