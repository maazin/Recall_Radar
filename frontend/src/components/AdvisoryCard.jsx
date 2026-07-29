import {
  CalendarIcon,
  ExternalLinkIcon,
  MapPinIcon,
  UsersIcon,
} from './Icons'

const AGENCY_LABELS = {
  FDA: 'U.S. Food & Drug Administration',
  'USDA-FSIS': 'USDA Food Safety and Inspection Service',
  CDC: 'Centers for Disease Control and Prevention',
}

// Agencies use several phrasings for "we don't know the food yet".
const UNIDENTIFIED = /^(not\s+yet\s+identified|not\s+identified|unknown|tbd|pending)$/i

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

/**
 * Pull the case count back out of an outbreak description.
 *
 * The outbreak ingesters compose descriptions like
 * "Product linked to illnesses: X. Total case count: 72." — the count is
 * structured data that currently only survives as prose. Reading it back here
 * keeps this change purely presentational; promoting `case_count` to a real
 * column is the better long-term fix.
 */
function extractCaseCount(description) {
  const match = /total case count:\s*([^.]+)\./i.exec(description || '')
  if (!match) return null

  const raw = match[1].trim()
  if (!raw || /^not/i.test(raw)) return null

  const digits = raw.replace(/,/g, '')
  return /^\d+$/.test(digits)
    ? `${Number(digits).toLocaleString()} ${Number(digits) === 1 ? 'case' : 'cases'}`
    : raw
}

/**
 * Decide what this card actually leads with.
 *
 * When the agency has not yet identified the product, the brand field carries a
 * placeholder rather than a name. Leading with "Not Yet Identified" tells the
 * reader nothing, so the pathogen becomes the headline and the unidentified
 * product is demoted to a badge.
 */
function deriveDisplay(advisory) {
  const productUnknown = UNIDENTIFIED.test((advisory.brand_or_chain || '').trim())

  const title = productUnknown ? advisory.reason : advisory.brand_or_chain
  const subtitle = productUnknown ? null : advisory.reason

  let body = advisory.description || ''
  if (advisory.type === 'outbreak') {
    // Both of these are shown elsewhere on the card now — as the title/badge and
    // as a metadata field — so leaving them in the prose just repeats them.
    body = body
      .replace(/product linked to illnesses:\s*[^.]*\.\s*/i, '')
      .replace(/total case count:\s*[^.]*\.\s*/i, '')
      .trim()
  }

  return { title, subtitle, body, productUnknown }
}

export default function AdvisoryCard({ advisory }) {
  const isOutbreak = advisory.type === 'outbreak'
  const isResolved = advisory.status === 'resolved'
  const { title, subtitle, body, productUnknown } = deriveDisplay(advisory)

  const caseCount = extractCaseCount(advisory.description)
  const states = advisory.states_affected.length
    ? advisory.states_affected.join(', ')
    : 'National / not specified'

  // One badge carries both type and severity, rather than a row of chips.
  const badgeLabel = [
    isOutbreak ? 'Outbreak investigation' : 'Recall',
    advisory.severity,
  ]
    .filter(Boolean)
    .join(' · ')

  return (
    <article className={`card card--${advisory.type}`}>
      <header className="card__head">
        <span className={`badge badge--${advisory.type}`}>{badgeLabel}</span>
        {productUnknown && (
          <span className="badge badge--pending">Product pending identification</span>
        )}
        {isResolved && <span className="badge badge--resolved">Resolved</span>}
      </header>

      <h2 className="card__title">{title}</h2>
      {subtitle && <p className="card__subtitle">{subtitle}</p>}
      {body && <p className="card__body">{body}</p>}

      <ul className="meta">
        <li className="meta__item">
          <CalendarIcon width="15" height="15" />
          <span>{formatDate(advisory.started_at)}</span>
        </li>
        {caseCount && (
          <li className="meta__item">
            <UsersIcon width="15" height="15" />
            <span>{caseCount}</span>
          </li>
        )}
        <li className="meta__item meta__item--states">
          <MapPinIcon width="15" height="15" />
          <span>{states}</span>
        </li>
      </ul>

      {/*
        Required by the compliance constraint: every card attributes its source
        agency and links to that agency's original record. RecallRadar presents
        the record; it does not issue the advisory.
      */}
      <footer className="card__foot">
        <span className="card__attribution">
          <span
            className={`dot dot--${advisory.status}`}
            title={isResolved ? 'Resolved' : 'Active'}
            aria-hidden="true"
          />
          <span title={AGENCY_LABELS[advisory.source_agency] || ''}>
            {advisory.source_agency}
          </span>
          <span className="card__sep" aria-hidden="true">
            ·
          </span>
          <span className="card__category">{advisory.category}</span>
        </span>

        <a
          className="btn btn--secondary"
          href={advisory.source_url}
          target="_blank"
          rel="noopener noreferrer"
        >
          View original {advisory.source_agency} record
          <ExternalLinkIcon width="14" height="14" />
        </a>
      </footer>
    </article>
  )
}
