const valid = (value, choices, fallback = '') =>
  choices.includes(value) ? value : fallback

export function initialFilters() {
  const params = new URLSearchParams(window.location.search)
  return {
    search: params.get('q') || '',
    category: valid(params.get('category'), ['grocery', 'restaurant']),
    type: valid(params.get('type'), ['recall', 'outbreak']),
    status: valid(params.get('status'), ['active', 'resolved', ''], 'active'),
  }
}

export function rememberFilters({ search, category, type, status }) {
  const params = new URLSearchParams()
  if (search) params.set('q', search)
  if (category) params.set('category', category)
  if (type) params.set('type', type)
  if (status !== 'active') params.set('status', status)
  const query = params.size ? `?${params}` : ''
  window.history.replaceState(null, '', `/${query}${window.location.hash}`)
  try {
    sessionStorage.setItem('recallradar:feed', query)
  } catch {
    /* Storage is optional. */
  }
}

export function feedReturnUrl() {
  try {
    const query = sessionStorage.getItem('recallradar:feed') || ''
    return `/${query.startsWith('?') ? query : ''}#advisories`
  } catch {
    return '/#advisories'
  }
}
