const CATEGORY_LABELS = {
  data_source: 'Data source',
  permission: 'Permission',
  subscription: 'Subscription',
  ai_pipeline: 'AI pipeline',
  sql: 'SQL execution',
  visualization: 'Visualization',
  service: 'Service',
}

const includesLimitMessage = (value) =>
  String(value || '').toLowerCase().includes('reached your limit')

export function describeVoiceWorkflowError(error) {
  const data = error?.response?.data || {}
  const status = Number(error?.response?.status || 0)
  const code = String(data.code || '').toLowerCase()
  const rawMessage = data.message || data.error || error?.message || 'Processing failed'

  let category = String(data.category || '').toLowerCase()
  if (!category) {
    if (includesLimitMessage(rawMessage) || code.includes('subscription')) {
      category = 'subscription'
    } else if (status === 401 || status === 403) {
      category = 'permission'
    } else if (code.startsWith('dataset_')) {
      category = 'data_source'
    } else if (code.includes('sql') || code.includes('query')) {
      category = 'sql'
    } else if (code.includes('metabase') || code.includes('visualization')) {
      category = 'visualization'
    } else if (code.includes('ai') || code.includes('pipeline')) {
      category = 'ai_pipeline'
    } else {
      category = 'service'
    }
  }

  const label = CATEGORY_LABELS[category] || 'Service'
  return {
    category,
    message: `${label}: ${rawMessage}`,
    shouldShowSubscription: category === 'subscription' || includesLimitMessage(rawMessage),
  }
}
