import Link from "next/link";

const COLUMNS = [
  {
    title: "Platform",
    links: [["Waste tracking", "/#solution"], ["Pickup scheduling", "/#lifecycle"], ["Smart matching", "/#solution"], ["Chain of custody", "/#trust"]],
  },
  {
    title: "Network",
    links: [["Treatment facilities", "/#network"], ["Hospitals", "/#network"], ["Collectors", "/#network"]],
  },
  {
    title: "Company",
    links: [["About", "/#solution"], ["Trust & security", "/#trust"], ["Get started", "/register"]],
  },
];

export function Footer() {
  return (
    <footer className="bg-charcoal-soft pt-16">
      <div className="mx-auto max-w-7xl px-6 lg:px-8">
        <div className="grid grid-cols-2 gap-10 pb-14 sm:grid-cols-4">
          <div className="col-span-2 sm:col-span-1">
            <span className="font-display text-[15px] font-semibold text-paper">
              MedWaste <span className="text-emerald-bright">AI</span>
            </span>
            <p className="mt-3 max-w-[220px] text-[13px] leading-relaxed text-mist-deep/80">
              One record for medical waste, from the bin to the certificate.
            </p>
          </div>
          {COLUMNS.map((col) => (
            <div key={col.title}>
              <h4 className="font-data text-[11px] font-medium uppercase tracking-[0.14em] text-mist-deep/60">
                {col.title}
              </h4>
              <ul className="mt-4 space-y-2.5">
                {col.links.map(([label, url]) => (
                  <li key={label}>
                    <Link
                      href={url}
                      className="text-[13.5px] text-mist-deep hover:text-paper transition-colors"
                    >
                      {label}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <div className="manifest-edge manifest-edge--dark flex flex-col items-center justify-between gap-3 py-6 text-[12.5px] text-mist-deep/60 sm:flex-row">
          <p>&copy; {new Date().getFullYear()} MedWaste AI. All rights reserved.</p>
          <p className="font-data">Healthcare operations, connected</p>
        </div>
      </div>
    </footer>
  );
}
