import Link from "next/link";
import { Building2, FileCheck2, ShieldCheck, Truck } from "lucide-react";
import { BrandMark } from "@/components/layout/brand-mark";
import { MotionToggle } from "@/components/motion/motion-toggle";

export function AuthShell({ eyebrow, title, description, children, footer }: {
  eyebrow: string; title: string; description: string; children: React.ReactNode; footer: React.ReactNode;
}) {
  return <main id="main-content" className="grid min-h-screen bg-[#f8f6fb] lg:grid-cols-[.95fr_1.05fr]">
    <aside className="auth-aside relative hidden flex-col justify-between overflow-hidden px-12 py-10 text-white lg:flex xl:px-20">
      <Link href="/" className="relative z-10 flex items-center gap-3 font-display text-lg font-semibold"><BrandMark className="size-10 shrink-0" />MedWaste <span className="-ml-2 text-[#d0b6e8]">AI</span></Link>
      <div className="relative z-10 max-w-md py-14 hero-enter"><p className="text-[10px] font-semibold uppercase tracking-[.2em] text-[#d4b695]">Connected healthcare operations</p><h2 className="mt-6 font-display text-5xl font-medium leading-[1.12] tracking-[-.045em] xl:text-[56px]">A clearer record.<br /><span className="text-[#c9a9df]">At every step.</span></h2><p className="mt-6 max-w-sm text-sm leading-7 text-[#beafca]">Bring reporting, collection, treatment and billing together in a workspace built around accountability.</p>
        <div className="auth-art max-w-sm" data-motion-art aria-hidden="true"><div className="auth-art-line" /><div className="auth-art-stages">{[{ icon: Building2, name: "Report" }, { icon: Truck, name: "Collect" }, { icon: FileCheck2, name: "Verify" }].map(({ icon: Icon, name }) => <div key={name}><Icon strokeWidth={1.5} /><span>{name}</span></div>)}</div></div>
        <div className="mt-6 flex max-w-sm items-center gap-4 rounded-2xl border border-white/10 bg-white/[.035] p-5"><ShieldCheck size={27} strokeWidth={1.25} className="shrink-0 text-[#c9a9df]" aria-hidden="true" /><p className="text-xs leading-6 text-[#d9cee0]">One chain of custody.<br /><span className="text-[#a999b5]">Evidence connected from start to finish.</span></p></div>
      </div>
      <p className="relative z-10 text-[10px] tracking-wide text-[#b19cbe]">MedWaste AI · Healthcare operations, connected</p>
      <div className="auth-orbit" aria-hidden="true" />
    </aside>
    <div className="auth-form-area flex flex-col items-center justify-center px-5 py-10 sm:px-10">
      <Link href="/" className="mb-8 flex items-center gap-2.5 font-display text-xl font-semibold text-charcoal lg:hidden"><BrandMark />MedWaste <span className="-ml-1 text-forest">AI</span></Link>
      <div className="auth-form-card page-enter w-full max-w-[470px]"><p className="eyebrow">{eyebrow}</p><h1 className="mt-3 font-display text-3xl font-semibold tracking-tight">{title}</h1><p className="mt-3 text-sm leading-6 text-slate">{description}</p><div className="mt-8">{children}</div><p className="mt-7 border-t border-mist-deep pt-6 text-center text-sm text-slate">{footer}</p></div>
      <p className="mt-7 flex items-center justify-center gap-2 text-[10px] text-slate"><ShieldCheck size={13} />Secure access to your organization’s workspace</p>
      <MotionToggle className="mt-4" />
    </div>
  </main>;
}
