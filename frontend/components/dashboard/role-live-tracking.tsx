"use client";
import { useDeferredEffect } from "@/hooks/use-deferred-effect";

import { AlertTriangle,CheckCircle2,LocateFixed,RefreshCw,Route as RouteIcon,Truck,WifiOff } from "lucide-react";
import { useCallback,useMemo,useState } from "react";

import { LiveTrackingMap,type TrackingMapLocation,type TrackingMapRoute } from "@/components/dashboard/live-tracking-map";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useTrackingWebSocket } from "@/hooks/use-tracking-websocket";
import { api } from "@/lib/api";
import { gpsTrust,gpsTrustLabel } from "@/lib/gps-trust";
import type { UserRole } from "@/types/auth";

type Vehicle = {
  id: string;
  vehicle_code: string;
  status: string;
  capacity_kg: number;
  assigned_collector_id: string;
};
type Item = {
  vehicle: Vehicle;
  location: TrackingMapLocation | null;
  route: TrackingMapRoute & { stops: (TrackingMapRoute["stops"][number] & { priority?: string | null; pickup_status?: string | null })[] } | null;
};
type Overview = { role: UserRole; vehicles: Item[] };
export function RoleLiveTracking({ role }: { role: UserRole }) {
  const isOperator = role === "collector" || role === "admin";
  const [data, setData] = useState<Overview | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  const [busy, setBusy] = useState(false);
  const [stopBusy, setStopBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [clock, setClock] = useState(() => Date.now());

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const next = await api.get<Overview>("/api/v1/tracking/role-overview");
      setData(next);
      setSelected((current) => current && next.vehicles.some((v) => v.vehicle.id === current) ? current : next.vehicles[0]?.vehicle.id ?? null);
      setMessage(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useDeferredEffect(() => {
    void load().catch((e) => setMessage(e instanceof Error ? e.message : "Could not load tracking data."));
    const timer = window.setInterval(() => setClock(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [load]);

  const socketState = useTrackingWebSocket({
    vehicleIds: data?.vehicles.map((item) => item.vehicle.id) ?? [],
    routeIds: data?.vehicles.map((item) => item.route?.id).filter((id): id is string => Boolean(id)) ?? [],
    enabled: Boolean(data?.vehicles.length),
    onEvent: (payload) => {
      if (payload.event === "vehicle.location.updated" && payload.vehicle_id && payload.location) {
        setData((current) => current ? {
          ...current,
          vehicles: current.vehicles.map((item) => {
            if (item.vehicle.id !== payload.vehicle_id) return item;
            const progress = payload.route_progress;
            const route = item.route && progress && item.route.id === progress.route_id
              ? { ...item.route, status: progress.status, destination_state: progress.destination_state, stops: item.route.stops.map((stop) => ({ ...stop, status: progress.stops.find((next) => next.id === stop.id)?.status ?? stop.status })) }
              : item.route;
            return { ...item, location: payload.location!, route };
          }),
        } : current);
      } else if (["vehicle.destination.arrived", "destination.received", "waste.processing.completed", "pickup.status.updated"].includes(payload.event ?? "") || payload.event?.startsWith("route.") || payload.event?.startsWith("tracking.session.")) {
        void load().catch((e) => setMessage(e instanceof Error ? e.message : "Could not synchronize tracking data."));
      }
    },
  });

  const connection = socketState;

  // A reconnect must synchronize the latest authorized snapshot before live events resume.
  useDeferredEffect(() => {
    if (connection === "live") void load().catch((e) => setMessage(e instanceof Error ? e.message : "Could not synchronize tracking data."));
  }, [connection, load]);

  const item = data?.vehicles.find((v) => v.vehicle.id === selected) ?? null;
  const staleSeconds = Number(process.env.NEXT_PUBLIC_GPS_STALE_THRESHOLD_SECONDS ?? 30);
  const trust = gpsTrust(item?.location ?? null, clock, staleSeconds);

  const metrics = useMemo(() => {
    const vehicles = data?.vehicles ?? [];
    const active = vehicles.filter((v) => v.route?.status === "active").length;
    const stale = vehicles.filter((v) => v.location && (clock - new Date(v.location.timestamp).getTime()) / 1000 > staleSeconds).length;
    return { active, stale };
  }, [data, staleSeconds, clock]);

  async function recalculate() {
    if (!item?.route?.id) return;
    setBusy(true); setMessage(null);
    try {
      const replanned = await api.post<{ id: string; version: number; status: string }>(`/api/v1/routes/${item.route.id}/recalculate`);
      await load();
      setMessage(replanned.status === "active"
        ? "Active route recalculated in place; completed stops remain unchanged."
        : `New draft route v${replanned.version} created. Review and confirm it before starting.`);
    } catch (e) { setMessage(e instanceof Error ? e.message : "Route recalculation failed."); }
    finally { setBusy(false); }
  }

  async function completeStop(stopId: string) {
    if (!item?.route?.id) return;
    setStopBusy(stopId);
    setMessage(null);
    try {
      await api.post(`/api/v1/routes/${item.route.id}/stops/${stopId}/complete`);
      await load();
      setMessage("Pickup completed and route progress advanced to the next stop.");
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Could not complete this pickup stop.");
    } finally {
      setStopBusy(null);
    }
  }

  return (
    <div className="mx-auto max-w-7xl">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="font-data text-[10px] uppercase tracking-[0.16em] text-slate">Operations / Live tracking</p>
          <h1 className="mt-1 font-display text-2xl font-semibold text-charcoal">
            {role === "admin" ? "Logistics command center" : role === "facility" ? "Inbound vehicle tracking" : role === "hospital" ? "Your pickup tracking" : "Collection route control"}
          </h1>
          <p className="mt-1.5 text-[14px] text-slate">
            {role === "admin" ? "Monitor the authorized fleet in real time." : "Live location and route state from the tracking service."}
          </p>
        </div>
        <div className="flex items-center gap-2" aria-live="polite">
          <Badge variant={connection === "live" ? "emerald" : "amber"}>
            {connection === "live" ? "● LIVE" : connection === "reconnecting" ? "◐ RECONNECTING" : "○ OFFLINE"}
          </Badge>
          <Button variant="outline" size="sm" onClick={() => void load()} disabled={loading}><RefreshCw size={14} className={loading ? "animate-spin" : ""} /> {loading ? "Refreshing…" : "Refresh"}</Button>
        </div>
      </div>

      <div className="mt-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Metric label={role === "admin" ? "Vehicles visible" : "Vehicles assigned"} value={data?.vehicles.length ?? 0} icon={<Truck size={15} />} />
        <Metric label="Active routes" value={metrics.active} icon={<RouteIcon size={15} />} />
        <Metric label="GPS stale" value={metrics.stale} icon={<WifiOff size={15} />} />
        <Metric label="Remaining stops" value={data?.vehicles.reduce((n, v) => n + (v.route?.stops.filter(s => !["collected", "cancelled", "skipped"].includes(s.status)).length ?? 0), 0) ?? 0} icon={<LocateFixed size={15} />} />
      </div>

      {loading && !data && <div className="mt-4 rounded-xl border border-mist-deep bg-mist/50 px-4 py-3 text-sm text-slate" role="status">Loading authorized tracking data…</div>}

      {message && <div className="mt-4 rounded-xl border border-mist-deep bg-paper px-4 py-3 text-sm text-slate">{message}</div>}

      {(data?.vehicles.length ?? 0) > 1 && (
        <div className="mt-5 flex gap-2 overflow-x-auto pb-1">
          {data?.vehicles.map((entry) => (
            <button
              key={entry.vehicle.id}
              type="button"
              onClick={() => setSelected(entry.vehicle.id)}
              className={`shrink-0 rounded-xl border px-3.5 py-2.5 text-left transition-colors ${
                selected === entry.vehicle.id
                  ? "border-forest bg-forest/[0.06]"
                  : "border-mist-deep bg-paper hover:bg-mist"
              }`}
            >
              <p className="font-display text-xs font-semibold text-charcoal">{entry.vehicle.vehicle_code}</p>
              <p className="mt-0.5 text-[10px] text-slate">{entry.vehicle.status.replaceAll("_", " ")}</p>
            </button>
          ))}
        </div>
      )}

      {!item ? (
        <div className="mt-6 rounded-2xl border border-mist-deep bg-paper px-6 py-12 text-center">
          <Truck className="mx-auto text-slate-light" size={28} />
          <p className="mt-3 font-display text-sm font-semibold text-charcoal">No authorized live vehicles</p>
          <p className="mt-1 text-xs text-slate">Tracking appears here when a vehicle is assigned to an accessible pickup or route.</p>
        </div>
      ) : (
        <div className="mt-6 grid gap-5 xl:grid-cols-[minmax(0,1fr)_330px]">
          <div className="min-w-0">
            <LiveTrackingMap route={item.route} location={item.location} staleThresholdSeconds={staleSeconds} />
          </div>
          <aside className="rounded-2xl border border-mist-deep bg-paper p-5">
            <div className="flex items-center justify-between">
              <div>
                <p className="font-data text-[10px] uppercase tracking-[0.14em] text-slate">Selected vehicle</p>
                <h2 className="mt-1 font-display text-lg font-semibold text-charcoal">{item.vehicle.vehicle_code}</h2>
              </div>
              <Badge variant={trust === "verified" ? "emerald" : "amber"}>
                {gpsTrustLabel[trust]}
              </Badge>
            </div>
            <div className="mt-5 grid grid-cols-2 gap-3">
              <Info label="Status" value={item.vehicle.status.replaceAll("_", " ").toUpperCase()} />
              <Info label="GPS trust" value={gpsTrustLabel[trust]} />
              <Info label="Speed" value={`${item.location?.speed_kmh?.toFixed(0) ?? "—"} km/h`} />
              <Info label="Route" value={item.route ? `v${item.route.version}` : "None"} />
              <Info label="Stops" value={String(item.route?.stops.length ?? 0)} />
              <Info label="Progress" value={item.route ? `${item.route.stops.filter((stop) => ["collected", "skipped", "cancelled"].includes(stop.status)).length}/${item.route.stops.length}` : "—"} />
              <Info label="Destination" value={item.route?.destination_state?.replaceAll("_", " ").toUpperCase() ?? "—"} />
            </div>

            <p className="mt-3 text-xs text-slate" role="status">{trust === "verified"
              ? "Authenticated device telemetry. GPS verification does not replace QR handover."
              : trust === "unverified" ? "Location shown for awareness only; not trusted for automatic arrival."
              : trust === "simulator" ? "Unverified location; physical arrival evidence is required."
              : trust === "anomalous" ? "Location flagged as anomalous; automatic arrival is not verified."
              : "Location is missing or stale; vehicle position may be outdated."}</p>
            <div className="mt-5 border-t border-mist-deep pt-5">
              <p className="font-data text-[10px] uppercase tracking-[0.14em] text-slate">Route stops</p>
              <div className="mt-3 space-y-2">
                {item.route?.stops.map((stop) => (
                  <div key={stop.id} className="flex items-center gap-3 rounded-xl border border-mist-deep px-3 py-2.5">
                    <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-mist font-data text-[10px] text-charcoal">{String(stop.sequence).padStart(2, "0")}</span>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-[12.5px] font-medium text-charcoal">{stop.priority ? `${stop.priority.toUpperCase()} · ` : ""}Pickup</p>
                      <p className="text-[10.5px] text-slate">{stop.status.replaceAll("_", " ")}</p>
                    </div>
                    {isOperator && stop.status === "arrived" && <Button size="sm" variant="outline" onClick={() => void completeStop(stop.id)} disabled={stopBusy === stop.id}><CheckCircle2 size={13} /> {stopBusy === stop.id ? "Saving…" : "Complete"}</Button>}
                  </div>
                ))}
              </div>
            </div>

            {isOperator && item.route?.id && (
              <div className="mt-5 flex flex-col gap-2">
                <Button onClick={() => void recalculate()} disabled={busy} className="w-full"><RefreshCw size={14} /> {busy ? "Recalculating…" : "Recalculate route"}</Button>
              </div>
            )}
            {role === "hospital" && <div className="mt-5 rounded-xl bg-mist px-3.5 py-3 text-xs text-slate">Only vehicles associated with your own pickup requests are visible.</div>}
            {role === "facility" && <div className="mt-5 rounded-xl bg-mist px-3.5 py-3 text-xs text-slate">Only vehicles carrying waste confirmed for your facility are visible.</div>}
            {role === "admin" && <div className="mt-5 rounded-xl bg-mist px-3.5 py-3 text-xs text-slate">Administrator view is fleet-wide and still uses backend authorization for every subscription.</div>}
          </aside>
        </div>
      )}

      {role === "admin" && metrics.stale > 0 && (
        <div className="mt-4 flex items-center gap-2 rounded-xl border border-signal-amber/25 bg-signal-amber-bg px-4 py-3 text-xs text-charcoal">
          <AlertTriangle size={15} className="text-signal-amber" /> {metrics.stale} vehicle(s) have a stale GPS signal.
        </div>
      )}
    </div>
  );
}

function Metric({ label, value, icon }: { label: string; value: number; icon: React.ReactNode }) {
  return <div className="rounded-xl border border-mist-deep bg-paper px-4 py-3"><div className="flex items-center gap-2 text-slate">{icon}<span className="font-data text-[10px] uppercase tracking-[0.12em]">{label}</span></div><p className="mt-1 font-display text-xl font-semibold text-charcoal">{value}</p></div>;
}
function Info({ label, value }: { label: string; value: string }) {
  return <div className="rounded-xl bg-mist px-3 py-2.5"><p className="font-data text-[9px] uppercase tracking-[0.12em] text-slate">{label}</p><p className="mt-1 text-xs font-medium text-charcoal">{value}</p></div>;
}
