import { useCallback, useEffect, useState } from 'react'
import { fetchAdvisories, fetchStats } from './api'
import AdvisoryCard from './components/AdvisoryCard'
import SubscribeForm from './components/SubscribeForm'

const PAGE_SIZE = 30

export default function App() {
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState('')
  const [type, setType] = useState('')
  const [status, setStatus] = useState('active')

  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [stats, setStats] = useState(null)

  const load = useCallback(
    async (nextOffset, { append } = { append: false }) => {
      setLoading(true)
      setError('')
      try {
        const data = await fetchAdvisories({
          category,
          type,
          status,
          search,
          limit: PAGE_SIZE,
          offset: nextOffset,
        })
        setTotal(data.total)
        setOffset(nextOffset)
        setItems((current) => (append ? [...current, ...data.items] : data.items))
      } catch (err) {
        setError(err.message)
        if (!append) setItems([])
      } finally {
        setLoading(false)
      }
    },
    [category, type, status, search],
  )

  // Re-query from the first page whenever a filter or the search term changes.
  useEffect(() => {
    load(0, { append: false })
  }, [load])

  useEffect(() => {
    fetchStats()
      .then(setStats)
      .catch(() => setStats(null))
  }, [])

  function handleSearchSubmit(event) {
    event.preventDefault()
    setSearch(searchInput.trim())
  }

  function clearSearch() {
    setSearchInput('')
    setSearch('')
  }

  const hasMore = items.length < total

  return (
    <div className="page">
      <header className="masthead">
        <div className="masthead__inner">
          <h1>
            Recall<span>Radar</span>
          </h1>
          <p className="masthead__tagline">
            Food recalls and foodborne-illness outbreak investigations published by the
            FDA, USDA/FSIS and CDC — in one place, in plain language.
          </p>

          {/*
            Compliance: state plainly what this site is. RecallRadar aggregates and
            links to published agency records; it is not an alerting authority and
            must not be read as issuing one.
          */}
          <p className="masthead__disclaimer">
            RecallRadar is an independent aggregator. It does not issue health alerts.
            Every entry links to the original agency record — always read that record
            for authoritative details.
          </p>

          {stats && (
            <ul className="stats">
              <li>
                <strong>{stats.active}</strong> active
              </li>
              <li>
                <strong>{stats.recalls}</strong> recalls
              </li>
              <li>
                <strong>{stats.outbreaks}</strong> outbreak investigations
              </li>
            </ul>
          )}
        </div>
      </header>

      <main className="content">
        <section className="controls" aria-label="Search and filter">
          <form className="searchbar" onSubmit={handleSearchSubmit} role="search">
            <input
              type="search"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder="Search a brand or chain — e.g. Chipotle, Acme Foods"
              aria-label="Search by brand or chain"
            />
            <button type="submit">Search</button>
            {search && (
              <button type="button" className="btn-ghost" onClick={clearSearch}>
                Clear
              </button>
            )}
          </form>

          <div className="filters">
            <FilterGroup
              label="Category"
              value={category}
              onChange={setCategory}
              options={[
                ['', 'All'],
                ['grocery', 'Grocery'],
                ['restaurant', 'Restaurant'],
              ]}
            />
            <FilterGroup
              label="Type"
              value={type}
              onChange={setType}
              options={[
                ['', 'All'],
                ['recall', 'Recalls'],
                ['outbreak', 'Outbreaks'],
              ]}
            />
            <FilterGroup
              label="Status"
              value={status}
              onChange={setStatus}
              options={[
                ['active', 'Active'],
                ['resolved', 'Resolved'],
                ['', 'All'],
              ]}
            />
          </div>

          <p className="resultcount" role="status">
            {search && (
              <>
                Brand/chain search for <strong>{search}</strong> —{' '}
              </>
            )}
            {loading && items.length === 0 ? 'Loading…' : `${total} matching advisories`}
          </p>
        </section>

        {error && (
          <p className="error" role="alert">
            Could not load advisories: {error}
          </p>
        )}

        {!loading && !error && items.length === 0 && (
          <p className="empty">
            No advisories match these filters. Try clearing the search or widening the
            status filter.
          </p>
        )}

        <div className="feed">
          {items.map((advisory) => (
            <AdvisoryCard key={advisory.id} advisory={advisory} />
          ))}
        </div>

        {hasMore && (
          <button
            className="loadmore"
            onClick={() => load(offset + PAGE_SIZE, { append: true })}
            disabled={loading}
          >
            {loading ? 'Loading…' : `Load more (${total - items.length} remaining)`}
          </button>
        )}

        <SubscribeForm />
      </main>

      <footer className="sitefoot">
        <p>
          Data indexed from{' '}
          <a href="https://open.fda.gov/apis/food/enforcement/" target="_blank" rel="noopener noreferrer">
            openFDA Food Enforcement
          </a>
          ,{' '}
          <a href="https://www.fsis.usda.gov/recalls" target="_blank" rel="noopener noreferrer">
            USDA/FSIS Recalls
          </a>
          ,{' '}
          <a href="https://www.cdc.gov/foodborne-outbreaks/outbreaks/index.html" target="_blank" rel="noopener noreferrer">
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
        <p>
          RecallRadar is not affiliated with the FDA, USDA or CDC and does not issue
          health alerts. Refer to the linked agency record in every case.
        </p>
      </footer>
    </div>
  )
}

function FilterGroup({ label, value, onChange, options }) {
  return (
    <fieldset className="filtergroup">
      <legend>{label}</legend>
      {options.map(([optionValue, optionLabel]) => (
        <button
          key={optionValue || 'all'}
          type="button"
          className={`chip ${value === optionValue ? 'chip--on' : ''}`}
          aria-pressed={value === optionValue}
          onClick={() => onChange(optionValue)}
        >
          {optionLabel}
        </button>
      ))}
    </fieldset>
  )
}
