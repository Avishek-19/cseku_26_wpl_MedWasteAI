"use client";
import { useDeferredEffect } from "@/hooks/use-deferred-effect";

import {
AlertCircle,
AlertTriangle,
ArrowRight,
BadgeCheck,
BarChart3,
Gauge,
Leaf,
MapPin,
Package,
Recycle,
ShieldCheck,
Trash2
} from "lucide-react";
import Link from "next/link";
import { useEffect,useState } from "react";

import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import type { AnalyticsResponse } from "@/types/analytics";
import type { OrgDashboardStats } from "@/types/org";

const PERIODS = [
  ["7d", "7 days"],
  ["30d", "30 days"],
  ["90d", "90 days"],
  ["12m", "12 months"],
] as const;

function formatKg(value: number) {
  return `${value.toLocaleString(undefined, { maximumFractionDigits: 1 })} kg`;
}

function MiniLineChart({ points }: { points: AnalyticsResponse["waste_trend"] }) {
  if (!points.length) {
    return (
      <div className="flex h-48 items-center justify-center text-sm text-slate-light">
        No tracked weight in this period.
      </div>
    );
  }
  const width = 520;
  const height = 180;
  const padX = 28;
  const padY = 18;
  const max = Math.max(...points.map((p) => p.value), 1);
  const coords = points.map((p, i) => ({
    x: padX + (i * (width - padX * 2)) / Math.max(points.length - 1, 1),
    y: height - padY - (p.value / max) * (height - padY * 2),
  }));
  const path = coords.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x} ${p.y}`).join(" ");
  const areaPath = `${path} L ${coords[coords.length - 1].x} ${height - padY} L ${coords[0].x} ${height - padY} Z`;
  const step = Math.max(1, Math.ceil(points.length / 5));

  return (
    <div className="overflow-x-auto">
      <svg viewBox={`0 0 ${width} ${height}`} className="h-48 w-full" role="img">
        {[0.25, 0.5, 0.75, 1].map((ratio) => {
          const y = height - padY - ratio * (height - padY * 2);
          return (
            <line
              key={ratio}
              x1={padX}
              x2={width - padX}
              y1={y}
              y2={y}
              stroke="currentColor"
              className="text-mist-deep"
              strokeWidth="1"
            />
          );
        })}
        <path d={areaPath} fill="url(#gradFacility)" opacity="0.25" />
        <path
          d={path}
          fill="none"
          stroke="#6c40ab"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        {coords.map((p, i) => (
          <circle key={i} cx={p.x} cy={p.y} r="3.5" fill="#6c40ab" />
        ))}
        {points.map(
          (p, i) =>
            i % step === 0 && (
              <text
                key={`label-${i}`}
                x={coords[i].x}
                y={height - 4}
                textAnchor="middle"
                className="fill-slate-light text-[10px]"
              >
                {p.label}
              </text>
            )
        )}
        <defs>
          <linearGradient id="gradFacility" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#6c40ab" />
            <stop offset="100%" stopColor="#6c40ab" stopOpacity="0" />
          </linearGradient>
        </defs>
      </svg>
    </div>
  );
}

function CategoryBars({
  categories,
}: {
  categories: AnalyticsResponse["category_distribution"];
}) {
  if (!categories.length) {
    return (
      <div className="flex h-48 items-center justify-center text-sm text-slate-light">
        No other categories reported
      </div>
    );
  }
  return (
    <div className="space-y-4">
      {categories.slice(0, 6).map((category) => (
        <div key={category.name}>
          <div className="mb-1.5 flex items-center justify-between gap-3 text-[13px]">
            <span className="truncate font-medium text-charcoal">{category.name}</span>
            <span className="font-data text-[12px] text-slate">
              {category.percentage}%
            </span>
          </div>
          <div className="h-2.5 overflow-hidden rounded-full bg-mist">
            <div
              className="h-full rounded-full"
              style={{
                width: `${category.percentage}%`,
                background: "linear-gradient(90deg, #6c40ab, #4e2d7d)",
              }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

export function OrgOverview({
  fullName,
  apiBase,
  orgLabel,
  orgName,
}: {
  fullName: string;
  apiBase: "facilities";
  orgLabel: string;
  orgName: string;
}) {
  const [stats, setStats] = useState<OrgDashboardStats | null>(null);
  const [analytics, setAnalytics] = useState<AnalyticsResponse | null>(null);
  const [period, setPeriod] = useState<AnalyticsResponse["period"]>("30d");
  const [loading, setLoading] = useState(true);
  const [analyticsLoading, setAnalyticsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    api
      .get<OrgDashboardStats>(`/api/v1/${apiBase}/me/stats`)
      .then((data) => {
        if (!cancelled) setStats(data);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [apiBase]);

  useDeferredEffect(() => {
    let cancelled = false;
    setAnalyticsLoading(true);
    api
      .get<AnalyticsResponse>(`/api/v1/analytics/overview?period=${period}`)
      .then((data) => {
        if (!cancelled) setAnalytics(data);
      })
      .catch(() => {
        if (!cancelled) setAnalytics(null);
      })
      .finally(() => {
        if (!cancelled) setAnalyticsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [period]);

  const firstName = fullName?.trim()?.split(/\s+/)[0] || "there";
  const s = analytics?.summary;

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      {/* Hero */}
      <div
        className="workspace-welcome relative overflow-hidden rounded-3xl p-6 sm:p-8"
      >
        <div className="relative flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <div
              className="mb-3 inline-flex items-center gap-2 rounded-full px-3 py-1 text-[11px] font-medium"
              style={{
                background: "rgba(190,157,211,0.15)",
                border: "1px solid rgba(190,157,211,0.35)",
                color: "#d2b0e5",
              }}
            >
              <ShieldCheck size={13} />
              Facility workspace
            </div>
            <h1 className="font-display text-2xl font-semibold tracking-tight text-white sm:text-3xl">
              Welcome back,{" "}
              <span style={{ color: "#d2b0e5" }}>{firstName}</span>
            </h1>
            <p
              className="mt-2 max-w-md text-[14px]"
              style={{ color: "rgba(232,241,248,0.9)" }}
            >
              Here&apos;s where {orgName} stands today — capacity, intake &
              processing.
            </p>
          </div>

          <div className="flex flex-wrap gap-3">
            <div className="rounded-2xl bg-white/95 px-4 py-3 shadow-sm min-w-30">
              <div className="flex items-center gap-2">
                <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-emerald-50 text-emerald-600">
                  <BadgeCheck size={16} />
                </div>
                <div>
                  <p className="text-[11px] text-slate">Profile</p>
                  <p className="text-[13px] font-semibold text-charcoal">
                    {loading ? "…" : stats?.profile_complete ? "Complete" : "Incomplete"}
                  </p>
                </div>
              </div>
            </div>
            <div className="rounded-2xl bg-white/95 px-4 py-3 shadow-sm min-w-30">
              <div className="flex items-center gap-2">
                <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-teal-50 text-teal-600">
                  <ShieldCheck size={16} />
                </div>
                <div>
                  <p className="text-[11px] text-slate">Verification</p>
                  <p className="text-[13px] font-semibold text-charcoal">
                    {loading ? "…" : stats?.is_verified ? "Verified" : "Pending"}
                  </p>
                </div>
              </div>
            </div>
            <div className="rounded-2xl bg-white/95 px-4 py-3 shadow-sm min-w-30">
              <div className="flex items-center gap-2">
                <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-blue-50 text-blue-600">
                  <Gauge size={16} />
                </div>
                <div>
                  <p className="text-[11px] text-slate">Capacity</p>
                  <p className="text-[13px] font-semibold text-charcoal">
                    {loading || !stats?.capacity_kg ? "—" : `${stats.capacity_kg} kg`}
                  </p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {!loading && stats && !stats.profile_complete && (
        <div className="flex flex-col items-start justify-between gap-4 rounded-2xl border border-signal-amber/30 bg-signal-amber-bg px-6 py-5 shadow-md sm:flex-row sm:items-center">
          <div className="flex items-start gap-3">
            <div
              className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl"
              style={{ background: "rgba(230,126,34,0.15)", color: "#e67e22" }}
            >
              <AlertCircle size={18} />
            </div>
            <div>
              <p className="text-[14px] font-semibold text-charcoal">
                Complete your {orgLabel} profile
              </p>
              <p className="mt-0.5 text-[13px] text-slate">
                Add your registration, capacity, and accepted categories so
                matching can find you.
              </p>
            </div>
          </div>
          <Button size="sm" variant="outline" asChild className="shrink-0 rounded-xl">
            <Link href="/dashboard/profile">
              Complete profile <ArrowRight size={14} />
            </Link>
          </Button>
        </div>
      )}

      {!loading && stats?.profile_complete && !stats.is_verified && (
        <div className="flex items-center gap-3 rounded-2xl border border-mist-deep bg-paper px-6 py-4 shadow-sm">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-mist text-slate">
            <ShieldCheck size={18} />
          </div>
          <p className="text-[13.5px] text-slate">
            Your profile is complete and awaiting admin verification.
          </p>
        </div>
      )}

      {/* Treatment analytics */}
      <div>
        <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <h2 className="font-display text-xl font-semibold text-charcoal">
            Treatment analytics
          </h2>
          <div className="flex items-center gap-1 rounded-xl border border-mist-deep bg-paper p-1">
            {PERIODS.map(([value, label]) => (
              <button
                key={value}
                onClick={() => setPeriod(value)}
                className={`rounded-lg px-3 py-1.5 text-[12px] font-medium transition-colors ${
                  period === value
                    ? "bg-[#4e2d7d] text-white"
                    : "text-slate hover:bg-mist"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <div className="rounded-2xl border border-mist-deep bg-paper p-5 shadow-sm">
            <div className="flex items-start justify-between">
              <div>
                <p className="text-[11px] font-medium uppercase tracking-wide text-slate">
                  Tracked Waste
                </p>
                <p className="mt-1 font-display text-2xl font-semibold text-charcoal">
                  {analyticsLoading || !s ? "…" : formatKg(Number(s.tracked_weight_kg))}
                </p>
                <p className="mt-1 text-[12px] text-slate">
                  {s ? `${s.total_batches} batches` : ""}
                </p>
              </div>
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-slate-100 text-slate-600">
                <Trash2 size={18} />
              </div>
            </div>
          </div>

          <div className="rounded-2xl border border-emerald-100 bg-emerald-50/60 p-5 shadow-sm">
            <div className="flex items-start justify-between">
              <div>
                <p className="text-[11px] font-medium uppercase tracking-wide text-slate">
                  Recyclable
                </p>
                <p className="mt-1 font-display text-2xl font-semibold text-charcoal">
                  {analyticsLoading || !s ? "…" : formatKg(Number(s.recyclable_weight_kg))}
                </p>
              </div>
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-100 text-emerald-600">
                <Leaf size={18} />
              </div>
            </div>
          </div>

          <div className="rounded-2xl border border-sky-100 bg-sky-50/60 p-5 shadow-sm">
            <div className="flex items-start justify-between">
              <div>
                <p className="text-[11px] font-medium uppercase tracking-wide text-slate">
                  Recycling Rate
                </p>
                <p className="mt-1 font-display text-2xl font-semibold text-charcoal">
                  {analyticsLoading || !s ? "…" : `${s.recycling_rate}%`}
                </p>
              </div>
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-sky-100 text-sky-600">
                <Recycle size={18} />
              </div>
            </div>
          </div>

          <div className="rounded-2xl border border-rose-100 bg-rose-50/50 p-5 shadow-sm">
            <div className="flex items-start justify-between">
              <div>
                <p className="text-[11px] font-medium uppercase tracking-wide text-slate">
                  High Risk
                </p>
                <p className="mt-1 font-display text-2xl font-semibold text-charcoal">
                  {analyticsLoading || !s ? "…" : String(s.high_risk_batches)}
                </p>
              </div>
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-rose-100 text-rose-600">
                <AlertTriangle size={18} />
              </div>
            </div>
          </div>
        </div>

        <div className="mt-5 grid gap-5 lg:grid-cols-[1.55fr_1fr]">
          <div className="rounded-2xl border border-mist-deep bg-paper p-5 shadow-sm">
            <div className="mb-3 flex items-center justify-between">
              <p className="font-display text-[15px] font-semibold text-charcoal">
                Waste generation trend
              </p>
              <span className="text-[11px] text-slate-light">Waste (kg)</span>
            </div>
            {analyticsLoading ? (
              <div className="h-48 animate-pulse rounded-xl bg-mist" />
            ) : (
              <MiniLineChart points={analytics?.waste_trend ?? []} />
            )}
          </div>

          <div className="rounded-2xl border border-mist-deep bg-paper p-5 shadow-sm">
            <p className="mb-4 font-display text-[15px] font-semibold text-charcoal">
              Category distribution
            </p>
            {analyticsLoading ? (
              <div className="h-48 animate-pulse rounded-xl bg-mist" />
            ) : (
              <CategoryBars categories={analytics?.category_distribution ?? []} />
            )}
          </div>
        </div>
      </div>

      {/* Facility quick stats + links */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <div className="rounded-2xl border border-mist-deep bg-paper p-4">
          <p className="text-[11px] text-slate">Utilization</p>
          <p className="mt-1 text-xl font-semibold text-charcoal">
            {loading || stats?.utilization_percent == null
              ? "—"
              : `${stats.utilization_percent}%`}
          </p>
        </div>
        <div className="rounded-2xl border border-mist-deep bg-paper p-4">
          <p className="text-[11px] text-slate">Accepted categories</p>
          <p className="mt-1 text-xl font-semibold text-charcoal">
            {loading ? "…" : String(stats?.accepted_category_count ?? 0)}
          </p>
        </div>
        <div className="rounded-2xl border border-mist-deep bg-paper p-4">
          <p className="text-[11px] text-slate">Incoming waste</p>
          <p className="mt-1 text-xl font-semibold text-charcoal">
            {loading ? "…" : String(stats?.incoming_waste_count ?? 0)}
          </p>
        </div>
        <div className="rounded-2xl border border-mist-deep bg-paper p-4">
          <p className="text-[11px] text-slate">Processing queue</p>
          <p className="mt-1 text-xl font-semibold text-charcoal">
            {loading ? "…" : String(stats?.processing_queue_count ?? 0)}
          </p>
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        {[
          {
            href: "/dashboard/incoming",
            icon: Package,
            title: "Incoming",
            desc: "Shipments & processing",
            color: "bg-blue-50 text-blue-700",
          },
          {
            href: "/dashboard/tracking",
            icon: MapPin,
            title: "Live Tracking",
            desc: "Vehicles on the map",
            color: "bg-teal-50 text-teal-700",
          },
          {
            href: "/dashboard/incoming",
            icon: BarChart3,
            title: "Impact",
            desc: "Capacity & trends",
            color: "bg-emerald-50 text-emerald-700",
          },
        ].map((item) => (
          <Link
            key={item.title}
            href={item.href}
            className="group flex items-center gap-4 rounded-2xl border border-mist-deep bg-paper p-5 shadow-sm transition-all duration-300 hover:-translate-y-0.5 hover:shadow-lg hover:border-[#6c40ab]/40"
          >
            <div
              className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl ${item.color}`}
            >
              <item.icon size={22} strokeWidth={1.7} />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-[14px] font-semibold text-charcoal">{item.title}</p>
              <p className="mt-0.5 text-[12px] text-slate">{item.desc}</p>
            </div>
            <ArrowRight
              size={16}
              className="shrink-0 opacity-0 transition-all duration-300 group-hover:opacity-100"
              style={{ color: "#6c40ab" }}
            />
          </Link>
        ))}
      </div>
    </div>
  );
}