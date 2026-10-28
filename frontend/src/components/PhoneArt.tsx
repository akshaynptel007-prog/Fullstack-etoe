/** Inline SVG product art: crisp at any DPI, ~1 KB, zero extra requests. */
export function PhoneArt() {
  return (
    <svg className="phone-art" viewBox="0 0 220 420" role="img" aria-label="Nova X Pro smartphone">
      <defs>
        <linearGradient id="pa-body" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#64748b" />
          <stop offset="0.45" stopColor="#334155" />
          <stop offset="1" stopColor="#172033" />
        </linearGradient>
        <linearGradient id="pa-screen" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#edf6fb" />
          <stop offset="0.58" stopColor="#bfd9e9" />
          <stop offset="1" stopColor="#78a9c5" />
        </linearGradient>
        <linearGradient id="pa-accent" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#397f9d" />
          <stop offset="1" stopColor="#72b9bd" />
        </linearGradient>
      </defs>
      <rect x="10" y="6" width="200" height="408" rx="34" fill="url(#pa-body)" />
      <rect x="20" y="16" width="180" height="388" rx="26" fill="url(#pa-screen)" />
      <rect x="85" y="28" width="50" height="14" rx="7" fill="#182433" />
      <circle cx="110" cy="170" r="68" fill="url(#pa-accent)" opacity="0.92" />
      <circle cx="145" cy="145" r="27" fill="#fff" opacity="0.22" />
      <path d="M44 264c35-35 97-35 132 0v78H44z" fill="#fff" opacity="0.33" />
      <text x="110" y="319" textAnchor="middle" fill="#173044" fontSize="17" fontWeight="700">
        NOVA X PRO
      </text>
    </svg>
  )
}
