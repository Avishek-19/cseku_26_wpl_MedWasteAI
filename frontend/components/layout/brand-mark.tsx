export function BrandMark({ className }: { className?: string }) {
  return <svg viewBox="0 0 40 40" fill="none" aria-hidden="true" className={className ?? "size-9 shrink-0"}>
    <rect width="40" height="40" rx="12" fill="#37234d" />
    <path d="M20 7.5c-2.5 3.3-9 9.8-9 15.1a9 9 0 0 0 18 0C29 17.3 22.5 10.8 20 7.5Z" fill="#d9c1ef" fillOpacity=".12" stroke="#dbc3ef" strokeWidth="1.5" />
    <path d="M15.5 23a4.5 4.5 0 0 0 4.5 4.5M17.5 18.5l2.5 2.5 4.5-5" stroke="#e3c29f" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
  </svg>;
}
