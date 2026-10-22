const BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

async function request(path, params = {}, options = {}) {
  const url = new URL(`${BASE_URL}${path}`)
  Object.entries(params).forEach(([key, value]) => {
    if (value !== null && value !== undefined && value !== '') {
      url.searchParams.set(key, value)
    }
  })

  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 60000)
  const abort = () => controller.abort()
  options.signal?.addEventListener('abort', abort, { once: true })
  let response
  try {
    if (options.signal?.aborted) controller.abort()
    response = await fetch(url, { ...options, signal: controller.signal })
    if (!response.ok) {
      let detail = `Request failed (${response.status})`
      try {
        const body = await response.json()
        if (typeof body.detail === 'string') detail = body.detail
      } catch { /* Keep the status message for non-JSON responses. */ }
      throw new Error(detail)
    }
    return await response.json()
  } catch (error) {
    if (controller.signal.aborted && !options.signal?.aborted) {
      throw new Error('The server took too long to respond. Please try again.')
    }
    throw error
  } finally {
    clearTimeout(timeout)
    options.signal?.removeEventListener('abort', abort)
  }
}

/** Product, firm and hazard search; empty filters are omitted by request(). */
export function fetchAdvisories({ category, type, status, search, limit = 50, offset = 0, signal }) {
  return request('/api/advisories', { category, type, status, q: search, limit, offset }, { signal })
}

export function fetchAdvisory(id, signal) {
  return request(`/api/advisories/${encodeURIComponent(id)}`, {}, { signal })
}

export function fetchSources(signal) {
  return request('/api/sources', {}, { signal })
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
