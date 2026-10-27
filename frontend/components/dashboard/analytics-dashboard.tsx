"use client";
import { useDeferredEffect } from "@/hooks/use-deferred-effect";

import { AlertTriangle,CheckCircle2,Leaf,Recycle,RefreshCw,Scale,Trash2 } from "lucide-react";
import { useCallback,useMemo,useState } from "react";

import { StatCard } from "@/components/dashboard/stat-card";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import type { AnalyticsResponse } from "@/types/analytics";

const PERIODS = [
  ["7d", "7 days"],
  ["30d", "30 days"],
  ["90d", "90 days"],
  ["12m", "12 months"],
] as const;

function formatKg(value: number) {
  return `${value.toLocaleString(undefined, { maximumFractionDigits: 1 })} kg`;
}

function LineChart({ points }: { points: AnalyticsResponse["waste_trend"] }) {
  if (!points.length) {
    return <div className="flex h-64 items-center justify-center text-sm text-slate-light">No tracked weight in this period.</div>;
  }
  const width = 760;
  const height = 260;
  const padX = 34;
  const padY = 24;
  const max = Math.max(...points.map((p) => p.value), 1);
  const coords = points.map((p, i) => ({
    x: padX + (i * (width - padX * 2)) / Math.max(points.length - 1, 1),
    y: height - padY - (p.value / max) * (height - padY * 2),
  }));
  const path = coords.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x} ${p.y}`).join(" ");
  const step = Math.max(1, Math.ceil(points.length / 6));

  return (
    <div className="overflow-x-auto">
      <svg viewBox={`0 0 ${width} ${height}`} className="h-64 min-w-[680px] w-full" role="img" aria-label="Waste generation trend">
        {[0.25, 0.5, 0.75, 1].map((ratio) => {
          const y = height - padY - ratio * (height - padY * 2);
          return <line key={ratio} x1={padX} x2={width - padX} y1={y} y2={y} stroke="currentColor" className="text-mist-deep" strokeWidth="1" />;
        })}
        <path d={path} fill="none" stroke="currentColor" className="text-emerald" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
        {coords.map((p, i) => <circle key={i} cx={p.x} cy={p.y} r="3.5" fill="currentColor" className="text-emerald" />)}
        {points.map((p, i) => i % step === 0 && <text key={`label-${i}`} x={coords[i].x} y={height - 5} textAnchor="middle" className="fill-slate-light text-[10px]">{p.label}</text>)}
      </svg>
    </div>
  );
}

function CategoryBars({ categories }: { categories: AnalyticsResponse["category_distribution"] }) {
  const max = Math.max(...categories.map((c) => c.batches), 1);
  if (!categories.length) return <div className="flex h-64 items-center justify-center text-sm text-slate-light">No categories in this period.</div>;
  return (
    <div className="space-y-4">
      {categories.slice(0, 8).map((category) => (
        <div key={category.name}>
          <div className="mb-1.5 flex items-center justify-between gap-3 text-[13px]">
            <span className="truncate text-charcoal">{category.name}</span>
            <span className="font-data text-[11px] text-slate-light">{category.batches} batches · {category.percentage}%</span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-mist">
            <div className="h-full rounded-full bg-emerald" style={{ width: `${(category.batches / max) * 100}%` }} />
          </div>
        </div>
      ))}
    </div>
  );
}

function ProcessingBars({ items }: { items: AnalyticsResponse["processing"] }) {
  const icons = [Recycle, Scale, Trash2];
  const max = Math.max(...items.map((i) => i.value), 1);
  return (
    <div className="space-y-5">
      {items.map((item, index) => {
        const Icon = icons[index] ?? Scale;
        return (
          <div key={item.label}>
            <div className="mb-2 flex items-center gap-3">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-mist text-forest"><Icon size={15} /></div>
              <div className="min-w-0 flex-1"><p className="text-[13px] font-medium text-charcoal">{item.label}</p><div className="mt-1.5 h-1.5 rounded-full bg-mist"><div className="h-full rounded-full bg-forest" style={{ width: `${(item.value / max) * 100}%` }} /></div></div>
              <span className="font-data text-[11px] text-slate-light">{formatKg(item.value)}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function AnalyticsDashboard() {
  const [period, setPeriod] = useState<AnalyticsResponse["period"]>("30d");
  const [data, setData] = useState<AnalyticsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (selected = period) => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.get<AnalyticsResponse>(`/api/v1/analytics/overview?period=${selected}`);
      setData(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load analytics.");
    } finally {
      setLoading(false);
    }
  }, [period]);

  useDeferredEffect(() => { void load(period); }, [period, load]);

  const title = useMemo(() => data?.scope === "collector" ? "Collection analytics" : data?.scope === "facility" ? "Treatment analytics" : "Environmental analytics", [data?.scope]);

  if (loading && !data) {
    return <div className="mx-auto max-w-6xl animate-pulse"><div className="h-8 w-64 rounded bg-mist" /><div className="mt-2 h-4 w-96 rounded bg-mist" /><div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">{[1,2,3,4].map((i) => <div key={i} className="h-28 rounded-xl border border-mist-deep bg-paper" />)}</div><div className="mt-6 h-80 rounded-xl border border-mist-deep bg-paper" /></div>;
  }

  if (error && !data) {
    return <div className="mx-auto max-w-3xl rounded-2xl border border-signal-rust/20 bg-signal-rust-bg p-6"><p className="font-display font-semibold text-charcoal">Analytics unavailable</p><p className="mt-1 text-sm text-slate">{error}</p><Button className="mt-4" variant="outline" onClick={() => void load()}><RefreshCw size={14} /> Try again</Button></div>;
  }

  if (!data) return null;
  const s = data.summary;

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <header className="flex flex-col justify-between gap-5 lg:flex-row lg:items-end">
        <div>
          <div className="mb-2 flex items-center gap-2"><Leaf size={16} className="text-emerald" /><span className="font-data text-[10px] font-medium uppercase tracking-[0.14em] text-emerald-dim">Decision support · {data.scope}</span></div>
          <h1 className="font-display text-3xl font-semibold text-charcoal">{title}</h1>
          <p className="mt-1.5 max-w-2xl text-[14px] text-slate">Operational waste and processing metrics derived from your existing chain-of-custody records.</p>
        </div>
        <div className="flex items-center gap-2 rounded-xl border border-mist-deep bg-paper p-1">
          {PERIODS.map(([value, label]) => <button key={value} onClick={() => setPeriod(value)} className={`rounded-lg px-3 py-2 text-[12px] transition-colors ${period === value ? "bg-forest text-paper" : "text-slate hover:bg-mist"}`}>{label}</button>)}
          <button aria-label="Refresh analytics" onClick={() => void load()} className="ml-1 rounded-lg p-2 text-slate hover:bg-mist"><RefreshCw size={14} className={loading ? "animate-spin" : ""} /></button>
        </div>
      </header>

      {error && <div className="rounded-xl border border-signal-amber/20 bg-signal-amber-bg px-4 py-3 text-[13px] text-charcoal">{error}</div>}

      <section className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="Tracked waste" value={formatKg(Number(s.tracked_weight_kg))} hint={`${s.total_batches} batches`} />
        <StatCard label="Recyclable" value={formatKg(Number(s.recyclable_weight_kg))} hint="Eligible category weight" tone="emerald" />
        <StatCard label="Recycling rate" value={`${s.recycling_rate}%`} hint="Recycled ÷ recyclable weight" tone="emerald" />
        <StatCard label="High risk" value={String(s.high_risk_batches)} hint="High or critical assessments" tone={s.high_risk_batches ? "amber" : "muted"} />
      </section>

      <section className="grid gap-6 lg:grid-cols-[1.6fr_1fr]">
        <div className="rounded-2xl border border-mist-deep bg-paper p-6">
          <div className="flex items-start justify-between gap-4"><div><p className="font-display text-lg font-semibold text-charcoal">Waste generation trend</p><p className="mt-1 text-[12.5px] text-slate-light">Tracked mass over the selected period</p></div><div className="rounded-lg bg-signal-emerald-bg p-2 text-emerald"><Leaf size={16} /></div></div>
          <div className="mt-5"><LineChart points={data.waste_trend} /></div>
        </div>
        <div className="rounded-2xl border border-mist-deep bg-paper p-6"><p className="font-display text-lg font-semibold text-charcoal">Category distribution</p><p className="mt-1 text-[12.5px] text-slate-light">Batch share by waste category</p><div className="mt-7"><CategoryBars categories={data.category_distribution} /></div></div>
      </section>

      <section className="grid gap-6 lg:grid-cols-[1fr_1fr]">
        <div className="rounded-2xl border border-mist-deep bg-paper p-6"><p className="font-display text-lg font-semibold text-charcoal">Processing outcomes</p><p className="mt-1 text-[12.5px] text-slate-light">Completed pathway quantities recorded in this period</p><div className="mt-7"><ProcessingBars items={data.processing} /></div></div>
        <div className="rounded-2xl border border-mist-deep bg-paper p-6"><p className="font-display text-lg font-semibold text-charcoal">Lifecycle snapshot</p><div className="mt-6 grid grid-cols-2 gap-3"><div className="rounded-xl bg-mist/60 p-4"><p className="text-[11px] uppercase tracking-wide text-slate-light">Active</p><p className="mt-1 font-display text-2xl font-semibold text-charcoal">{s.active_batches}</p></div><div className="rounded-xl bg-signal-emerald-bg p-4"><p className="text-[11px] uppercase tracking-wide text-emerald-dim">Completed</p><p className="mt-1 font-display text-2xl font-semibold text-forest">{s.completed_batches}</p></div><div className="rounded-xl bg-signal-amber-bg p-4"><p className="text-[11px] uppercase tracking-wide text-signal-amber">Treated</p><p className="mt-1 font-display text-2xl font-semibold text-charcoal">{formatKg(Number(s.treated_weight_kg))}</p></div><div className="rounded-xl bg-mist/60 p-4"><p className="text-[11px] uppercase tracking-wide text-slate-light">Disposed</p><p className="mt-1 font-display text-2xl font-semibold text-charcoal">{formatKg(Number(s.disposed_weight_kg))}</p></div></div><div className="mt-5 space-y-2">{data.notes.map((note) => <div key={note} className="flex gap-2 text-[12px] leading-5 text-slate"><CheckCircle2 size={14} className="mt-0.5 shrink-0 text-emerald" />{note}</div>)}</div></div>
      </section>

      <div className="rounded-xl border border-mist-deep bg-paper px-5 py-4"><div className="flex gap-3"><AlertTriangle size={17} className="mt-0.5 shrink-0 text-signal-amber" /><p className="text-[12.5px] leading-5 text-slate"><span className="font-medium text-charcoal">Analytics are decision-support indicators.</span> Environmental mass metrics deliberately avoid unsupported conversions. AI recommendations are not treated as authoritative operational or medical decisions.</p></div></div>
    </div>
  );
}
