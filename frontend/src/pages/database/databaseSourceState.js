export function buildInitialConfiguration(connector) {
  return Object.fromEntries(
    (connector?.fields || [])
      .filter((field) => field.default !== undefined)
      .map((field) => [field.name, field.default]),
  )
}

export function redactTransientSecrets(configuration) {
  const result = { ...(configuration || {}) }
  for (const key of ['password', 'ssl_key', 'wallet_password']) {
    if (key in result) result[key] = ''
  }
  return result
}

export function tableSelectionKey(table) {
  return `${table?.schema || ''}.${table?.name || ''}`
}

export function sourceErrorMessage(error, fallback) {
  return error?.response?.data?.error?.message || error?.response?.data?.message || fallback
}

export function capabilityConnectorIds(capabilityPayload) {
  return (capabilityPayload?.connectors || []).map((connector) => connector.id)
}

export function connectorWorkflow(connector) {
  return connector?.workflow === 'file_upload' ? 'sqlite-upload' : 'server-connection'
}

export function operationState(operation, result) {
  const states = {
    test: { pending: 'testing', success: 'test-success', failure: 'failed' },
    discover: { pending: 'discovering', success: 'ready', failure: 'failed' },
    snapshot: { pending: 'starting', success: 'started', failure: 'failed' },
  }
  return states[operation]?.[result] || 'idle'
}

export function pollOutcome(status) {
  if (status === 'completed') return { stop: true, loadPreview: true, failed: false }
  if (status === 'failed') return { stop: true, loadPreview: false, failed: true }
  return { stop: false, loadPreview: false, failed: false }
}

export function isSupportedLegacyUpload(file) {
  if (!file) return false
  const allowedTypes = new Set([
    'text/csv',
    'application/vnd.ms-excel',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'text/plain',
  ])
  return allowedTypes.has(file.type) || /\.(csv|xlsx|xls)$/i.test(file.name || '')
}
