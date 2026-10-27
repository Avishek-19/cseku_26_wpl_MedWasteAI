import Link from "next/link";
import { ArrowDown, ArrowRight, ArrowUpRight, Building2, Check, ClipboardCheck, FileCheck2, Fingerprint, Layers3, MapPinned, Network, ShieldCheck, Truck } from "lucide-react";
import { Footer } from "@/components/layout/footer";
import { Navbar } from "@/components/layout/navbar";
import { Button } from "@/components/ui/button";

const stages = [
  { icon: Building2, label: "Hospital", caption: "Report · classify · request pickup", tag: "Origin", number: "01" },
  { icon: Truck, label: "Collection team", caption: "Assign · collect · track transport", tag: "In transit", number: "02" },
  { icon: FileCheck2, label: "Treatment facility", caption: "Receive · process · submit proof", tag: "Destination", number: "03" },
];
const steps = [
  { icon: ClipboardCheck, title: "A better beginning.", label: "Report & classify", text: "Record each batch, attach evidence and confirm the handling it needs before collection.", number: "01" },
  { icon: Truck, title: "A coordinated journey.", label: "Collect & track", text: "Match a destination, assign a vehicle and keep the team connected from pickup to delivery.", number: "02" },
  { icon: FileCheck2, title: "A verifiable finish.", label: "Receive & verify", text: "Confirm the handover, document treatment and keep the proof with the original batch.", number: "03" },
];
const capabilities = [
  { icon: MapPinned, name: "Bring the operation into focus.", text: "Pickup windows, compatible destinations and vehicle capacity come together in one route planning workspace.", detail: "Dispatch & visibility" },
  { icon: Fingerprint, name: "Keep the context. At every step.", text: "Follow who reported, collected, received and processed a batch, with evidence connected to the same record.", detail: "Evidence & ownership" },
  { icon: Layers3, name: "Connect the work to the numbers.", text: "Bring agreed service rates and measured quantities into invoices, recycling allocations and verified payment records.", detail: "Billing & reconciliation" },
];
const roles = [
  { icon: Building2, title: "Hospitals", text: "Report waste, review classification, schedule pickups and track invoices.", tag: "Generate & oversee" },
  { icon: Truck, title: "Collection companies", text: "Manage vehicles, coordinate routes and record evidence at collection.", tag: "Collect & transport" },
  { icon: FileCheck2, title: "Treatment facilities", text: "Declare capabilities, receive matched batches and document processing.", tag: "Receive & process" },
];

