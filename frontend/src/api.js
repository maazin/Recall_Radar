const BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

async function request(path, params = {}, options = {}) {
  const url = new URL(`${BASE_URL}${path}`)
  Object.entries(params).forEach(([key, value]) => {
    if (value !== null && value !== undefined && value !== '') {
      url.searchParams.set(key, value)
    }
  })

  const response = await fetch(url, options)
  if (!response.ok) {
    let detail = `Request failed (${response.status})`
    try {
      const body = await response.json()
      if (body.detail) detail = typeof body.detail === 'string' ? body.detail : detail
    } catch {
      // Non-JSON error body; keep the status-based message.
    }
    throw new Error(detail)
  }
  return response.json()
}

/**
 * The unified feed. `search` is scoped to brand/chain names when set, which is
 * what the search box is for; the category and type filters apply either way.
 */
export function fetchAdvisories({ category, type, status, search, limit = 50, offset = 0 }) {
  if (search) {
    return request('/api/advisories/search', {
      q: search,
      category,
      type,
      status,
      limit,
      offset,
    })
  }
  return request('/api/advisories', { category, type, status, limit, offset })
}

export function fetchStats() {
  return request('/api/stats')
}

/**
 * What this deployment supports. Currently just whether a mail provider is
 * configured — the subscribe form is hidden when it is not, so the page never
 * asks for an address that could not be written to.
 */
export function fetchConfig() {
  return request('/api/config')
}

export function createSubscription({ email, categoryFilter, keywordFilter }) {
  return request(
    '/api/subscriptions',
    {},
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email,
        category_filter: categoryFilter || null,
        keyword_filter: keywordFilter || null,
      }),
    },
  )
}
