"use client";
import { useDeferredEffect } from "@/hooks/use-deferred-effect";

import { Badge } from "@/components/ui/badge";
import { useTrackingWebSocket } from "@/hooks/use-tracking-websocket";
import { api,ApiError } from "@/lib/api";
import { ArrowRight,CheckCircle2,Clock3,Route as RouteIcon,Truck } from "lucide-react";
import { useState } from "react";

type Transfer = {
  transfer_id: string;
  route_id: string;
  route_version: number;
  hospital: string;
  facility: string;
  facility_id: string | null;
  vehicle: string | null;
  collector_id: string;
  waste_ids: string[];
  collected_at: string | null;
  destination_arrived_at: string | null;
  received_at: string | null;
  distance_km: string | number | null;
  duration_minutes: number | null;
  status: string;
};

export default function TransferHistoryPage() {
  const [items, setItems] = useState<Transfer[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    api.get<{ items: Transfer[] }>("/api/v1/pickups/transfers/history")
      .then((data) => setItems(data.items))
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load transfer history."))
      .finally(() => setLoading(false));
  };

  useDeferredEffect(() => { load(); }, []);

  useTrackingWebSocket({
    enabled: false,
    onEvent: () => undefined,
  });

  return (
    <div className="mx-auto max-w-6xl">
      <p className="font-data text-[10px] uppercase tracking-[0.16em] text-slate">Collector / Chain of custody</p>
      <div className="mt-1 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-2xl font-semibold text-charcoal">Transfer history</h1>
          <p className="mt-1.5 text-[14px] text-slate">Permanent Hospital → Treatment Facility transport records from persisted routes.</p>
        </div>
      </div>

      {error && <div className="mt-5 rounded-xl border border-signal-rust/20 bg-signal-rust-bg px-4 py-3 text-[13px] text-signal-rust">{error}</div>}

      <div className="mt-6 space-y-4">
        {loading ? <p className="text-sm text-slate">Loading…</p> : items.length === 0 ? (
          <div className="rounded-2xl border border-mist-deep bg-paper p-12 text-center text-sm text-slate">No completed transfers yet.</div>
        ) : items.map((item) => (
          <article key={item.transfer_id} className="rounded-2xl border border-mist-deep bg-paper p-5 shadow-[0_8px_30px_rgba(16,28,23,0.04)]">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="emerald"><CheckCircle2 size={13} /> COMPLETED</Badge>
                <span className="font-data text-[11px] text-slate">Route v{item.route_version}</span>
              </div>
              <span className="font-data text-[10px] text-slate-light">{item.transfer_id}</span>
            </div>
            <div className="mt-5 flex flex-col gap-3 md:flex-row md:items-center">
              <div className="flex-1 rounded-xl bg-mist/55 p-4"><p className="text-[10px] uppercase tracking-wide text-slate-light">Hospital</p><p className="mt-1 font-display font-semibold text-charcoal">{item.hospital}</p></div>
              <ArrowRight className="mx-auto text-forest md:shrink-0" size={22} />
              <div className="flex-1 rounded-xl border border-forest/20 bg-forest/[0.04] p-4"><p className="text-[10px] uppercase tracking-wide text-slate-light">Treatment Facility</p><p className="mt-1 font-display font-semibold text-charcoal">{item.facility}</p></div>
            </div>
            <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-5">
              <Metric icon={<Truck size={14} />} label="Vehicle" value={item.vehicle ?? "—"} />
              <Metric icon={<Clock3 size={14} />} label="Collected" value={formatTime(item.collected_at)} />
              <Metric icon={<Clock3 size={14} />} label="Arrived" value={formatTime(item.destination_arrived_at)} />
              <Metric icon={<Clock3 size={14} />} label="Received" value={formatTime(item.received_at)} />
              <Metric icon={<RouteIcon size={14} />} label="Route" value={`${Number(item.distance_km ?? 0).toFixed(1)} km`} />
            </div>
            <p className="mt-4 text-[11px] text-slate">Waste batches: {item.waste_ids.length} · Transport duration: {item.duration_minutes ?? "—"} min</p>
          </article>
        ))}
      </div>
    </div>
  );
}

function Metric({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return <div className="rounded-xl bg-mist/50 px-3 py-2.5"><div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wide text-slate-light">{icon}{label}</div><p className="mt-1 text-xs font-medium text-charcoal">{value}</p></div>;
}
function formatTime(value: string | null) { return value ? new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "—"; }