export default function Home() {
  return <>
    <Navbar />
    <main id="main-content" className="flex-1">
      <section className="premium-hero">
        <div aria-hidden="true" className="hero-grid" />
        <div aria-hidden="true" className="hero-orbit" data-motion-art><span /><span /></div>
        <div className="relative mx-auto grid max-w-7xl gap-14 px-6 lg:grid-cols-[1.08fr_1fr] lg:items-center lg:gap-12 lg:px-8">
          <div className="hero-copy">
            <div className="hero-enter hero-kicker"><span />CONNECTED CARE. ACCOUNTABLE OPERATIONS.</div>
            <h1 className="hero-enter hero-title">Every batch.<br />Every handover.<br /><span>Accounted for.</span></h1>
            <p className="hero-enter hero-description">One considered workspace for healthcare waste. Connect your people, follow the journey and keep a clearer record of every decision.</p>
            <div className="hero-enter mt-9 flex flex-wrap gap-3">
              <Button asChild size="lg"><Link href="/register">Create your workspace<ArrowUpRight size={17} /></Link></Button>
              <Button asChild size="lg" variant="outline"><Link href="/login">Sign in<ArrowRight size={16} /></Link></Button>
            </div>
            <div className="hero-enter hero-assurances">{["Role-based access", "Connected evidence", "Verified payments"].map(text => <span key={text}><Check size={13} />{text}</span>)}</div>
            <a href="#lifecycle" className="hero-enter hero-scroll"><span><ArrowDown size={14} /></span>Explore the workflow</a>
          </div>
          <div className="hero-enter workflow-visual" data-motion-art aria-label="Workflow overview: hospital, collection team and treatment facility share one batch record.">
            <div className="workflow-frame">
              <div className="workflow-heading"><span><Network size={16} />Connected by design</span><span className="workflow-tag">The batch journey</span></div>
              <div className="workflow-stage-list">
                {stages.map(({ icon: Icon, label, caption, tag, number }, index) => <div key={label}>
                  <div className="workflow-stage" style={{ "--stage": index } as React.CSSProperties}>
                    <div className="workflow-icon"><Icon size={24} strokeWidth={1.5} /></div>
                    <div className="min-w-0"><p className="workflow-stage-tag">{tag}</p><p className="workflow-stage-label">{label}</p><p className="workflow-caption">{caption}</p></div>
                    <span className="workflow-number">{number}</span>
                  </div>
                  {index < stages.length - 1 && <div className="workflow-connector" aria-hidden="true"><span /><ArrowDown size={12} /></div>}
                </div>)}
              </div>
              <div className="workflow-record"><div className="workflow-record-icon"><ShieldCheck size={21} /></div><div><strong>One record. The complete journey.</strong><p>Clear ownership at every handover.</p></div><Check className="ml-auto shrink-0 text-[#d5b893]" size={16} /></div>
            </div>
            <div className="workflow-note"><span className="workflow-note-mark"><Fingerprint size={22} strokeWidth={1.5} /></span><div><strong>Evidence stays connected.</strong><span>From the first report to verified completion.</span></div></div>
            <div className="workflow-caption-line"><span />A shared workflow for real operations</div>
          </div>
        </div>
      </section>
      <div className="operation-strip"><div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-x-6 gap-y-4 px-6 py-6 lg:px-8"><span className="text-[10px] font-semibold uppercase tracking-[.16em] text-slate">One shared standard</span>{["Hospitals & clinics", "Collection companies", "Treatment facilities", "Platform administrators"].map(x => <span key={x} className="flex items-center gap-2 text-xs font-medium text-charcoal"><span className="size-1 rounded-full bg-[#b9a1cd]" />{x}</span>)}</div></div>
      <section id="lifecycle" className="premium-section bg-white">
        <div className="mx-auto max-w-7xl px-6 lg:px-8">
          <div data-reveal className="flex flex-wrap items-end justify-between gap-6"><div><p className="eyebrow section-eyebrow"><span>01</span>The lifecycle</p><h2 className="section-title mt-5">Complex operations.<br />A considered path forward.</h2></div><p className="section-description max-w-sm">Give every team the information and actions they need, while keeping the full history in one place.</p></div>
          <div data-reveal className="reveal-stagger mt-12 grid gap-5 md:grid-cols-3">{steps.map(({ icon: Icon, title, label, text, number }) => <article key={number} className="lifecycle-card"><div className="flex items-center justify-between"><span className="feature-icon"><Icon size={24} strokeWidth={1.5} /></span><span className="card-number">{number}</span></div><p className="mt-9 text-[10px] font-semibold uppercase tracking-[.14em] text-brown">{label}</p><h3 className="mt-3 font-display text-xl font-medium tracking-tight">{title}</h3><p className="mt-4 text-sm leading-7 text-slate">{text}</p></article>)}</div>
        </div>
      </section>
      <section id="solution" className="premium-section solution-section">
        <div className="mx-auto grid max-w-7xl gap-12 px-6 lg:grid-cols-[.85fr_1.15fr] lg:gap-20 lg:px-8">
          <div data-reveal><p className="eyebrow section-eyebrow"><span>02</span>A unified platform</p><h2 className="section-title mt-5">Less fragmentation.<br /><span className="text-[#8964a8]">More clarity.</span></h2><p className="section-description mt-6 max-w-sm">Move between reporting, dispatch, treatment and billing without losing the context behind a decision.</p><Button asChild variant="outline" className="mt-8"><Link href="/register">Bring your team together<ArrowUpRight size={15} /></Link></Button><div className="solution-detail" aria-hidden="true"><div /><Fingerprint size={38} strokeWidth={1} /><span>Connected from the start.</span></div></div>
          <div data-reveal className="reveal-stagger space-y-4">{capabilities.map(({ icon: Icon, name, text, detail }) => <article key={name} className="capability-card"><span className="feature-icon shrink-0"><Icon size={23} strokeWidth={1.5} /></span><div><p className="mb-2 text-[9px] font-semibold uppercase tracking-[.14em] text-brown">{detail}</p><h3 className="font-display text-lg font-medium tracking-tight">{name}</h3><p className="mt-3 text-sm leading-7 text-slate">{text}</p></div></article>)}</div>
        </div>
      </section>
      <section id="network" className="premium-section bg-white">
        <div className="mx-auto max-w-7xl px-6 lg:px-8">
          <div data-reveal><p className="eyebrow section-eyebrow"><span>03</span>The people behind the process</p><div className="mt-5 flex flex-wrap items-end justify-between gap-6"><h2 className="section-title">Shared information.<br />Clear responsibilities.</h2><Link href="/login" className="editorial-link">Open your workspace<ArrowRight size={16} /></Link></div></div>
          <div data-reveal className="reveal-stagger mt-12 grid gap-5 md:grid-cols-3">{roles.map(({ icon: Icon, title, text, tag }) => <article key={title} className="role-card"><div className="role-card-top"><Icon size={29} strokeWidth={1.25} /><span className="role-card-line" /></div><p className="mt-9 text-[10px] font-semibold uppercase tracking-[.14em] text-brown">{tag}</p><h3 className="mt-3 font-display text-2xl font-medium tracking-tight">{title}</h3><p className="mt-4 text-sm leading-7 text-slate">{text}</p><Link href="/register" className="editorial-link mt-7 text-xs" aria-label={`Get started as ${title.toLowerCase()}`}>Get started<ArrowUpRight size={14} /></Link></article>)}</div>
        </div>
      </section>
      <section id="trust" className="trust-section">
        <div aria-hidden="true" className="trust-watermark"><ShieldCheck strokeWidth={.5} /></div>
        <div className="relative mx-auto grid max-w-7xl gap-12 px-6 lg:grid-cols-[.9fr_1.1fr] lg:items-center lg:gap-20 lg:px-8">
          <div data-reveal><p className="eyebrow section-eyebrow text-[#d2b697]"><span>04</span>Trust at every stage</p><h2 className="section-title mt-5 text-white">The full record.<br />A clearer next decision.</h2><p className="mt-6 max-w-sm text-sm leading-7 text-[#c2b5cf]">Accountability is built into the workflow, from organization review to verified completion.</p><span className="trust-seal"><ShieldCheck size={16} />Evidence-led. Human-reviewed.</span></div>
          <div data-reveal className="reveal-stagger grid gap-x-8 gap-y-9 sm:grid-cols-2">{[["Scoped access", "Role and organization permissions protect operational records."], ["Verified partners", "Review organizations and permits before assigning new work."], ["Connected evidence", "Keep handover, processing and payment evidence together."], ["Human oversight", "Review safety-critical classification and handling decisions."]].map(([title, text]) => <div className="trust-item" key={title}><ShieldCheck size={19} strokeWidth={1.5} /><h3 className="mt-4 font-display text-base font-medium">{title}</h3><p className="mt-3 text-xs leading-6">{text}</p></div>)}</div>
        </div>
      </section>
      <section className="premium-section cta-section"><div data-reveal className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-9 px-6 lg:px-8"><div><p className="eyebrow">Start with a clearer record</p><h2 className="section-title mt-5 max-w-2xl">Better connected.<br />From your very next batch.</h2><p className="section-description mt-5">Create an account and bring your organization together.</p></div><div><Button asChild size="lg"><Link href="/register">Create your workspace<ArrowUpRight size={17} /></Link></Button><p className="mt-3 text-center text-[11px] text-slate">Built around your team. Ready for real work.</p></div></div></section>
    </main>
    <Footer />
  </>;
}
