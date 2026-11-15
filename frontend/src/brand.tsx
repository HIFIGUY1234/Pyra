/* PyroScope identity mark: a polar-orbit ground track crossing a detected fire pixel. */
export function BrandMark({ size = 32 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" focusable="false">
      <rect x="0.5" y="0.5" width="31" height="31" rx="5" fill="#0f1726" stroke="#2a3a55" />
      <ellipse cx="16" cy="16" rx="12" ry="5.2" transform="rotate(-28 16 16)" fill="none" stroke="#5b7aa6" strokeWidth="1.1" />
      <rect x="13" y="13" width="6" height="6" fill="#f0782d" />
      <rect x="13" y="13" width="6" height="6" fill="none" stroke="#ffb27a" strokeWidth="0.8" />
      <circle cx="25.2" cy="10.4" r="1.7" fill="#cbd5e1" />
    </svg>
  )
}

export function BrandLockup({ subtitle = 'Satellite Fire Intelligence' }: { subtitle?: string }) {
  return (
    <div className="flex items-center gap-2.5">
      <BrandMark />
      <div className="leading-tight">
        <div className="text-[15px] font-semibold tracking-tight text-white">PyroScope</div>
        <div className="text-[11px] text-slate-400">{subtitle}</div>
      </div>
    </div>
  )
}
