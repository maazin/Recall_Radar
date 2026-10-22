import { useEffect, useState } from 'react'
import { fetchSources } from '../api'

const LABELS = {
  current: 'Fetched recently',
  delayed: 'Delayed',
  unavailable: 'Source unavailable',
  error: 'Refresh failed',
  unknown: 'Not yet tracked',
  updating: 'Updating',
}

function timestamp(value) {
  if (!value) return 'No successful fetch recorded'
  return new Date(value).toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    timeZoneName: 'short',
  })
}

export default function SourceCoverage() {
  const [data, setData] = useState(null)
  const [error, setError] = useState(false)
  const [revision, setRevision] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    setError(false)
    fetchSources(controller.signal)
      .then(setData)
      .catch(() => {
        if (!controller.signal.aborted) setError(true)
      })
    return () => controller.abort()
  }, [revision])
  useEffect(() => {
    const timer = setInterval(() => setRevision((n) => n + 1), 5 * 60 * 1000)
    return () => clearInterval(timer)
  }, [])

  return (
    <section
      className="coverage"
      id="coverage"
      aria-labelledby="coverage-title"
    >
      <p className="eyebrow">TRANSPARENT BY DESIGN</p>
      <h2 id="coverage-title">Sources & coverage</h2>
      <p>
        Scheduled daily. A recent fetch does not mean the agency published new
        records.
      </p>
      {error ? (
        <div role="status">
          <p>Coverage information could not be loaded.</p>
          <button
            className="btn btn--secondary"
            onClick={() => setRevision((n) => n + 1)}
          >
            Retry coverage
          </button>
        </div>
      ) : !data ? (
        <p role="status">Checking source coverage…</p>
      ) : (
        <>
          <ul className="coverage__list">
            {data.sources.map((source) => (
              <li key={source.key}>
                <a href={source.url} target="_blank" rel="noopener noreferrer">
                  {source.label} ↗
                </a>
                <span
                  className={`coverage__status coverage__status--${source.status}`}
                >
                  {LABELS[source.status] || 'Unknown'}
                </span>
                <span className="coverage__date">
                  Last success: {timestamp(source.last_success_at)}
                </span>
                <span className="coverage__count">
                  {source.record_count.toLocaleString()} indexed records
                </span>
              </li>
            ))}
          </ul>
          <p className="coverage__fine">
            Delayed means no successful refresh in {data.stale_after_hours}{' '}
            hours. Previously indexed records remain searchable when a source is
            unavailable.
          </p>
          <button
            className="coverage__refresh"
            onClick={() => setRevision((n) => n + 1)}
          >
            Refresh coverage
          </button>
        </>
      )}
    </section>
  )
}
