/** Inline SVG product art: crisp at any DPI, ~1 KB, zero extra requests. */
export function PhoneArt() {
  return (
    <svg className="phone-art" viewBox="0 0 220 420" role="img" aria-label="Nova X Pro smartphone">
      <defs>
        <linearGradient id="pa-body" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#3a3358" />
          <stop offset="1" stopColor="#15121f" />
        </linearGradient>
        <linearGradient id="pa-screen" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#ffb547" />
          <stop offset="0.5" stopColor="#ff3d81" />
          <stop offset="1" stopColor="#6a5cff" />
        </linearGradient>
      </defs>
      <rect x="10" y="6" width="200" height="408" rx="34" fill="url(#pa-body)" />
      <rect x="20" y="16" width="180" height="388" rx="26" fill="url(#pa-screen)" />
      <rect x="85" y="28" width="50" height="14" rx="7" fill="#0c0a14" />
      <path d="M118 150 84 214h28l-8 56 40-74h-30z" fill="#fff" opacity="0.92" />
      <text x="110" y="320" textAnchor="middle" fill="#fff" fontSize="18" fontWeight="700">
        NOVA X PRO
      </text>
    </svg>
  )
}
