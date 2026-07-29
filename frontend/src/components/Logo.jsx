/**
 * The RecallRadar mark: a grocery bag carrying an exclamation point.
 *
 * Redrawn as vector rather than dropping in logo.png, because the source
 * artwork is a 1600px app icon with a white tile and drop shadow baked in —
 * that tile reads as a floating white square against the navbar, and the raster
 * softens badly at 30px. The PNG still ships as the favicon and
 * apple-touch-icon, where the tile is exactly what's wanted.
 *
 * Geometry and colour are measured from the artwork rather than eyeballed. The
 * source mark occupies 734x838px; that is mapped onto a square 32-unit viewBox
 * at 27 units tall and centred, so `size` stays a single number at call sites.
 * Notable measurements preserved: the bag is taller than it is wide, its sides
 * flare only slightly (about 1 unit over its full height), and the front panel
 * has vertical sides so the darker gussets widen toward the base.
 */

export const BRAND_TEAL = '#12c6b2'
export const BRAND_TEAL_DEEP = '#01ac9b'
export const BRAND_CORAL = '#ff6e5b'

export default function Logo({ size = 30, ...props }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      role="img"
      aria-label="RecallRadar"
      {...props}
    >
      {/* Handles: semicircles of radius 3.09 with short legs tucked behind
          the bag's top edge at y=8.75. */}
      <g stroke={BRAND_TEAL} strokeWidth="2.32" fill="none">
        <path d="M6.64 9.2V6.75a3.09 3.09 0 0 1 6.18 0V9.2" />
        <path d="M19.2 9.2V6.75a3.09 3.09 0 0 1 6.18 0V9.2" />
      </g>

      {/* Full silhouette, in the deeper teal — visible as the side gussets. */}
      <path
        fill={BRAND_TEAL_DEEP}
        d="M5.4 8.75h21.23l1.16 17.85a2.9 2.9 0 0 1-2.9 2.9H7.14a2.9 2.9 0 0 1-2.9-2.9Z"
      />

      {/* Lit front panel: vertical sides, so the gussets widen toward the base
          exactly as they do in the artwork. */}
      <path
        fill={BRAND_TEAL}
        d="M7.56 8.75h16.85V26.9a2.6 2.6 0 0 1-2.6 2.6H10.16a2.6 2.6 0 0 1-2.6-2.6Z"
      />

      {/* The alert: a teardrop bar tapering from its widest at y=14.3, and a
          separate dot. */}
      <path
        fill={BRAND_CORAL}
        d="M16 11.97c1.42 0 2.02.98 1.88 2.33l-.86 6.05c-.07.8-.42 1.15-1.02 1.15s-.95-.35-1.02-1.15l-.86-6.05c-.14-1.35.46-2.33 1.88-2.33Z"
      />
      <circle fill={BRAND_CORAL} cx="16" cy="24.28" r="1.69" />
    </svg>
  )
}
