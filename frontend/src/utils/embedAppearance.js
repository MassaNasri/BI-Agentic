export const withNightEmbedAppearance = (rawUrl = '') => {
  const trimmedUrl = String(rawUrl || '').trim()
  if (!trimmedUrl) return ''

  const hashIndex = trimmedUrl.indexOf('#')
  const baseUrl = hashIndex >= 0 ? trimmedUrl.slice(0, hashIndex) : trimmedUrl
  const hashPart = hashIndex >= 0 ? trimmedUrl.slice(hashIndex + 1) : ''
  const params = new URLSearchParams(hashPart)

  if (!params.get('theme')) {
    params.set('theme', 'night')
  }
  if (!params.get('bordered')) {
    params.set('bordered', 'true')
  }
  if (!params.get('titled')) {
    params.set('titled', 'true')
  }
  if (baseUrl.includes('/embed/dashboard/') && !params.get('background')) {
    params.set('background', 'false')
  }

  return `${baseUrl}#${params.toString()}`
}
