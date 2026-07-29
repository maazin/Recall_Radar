import { useCallback, useEffect, useState } from 'react'
import { fetchAdvisories, fetchConfig, fetchStats } from './api'
import AdvisoryCard from './components/AdvisoryCard'
import SubscribeForm from './components/SubscribeForm'
import { EmptyIcon, SearchIcon } from './components/Icons'
import Logo from './components/Logo'

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
  // How many advisories the same filters would return with the status cleared.
  const [otherStatusTotal, setOtherStatusTotal] = useState(0)
  // Whether this deployment has a mail provider. Defaults to false so the
  // subscribe form is never shown before the answer is known.
  const [notificationsEnabled, setNotificationsEnabled] = useState(false)

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
          })
          setOtherStatusTotal(wider.total)
        } else if (!append) {
          setOtherStatusTotal(0)
        }
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

  const hasMore = items.length < total
  const filtersActive = Boolean(search || category || type) || status !== 'active'
  const showEmpty = !loading && !error && items.length === 0

  return (
    <div className="page">
      <div className="masthead-rule" aria-hidden="true" />

      <nav className="navbar">
        <div className="navbar__inner">
          <a className="brand" href="/">
            <span className="brand__mark">
              <Logo size={30} />
            </span>
            <span className="brand__text">
              <span className="brand__name">RecallRadar</span>
              <span className="brand__tag">Food safety registry</span>
            </span>
          </a>

          <span className="livepill" title="Indexed from official agency sources">
            <span className="livepill__dot" aria-hidden="true" />
            FDA / USDA / CDC Live Data
          </span>
        </div>
      </nav>

      <header className="hero">
        <div className="shell">
          <p className="eyebrow hero__eyebrow">Updated continuously from federal sources</p>
          <h1 className="hero__title">
            Food recalls and outbreak investigations, in one place
          </h1>
          <p className="hero__lede">
            Records published by the FDA, USDA/FSIS and CDC: what to avoid, why, and
            where, in plain language.
          </p>

          {/*
            Compliance: state plainly what this site is. RecallRadar aggregates and
            links to published agency records; it is not an alerting authority and
            must not be read as issuing one.
          */}
          <p className="notice">
            RecallRadar is an independent aggregator. It does not issue health alerts.
            Every entry links to the original agency record. Always read that record
            for authoritative details.
          </p>

          <div className="ledger">
            <LedgerColumn
              tone="active"
              label="Active"
              value={stats?.active}
              caption="currently open"
            />
            <LedgerColumn
              tone="recall"
              label="Recalls"
              value={stats?.recalls}
              caption="FDA & USDA/FSIS"
            />
            <LedgerColumn
              tone="outbreak"
              label="Outbreaks"
              value={stats?.outbreaks}
              caption="CDC & FDA investigations"
            />
          </div>
        </div>
      </header>

      <div className="toolbar">
        <div className="shell toolbar__inner">
          <form className="searchfield" onSubmit={handleSearchSubmit} role="search">
            <SearchIcon className="searchfield__icon" width="17" height="17" />
            <input
              type="search"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder="Search a brand or chain (e.g. Chipotle, Acme Foods)"
              aria-label="Search by brand or chain"
            />
            <button type="submit" className="btn btn--primary searchfield__go">
              Search
            </button>
          </form>

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
              label="Type"
              value={type}
              onChange={setType}
              options={[
                ['', 'All types'],
                ['recall', 'Recalls'],
                ['outbreak', 'Outbreaks'],
              ]}
            />
            <Select
              label="Status"
              value={status}
              onChange={setStatus}
              options={[
                ['active', 'Active'],
                ['resolved', 'Resolved'],
                ['', 'Any status'],
              ]}
            />
            {filtersActive && (
              <button type="button" className="btn btn--ghost" onClick={resetFilters}>
                Reset
              </button>
            )}
          </div>
        </div>
      </div>

      <main className="shell content">
        <p className="resultline" role="status">
          {loading && items.length === 0 ? (
            'Loading advisories…'
          ) : (
            <>
              <strong>{total.toLocaleString()}</strong>
              {total === 1 ? ' advisory' : ' advisories'}
              {search && (
                <>
                  {' '}
                  matching brand <strong>“{search}”</strong>
                </>
              )}
            </>
          )}
        </p>

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
                ? `No brand or chain matching “${search}” has a record under the current filters.`
                : 'Nothing is indexed under this combination of filters right now.'}
            </p>

            {otherStatusTotal > 0 && (
              <p className="panel__hint">
                {otherStatusTotal === 1
                  ? 'There is 1 matching advisory'
                  : `There are ${otherStatusTotal.toLocaleString()} matching advisories`}{' '}
                under a different status. Most restaurant outbreaks CDC publishes
                are closed investigations.
              </p>
            )}

            <div className="panel__actions">
              {otherStatusTotal > 0 && (
                <button className="btn btn--primary" onClick={() => setStatus('')}>
                  Show any status
                </button>
              )}
              {filtersActive && (
                <button
                  className={otherStatusTotal > 0 ? 'btn btn--secondary' : 'btn btn--primary'}
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
            {loading ? 'Loading…' : `Load ${Math.min(PAGE_SIZE, total - items.length)} more`}
          </button>
        )}

        {/* Only offered when the deployment can actually send. */}
        {notificationsEnabled && <SubscribeForm />}
      </main>

      <footer className="sitefoot">
        <div className="shell">
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
          <p className="sitefoot__fine">
            RecallRadar is not affiliated with the FDA, USDA or CDC and does not issue
            health alerts. Refer to the linked agency record in every case.
          </p>
        </div>
      </footer>
    </div>
  )
}

function LedgerColumn({ tone, label, value, caption }) {
  return (
    <div className={`ledger__col ledger__col--${tone}`}>
      <div className="ledger__head">
        <span className="ledger__chip" aria-hidden="true" />
        <span className="eyebrow ledger__label">{label}</span>
      </div>
      <span className="ledger__value">
        {value === undefined || value === null ? '—' : value.toLocaleString()}
      </span>
      <span className="ledger__caption">{caption}</span>
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
