const AGENCY_LABELS = {
  FDA: 'U.S. Food & Drug Administration',
  'USDA-FSIS': 'USDA Food Safety and Inspection Service',
  CDC: 'Centers for Disease Control and Prevention',
}

function formatDate(iso) {
  if (!iso) return ''
  // Parsed as UTC so the displayed day matches the stored ISO date regardless
  // of the viewer's timezone.
  const date = new Date(`${iso}T00:00:00Z`)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    timeZone: 'UTC',
  })
}

export default function AdvisoryCard({ advisory }) {
  const isOutbreak = advisory.type === 'outbreak'

  return (
    <article className={`card card--${advisory.type}`}>
      <div className="card__tags">
        <span className={`tag tag--${advisory.type}`}>
          {isOutbreak ? 'Outbreak investigation' : 'Recall'}
        </span>
        <span className="tag tag--category">{advisory.category}</span>
        {advisory.severity && <span className="tag tag--severity">{advisory.severity}</span>}
        <span className={`tag tag--status tag--${advisory.status}`}>{advisory.status}</span>
      </div>

      <h2 className="card__title">{advisory.brand_or_chain}</h2>
      <p className="card__reason">{advisory.reason}</p>
      <p className="card__description">{advisory.description}</p>

      <dl className="card__meta">
        <div>
          <dt>Published</dt>
          <dd>{formatDate(advisory.started_at)}</dd>
        </div>
        {advisory.updated_at !== advisory.started_at && (
          <div>
            <dt>Updated</dt>
            <dd>{formatDate(advisory.updated_at)}</dd>
          </div>
        )}
        <div>
          <dt>States</dt>
          <dd>
            {advisory.states_affected.length
              ? advisory.states_affected.join(', ')
              : 'Not specified / national'}
          </dd>
        </div>
      </dl>

      {/*
        Required by the compliance constraint: every card attributes its source
        agency and links to that agency's original record. RecallRadar presents
        the record; it does not issue the advisory.
      */}
      <footer className="card__source">
        <span className="card__agency" title={AGENCY_LABELS[advisory.source_agency] || ''}>
          Source: {advisory.source_agency}
        </span>
        <a href={advisory.source_url} target="_blank" rel="noopener noreferrer">
          View the original {advisory.source_agency} record →
        </a>
      </footer>
    </article>
  )
}
