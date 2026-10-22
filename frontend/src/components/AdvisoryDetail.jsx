import { useEffect, useState } from 'react'
import { fetchAdvisory } from '../api'
import Logo from './Logo'
import { ExternalLinkIcon } from './Icons'

function Field({ label, children }) {
  return (
    <div className="detail__field">
      <dt>{label}</dt>
      <dd>
        {children ||
          'Not provided in the indexed record. Check the agency source.'}
      </dd>
    </div>
  )
}

export default function AdvisoryDetail({ id }) {
  const [advisory, setAdvisory] = useState(null)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)
  const [copied, setCopied] = useState('')
  useEffect(() => {
    const controller = new AbortController()
    setError('')
    if (!id) {
      setError('Advisory not found.')
      return () => controller.abort()
    }
    fetchAdvisory(id, controller.signal)
      .then(setAdvisory)
      .catch((err) => {
        if (!controller.signal.aborted) setError(err.message)
      })
    return () => controller.abort()
  }, [id, revision])
  useEffect(() => {
    const previous = document.title
    document.title = advisory
      ? `${advisory.brand_or_chain} — RecallRadar`
      : 'Advisory details — RecallRadar'
    return () => {
      document.title = previous
    }
  }, [advisory])

  async function copyLink() {
    try {
      await navigator.clipboard.writeText(window.location.href)
      setCopied('Link copied.')
    } catch {
      setCopied('Copy the address from your browser to share this record.')
    }
  }

  return (
    <div className="page">
      <nav className="navbar" aria-label="Main navigation">
        <div className="navbar__inner">
          <a className="brand" href="/">
            <Logo size={30} />
            <span className="brand__name">RecallRadar</span>
          </a>
          <a href="/#advisories">Browse advisories →</a>
        </div>
      </nav>
      <main className="shell detail">
        <a className="detail__back" href="/#advisories">
          ← Back to advisories
        </a>
        {error ? (
          <section className="panel panel--error" role="alert">
            <h1>Could not open this advisory</h1>
            <p>{error}</p>
            {id && (
              <button
                className="btn btn--secondary"
                onClick={() => setRevision((n) => n + 1)}
              >
                Try again
              </button>
            )}
          </section>
        ) : !advisory ? (
          <p role="status">Loading agency record…</p>
        ) : (
          <>
            <header className="detail__header">
              <div className="card__head">
                <span className={`badge badge--${advisory.type}`}>
                  {advisory.type === 'outbreak'
                    ? 'Outbreak investigation'
                    : 'Food recall'}
                </span>
                <span className="badge badge--resolved">
                  {advisory.status === 'resolved' ? 'Resolved' : 'Active'}
                </span>
                <span className="detail__agency">{advisory.source_agency}</span>
              </div>
              <h1>{advisory.brand_or_chain}</h1>
              <p className="detail__reason">{advisory.reason}</p>
              <div className="detail__actions">
                <a
                  className="btn btn--primary"
                  href={advisory.source_url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Read original agency record{' '}
                  <ExternalLinkIcon width="15" height="15" />
                </a>
                <button className="btn btn--secondary" onClick={copyLink}>
                  Copy share link
                </button>
                <span role="status">{copied}</span>
              </div>
            </header>
            <p className="notice detail__notice">
              RecallRadar is an independent aggregator and does not issue health
              alerts. Compare the exact product, lot codes and dates with the
              original agency record. A missing detail or search result does not
              establish that a product is safe.
            </p>
            <div className="detail__grid">
              <section className="detail__panel">
                <h2>
                  {advisory.type === 'outbreak'
                    ? 'Investigation details'
                    : 'Affected product details'}
                </h2>
                <dl>
                  <Field label="Product description">
                    {advisory.product_description}
                  </Field>
                  {advisory.type === 'recall' && (
                    <>
                      <Field label="Lot / batch codes">
                        {advisory.lot_codes}
                      </Field>
                      <Field label="Recall number">
                        {advisory.recall_number}
                      </Field>
                    </>
                  )}
                  <Field label="Distribution details">
                    {advisory.distribution_pattern}
                  </Field>
                  <Field label="States listed">
                    {advisory.states_affected.length
                      ? advisory.states_affected.join(', ')
                      : 'National or unspecified. Confirm distribution in the agency record.'}
                  </Field>
                </dl>
              </section>
              <section className="detail__panel">
                <h2>Record information</h2>
                <dl>
                  <Field label="Agency classification">
                    {advisory.severity}
                  </Field>
                  <Field label="Category">{advisory.category}</Field>
                  <Field label="Record start date">{advisory.started_at}</Field>
                  <Field label="Agency record updated">
                    {advisory.updated_at}
                  </Field>
                </dl>
                <p className="detail__fine">
                  Dates retain the precision provided by the source. Agency
                  record dates do not indicate when RecallRadar last fetched the
                  feed.
                </p>
              </section>
            </div>
            <section className="detail__panel detail__description">
              <h2>Published description</h2>
              <p>{advisory.description}</p>
            </section>
            <p className="detail__fine">
              Some details may be absent for older records until the source is
              fetched again. Always consult the linked agency record for
              complete information.
            </p>
          </>
        )}
      </main>
    </div>
  )
}
