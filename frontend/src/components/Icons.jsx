/**
 * Inline SVG icons.
 *
 * Kept inline (rather than an icon package) so the bundle stays dependency-free
 * and every glyph inherits `currentColor` from its container. All are drawn on a
 * 24x24 grid with a 1.75 stroke so they stay legible at the 14–16px sizes used
 * in card metadata.
 */

const base = {
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.75,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
  'aria-hidden': 'true',
  focusable: 'false',
}

export function SearchIcon(props) {
  return (
    <svg {...base} {...props}>
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-3.5-3.5" />
    </svg>
  )
}

export function CalendarIcon(props) {
  return (
    <svg {...base} {...props}>
      <rect x="3" y="5" width="18" height="16" rx="2" />
      <path d="M8 3v4M16 3v4M3 10h18" />
    </svg>
  )
}

export function UsersIcon(props) {
  return (
    <svg {...base} {...props}>
      <path d="M16 20v-1a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4v1" />
      <circle cx="9.5" cy="7" r="3.5" />
      <path d="M21 20v-1a4 4 0 0 0-3-3.87" />
      <path d="M16.5 3.6a4 4 0 0 1 0 6.8" />
    </svg>
  )
}

export function MapPinIcon(props) {
  return (
    <svg {...base} {...props}>
      <path d="M20 10.5c0 5.2-8 11-8 11s-8-5.8-8-11a8 8 0 0 1 16 0Z" />
      <circle cx="12" cy="10.5" r="2.75" />
    </svg>
  )
}

export function ExternalLinkIcon(props) {
  return (
    <svg {...base} {...props}>
      <path d="M14 4h6v6" />
      <path d="M20 4 11 13" />
      <path d="M18 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4" />
    </svg>
  )
}

export function EmptyIcon(props) {
  return (
    <svg {...base} {...props}>
      <circle cx="11" cy="11" r="7.5" />
      <path d="m20.5 20.5-4-4" />
      <path d="M8.5 11h5" />
    </svg>
  )
}
