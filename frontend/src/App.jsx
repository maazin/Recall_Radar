import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchAdvisories, fetchConfig, fetchStats } from './api'
import AdvisoryCard from './components/AdvisoryCard'
import SubscribeForm from './components/SubscribeForm'
import { EmptyIcon, SearchIcon } from './components/Icons'
import SourceCoverage from './components/SourceCoverage'
import AdvisoryDetail from './components/AdvisoryDetail'
import Logo from './components/Logo'
import { initialFilters, rememberFilters } from './utils/feedState'

const PAGE_SIZE = 30

export default function App() {
  if (window.location.pathname.startsWith('/advisories/')) {
    const match = /^\/advisories\/(\d+)\/?$/.exec(window.location.pathname)
    return <AdvisoryDetail id={match?.[1]} />
  }
  return <Feed />
}

function Feed() {
  const requestRef = useRef(null)
  const [initial] = useState(initialFilters)
  const [searchInput, setSearchInput] = useState(initial.search)
  const [search, setSearch] = useState(initial.search)
  const [category, setCategory] = useState(initial.category)
  const [type, setType] = useState(initial.type)

  const [status, setStatus] = useState(initial.status)

  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [stats, setStats] = useState(null)
  // How many advisories the same filters would return with the status cleared.
  const [otherStatusTotal, setOtherStatusTotal] = useState(0)
  // Whether this deployment has a mail provider. Defaults to false so the
  // subscribe form is never shown before the answer is known.
  const [notificationsEnabled, setNotificationsEnabled] = useState(false)

  const load = useCallback(
    async (nextOffset, { append = false } = {}) => {
      requestRef.current?.abort()
      const controller = new AbortController()
      requestRef.current = controller
      const signal = controller.signal
      setLoading(true)
      setError('')
      if (!append) {
        setItems([])
        setOtherStatusTotal(0)
      }
      try {
        const data = await fetchAdvisories({
          category,
          type,
          status,
          search,
          limit: PAGE_SIZE,
          offset: nextOffset,
          signal,
        })
        if (signal?.aborted) return
        setTotal(data.total)
        setOffset(nextOffset)
        setItems((current) =>
          append ? [...current, ...data.items] : data.items,
        )

        // Nothing matched, but the status filter may be what's hiding it. Most
        // of the restaurant advisories CDC publishes are closed investigations,
        // so filtering to Restaurant while Active is selected looks empty even
        // though there is real history to read. Probe without the status and
        // offer the wider result rather than leaving a dead end.
        if (!append && data.total === 0 && status) {
          const wider = await fetchAdvisories({
            category,
            type,
            status: '',
            search,
            limit: 1,
            offset: 0,
            signal,
          })
          if (!signal?.aborted) setOtherStatusTotal(wider.total)
        } else if (!append) {
          setOtherStatusTotal(0)
        }
      } catch (err) {
        if (signal?.aborted) return
        setError(err.message)
        if (!append) setItems([])
      } finally {
        if (!signal?.aborted) setLoading(false)
      }
    },
    [category, type, status, search],
  )

  useEffect(() => {
    rememberFilters({ search, category, type, status })
  }, [search, category, type, status])

  // Re-query from the first page whenever a filter or the search term changes.
  useEffect(() => {
    load(0)
    return () => requestRef.current?.abort()
  }, [load])

  useEffect(() => {
    fetchStats()
      .then(setStats)
      .catch(() => setStats(null))

    fetchConfig()
      .then((c) => setNotificationsEnabled(Boolean(c.notifications_enabled)))
      .catch(() => setNotificationsEnabled(false))
  }, [])

  function handleSearchSubmit(event) {
    event.preventDefault()
    setSearch(searchInput.trim())
  }

  function resetFilters() {
    setSearchInput('')
    setSearch('')
    setCategory('')
    setType('')
    setStatus('active')
  }

  const hasMore = items.length > 0 && items.length < total
  const filtersActive =
    Boolean(search || category || type) || status !== 'active'
  const showEmpty = !loading && !error && items.length === 0

  return (
    <div className="page">
      <a className="skip-link" href="#advisories">
        Skip to advisories
      </a>

      <nav className="navbar" aria-label="Main navigation">
        <div className="navbar__inner">
          <a className="brand" href="/">
            <span className="brand__mark">
              <Logo size={30} />
            </span>
            <span className="brand__text">
              <span className="brand__name">RecallRadar</span>
              <span className="brand__tag">Food safety records</span>
            </span>
          </a>

          <div className="navlinks">
            <a href="#advisories">Browse</a>
            <a
              href="#coverage"
              onClick={() => {
                document.getElementById('coverage').open = true
              }}
            >
              Source coverage
            </a>
          </div>
        </div>
      </nav>

      <main className="shell content" id="advisories">
        <header className="page-heading">
          <h1>Food recalls & outbreaks</h1>
          <p>Search records published by the FDA, USDA and CDC.</p>
          {stats && (
            <p className="index-summary">
              {stats.active.toLocaleString()} active records{' '}
              <span aria-hidden="true">·</span> {stats.total.toLocaleString()}{' '}
              indexed
            </p>
          )}
        </header>
        <section className="filter-panel" aria-label="Search and filters">
          <form
            className="searchfield"
            onSubmit={handleSearchSubmit}
            role="search"
          >
            <label className="sr-only" htmlFor="record-search">
              Search products, brands and hazards
            </label>
            <SearchIcon width="19" height="19" />
            <input
              id="record-search"
              type="search"
              value={searchInput}
              onChange={(e) => {
                setSearchInput(e.target.value)
                if (!e.target.value) setSearch('')
              }}
              placeholder="Product, company or hazard"
            />
            <button type="submit" className="btn btn--primary">
              Search
            </button>
          </form>
          <div className="filter-row">
            <div
              className="status-filter"
              role="group"
              aria-label="Record status"
            >
              {[
                ['active', 'Active'],
                ['resolved', 'Resolved'],
                ['', 'All statuses'],
              ].map(([value, label]) => (
                <button
                  key={label}
                  type="button"
                  aria-pressed={status === value}
                  onClick={() => setStatus(value)}
                >
                  {label}
                </button>
              ))}
            </div>
            <div className="selects">
              <Select
                label="Category"
                value={category}
                onChange={setCategory}
                options={[
                  ['', 'All categories'],
                  ['grocery', 'Grocery'],
                  ['restaurant', 'Restaurant'],
                ]}
              />
              <Select
                label="Record type"
                value={type}
                onChange={setType}
                options={[
                  ['', 'All types'],
                  ['recall', 'Recalls'],
                  ['outbreak', 'Outbreaks'],
                ]}
              />
            </div>
          </div>
          {filtersActive && (
            <div className="applied-filters" aria-label="Applied filters">
              {search && (
                <button
                  onClick={() => {
                    setSearch('')
                    setSearchInput('')
                  }}
                  aria-label={`Remove search for ${search}`}
                >
                  “{search}” <span aria-hidden="true">×</span>
                </button>
              )}
              {category && (
                <button
                  onClick={() => setCategory('')}
                  aria-label="Remove category filter"
                >
                  {category === 'grocery' ? 'Grocery' : 'Restaurant'}{' '}
                  <span aria-hidden="true">×</span>
                </button>
              )}
              {type && (
                <button
                  onClick={() => setType('')}
                  aria-label="Remove record type filter"
                >
                  {type === 'recall' ? 'Recalls' : 'Outbreaks'}{' '}
                  <span aria-hidden="true">×</span>
                </button>
              )}
              <button className="reset-filters" onClick={resetFilters}>
                Reset filters
              </button>
            </div>
          )}
        </section>
        <SourceCoverage />
        <div className="feed-column" aria-busy={loading}>
          <div className="results-heading">
            <p className="resultline" role="status">
              {loading && items.length === 0 ? (
                'Loading advisories…'
              ) : error ? (
                'Advisories unavailable'
              ) : (
                <>
                  <strong>{total.toLocaleString()}</strong>
                  {total === 1 ? ' advisory' : ' advisories'}
                  {search && (
                    <>
                      {' '}
                      matching <strong>“{search}”</strong>
                    </>
                  )}
                </>
              )}
            </p>
            <span className="sort-note">Newest first</span>
          </div>

          {error && (
            <div className="panel panel--error" role="alert">
              <h2>Could not load advisories</h2>
              <p>{error}</p>
              <button className="btn btn--secondary" onClick={() => load(0)}>
                Try again
              </button>
            </div>
          )}

          {loading && items.length === 0 && !error && (
            <div className="feed" aria-hidden="true">
              {[0, 1, 2].map((n) => (
                <div className="skeleton" key={n} />
              ))}
            </div>
          )}

          {showEmpty && (
            <div className="panel panel--empty">
              <span className="panel__icon" aria-hidden="true">
                <EmptyIcon width="26" height="26" />
              </span>
              <h2>No advisories match these filters</h2>
              <p>
                {search
                  ? `No product, brand or hazard matching “${search}” has a record under the current filters.`
                  : 'Nothing is indexed under this combination of filters right now.'}
              </p>

              {otherStatusTotal > 0 && (
                <p className="panel__hint">
                  {otherStatusTotal === 1
                    ? 'There is 1 matching advisory'
                    : `There are ${otherStatusTotal.toLocaleString()} matching advisories`}{' '}
                  under a different status. Most restaurant outbreaks CDC
                  publishes are closed investigations.
                </p>
              )}

              <div className="panel__actions">
                {otherStatusTotal > 0 && (
                  <button
                    className="btn btn--primary"
                    onClick={() => setStatus('')}
                  >
                    Show any status
                  </button>
                )}
                {filtersActive && (
                  <button
                    className={
                      otherStatusTotal > 0
                        ? 'btn btn--secondary'
                        : 'btn btn--primary'
                    }
                    onClick={resetFilters}
                  >
                    Reset filters
                  </button>
                )}
              </div>
            </div>
          )}

          {items.length > 0 && (
            <div className="feed">
              {items.map((advisory) => (
                <AdvisoryCard key={advisory.id} advisory={advisory} />
              ))}
            </div>
          )}

          {hasMore && (
            <button
              className="btn btn--secondary loadmore"
              onClick={() => load(offset + PAGE_SIZE, { append: true })}
              disabled={loading}
            >
              {loading
                ? 'Loading…'
                : `Load ${Math.min(PAGE_SIZE, total - items.length)} more`}
            </button>
          )}
        </div>
        <p className="feed-note">
          RecallRadar is an independent index and does not issue health alerts.
          Check the original agency record for affected lots, distribution and
          instructions. No matching record does not establish that a product is
          safe.
        </p>
        {/* Only offered when the deployment can actually send. */}
        {notificationsEnabled && <SubscribeForm />}
      </main>

      <footer className="sitefoot" id="sources">
        <div className="shell">
          <p>
            Data indexed from{' '}
            <a
              href="https://open.fda.gov/apis/food/enforcement/"
              target="_blank"
              rel="noopener noreferrer"
            >
              openFDA Food Enforcement
            </a>
            ,{' '}
            <a
              href="https://www.fsis.usda.gov/recalls"
              target="_blank"
              rel="noopener noreferrer"
            >
              USDA/FSIS Recalls
            </a>
            ,{' '}
            <a
              href="https://www.cdc.gov/foodborne-outbreaks/outbreaks/index.html"
              target="_blank"
              rel="noopener noreferrer"
            >
              CDC Foodborne Outbreaks
            </a>{' '}
            and{' '}
            <a
              href="https://www.fda.gov/food/outbreaks-foodborne-illness/investigations-foodborne-illness-outbreaks"
              target="_blank"
              rel="noopener noreferrer"
            >
              FDA Outbreak Investigations
            </a>
            .
          </p>
          <p className="sitefoot__fine">
            RecallRadar is not affiliated with the FDA, USDA or CDC and does not
            issue health alerts. Refer to the linked agency record in every
            case.
          </p>
        </div>
      </footer>
    </div>
  )
}

function Select({ label, value, onChange, options }) {
  return (
    <label className="select">
      <span className="select__label">{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        {options.map(([optionValue, optionLabel]) => (
          <option key={optionValue || 'any'} value={optionValue}>
            {optionLabel}
          </option>
        ))}
      </select>
    </label>
  )
}
