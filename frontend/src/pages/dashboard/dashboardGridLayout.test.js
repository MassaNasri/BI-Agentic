import { describe, it } from 'node:test'
import assert from 'node:assert/strict'
import {
  BASE_GRID_COLUMNS,
  clampLayoutX,
  computeLayoutUpdates,
  getMaxOccupiedColumns,
  resolveEffectiveGridColumns,
} from './dashboardGridLayout.js'

describe('getMaxOccupiedColumns', () => {
  it('returns 0 for empty input', () => {
    assert.equal(getMaxOccupiedColumns([]), 0)
  })

  it('uses actual widget extent instead of a fixed floor', () => {
    assert.equal(getMaxOccupiedColumns([{ x: 0, width: 6 }]), 6)
    assert.equal(getMaxOccupiedColumns([{ x: 10, width: 6 }]), 16)
  })
})

describe('resolveEffectiveGridColumns', () => {
  it('keeps at least the base column count', () => {
    assert.equal(resolveEffectiveGridColumns(0), BASE_GRID_COLUMNS)
    assert.equal(resolveEffectiveGridColumns(6), BASE_GRID_COLUMNS)
  })

  it('expands when widgets occupy more columns', () => {
    assert.equal(resolveEffectiveGridColumns(16), 18)
  })
})

describe('clampLayoutX', () => {
  it('allows movement to the right within expanded grid columns', () => {
    assert.equal(clampLayoutX(10, 6, 18), 10)
  })

  it('only clamps when exceeding the provided column limit', () => {
    assert.equal(clampLayoutX(10, 6, 14), 8)
  })
})

describe('computeLayoutUpdates', () => {
  it('detects rightward moves that were previously dropped by narrow grids', () => {
    const widgetsById = new Map([
      [
        '1',
        {
          id: 1,
          x: 0,
          y: 0,
          width: 6,
          height: 3,
        },
      ],
    ])
    const layout = [{ i: '1', x: 8, y: 0, w: 6, h: 3 }]
    const { updates, persistGridColumns } = computeLayoutUpdates({ layout, widgetsById })

    assert.equal(persistGridColumns, 16)
    assert.equal(updates.length, 1)
    assert.equal(updates[0].x, 8)
  })
})
