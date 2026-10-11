const adjustmentClassByType = {
  derived_field: 'bg-amber-500/20 text-amber-400 dark:bg-amber-400/40 dark:text-amber-400',
  mapped_column: 'bg-amber-500/20 text-amber-400 dark:bg-amber-400/40 dark:text-amber-400',
}

function Pill({ text, className }) {
  return (
    <span className={`inline-flex rounded-full px-2 py-1 text-xs font-medium ${className}`}>
      {text}
    </span>
  )
}

function SchemaUsageViewer({
  schemaUsed = {},
  adjustments = [],
  selectedTable = '',
  selectedColumns = [],
}) {
  const schemaTables = Array.isArray(schemaUsed?.tables) ? schemaUsed.tables : []
  const schemaColumns = Array.isArray(schemaUsed?.columns) ? schemaUsed.columns : []
  const fallbackTables = selectedTable ? [selectedTable] : []
  const fallbackColumns = Array.isArray(selectedColumns)
    ? selectedColumns.map((column) =>
      selectedTable ? `${selectedTable}.${column}` : String(column || '').trim()
    ).filter((column) => String(column || '').trim())
    : []

  const tables = schemaTables.length > 0 ? schemaTables : fallbackTables
  const columns = schemaColumns.length > 0 ? schemaColumns : fallbackColumns

  return (
    <div className="space-y-4">
      <div>
        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-brand-300/80 dark:text-brand-300/60">
          Tables Used
        </p>
        {tables.length > 0 ? (
          <div className="flex flex-wrap gap-2">
            {tables.map((table, index) => (
              <Pill
                key={`${table}-${index}`}
                text={table}
                className="bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-200"
              />
            ))}
          </div>
        ) : (
          <p className="text-sm text-brand-300/80 dark:text-brand-300/60">No table references detected.</p>
        )}
      </div>

      <div>
        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-brand-300/80 dark:text-brand-300/60">
          Columns Used
        </p>
        {columns.length > 0 ? (
          <div className="flex flex-wrap gap-2">
            {columns.map((column, index) => (
              <Pill
                key={`${column}-${index}`}
                text={column}
                className="bg-green-50 text-green-700 dark:bg-green-900/20 dark:text-green-300"
              />
            ))}
          </div>
        ) : (
          <p className="text-sm text-brand-300/80 dark:text-brand-300/60">No column references detected.</p>
        )}
      </div>

      <div>
        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-brand-300/80 dark:text-brand-300/60">
          Schema Adjustments
        </p>
        {Array.isArray(adjustments) && adjustments.length > 0 ? (
          <div className="space-y-2">
            {adjustments.map((adjustment, index) => (
              <div
                key={`${adjustment.type}-${index}`}
                className="rounded-lg border border-brand-700/30 bg-[var(--c-card-bg)] p-3 dark:border-brand-700/40 dark:bg-brand-950/40"
              >
                <div className="flex items-center gap-2 text-sm">
                  <Pill
                    text={String(adjustment.type || 'mapped_column').replace('_', ' ')}
                    className={adjustmentClassByType[adjustment.type] || adjustmentClassByType.mapped_column}
                  />
                  <span className="text-brand-300 dark:text-brand-200">{adjustment.description}</span>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-brand-300/80 dark:text-brand-300/60">No schema adjustments were required.</p>
        )}
      </div>
    </div>
  )
}

export default SchemaUsageViewer
