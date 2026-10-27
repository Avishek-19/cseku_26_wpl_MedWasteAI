"use client";
import { useDeferredEffect } from "@/hooks/use-deferred-effect";

import { AlertTriangle,CheckCircle2,ChevronRight,Clock3,MapPin,RefreshCw,Route as RouteIcon,Truck,Zap } from "lucide-react";
import Link from "next/link";
import { useCallback,useEffect,useMemo,useState } from "react";

import { LiveTrackingMap,type TrackingMapRoute } from "@/components/dashboard/live-tracking-map";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api,ApiError } from "@/lib/api";
import type { PickupRequest,Vehicle } from "@/types/waste";

type OptimizedRoute = TrackingMapRoute & {
  vehicle_id: string;
  tracking_session_id: string | null;
  is_optimized: boolean;
  total_distance_km: string | number | null;
  estimated_duration_minutes: number | null;
  routing_provider: string | null;
  destination_state?: string;
  destination_arrived_at?: string | null;
  destination_received_at?: string | null;
  completed_at?: string | null;
  optimization_details: { algorithm?: string; total_load_kg?: number; optimization_provider?: string } | null;
};

const optimizeStages = [
  "Optimizing route…",
  "Analyzing pickup sequence…",
  "Calculating road distance…",
  "Generating efficient route…",
];

export function RoutePlanner() {
  const [pickups, setPickups] = useState<PickupRequest[]>([]);
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [selectedPickupIds, setSelectedPickupIds] = useState<string[]>([]);
  const [vehicleId, setVehicleId] = useState("");
  const [route, setRoute] = useState<OptimizedRoute | null>(null);
  const [loading, setLoading] = useState(true);
  const [optimizing, setOptimizing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [stage, setStage] = useState(0);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [nextPickups, nextVehicles, readyRoutes] = await Promise.all([
        api.get<PickupRequest[]>("/api/v1/pickups/assigned?scope=company"),
        api.get<Vehicle[]>("/api/v1/vehicles/operations"),
        api.get<OptimizedRoute[]>("/api/v1/routes/ready"),
      ]);
      setPickups(nextPickups);
      setVehicles(nextVehicles);
      const restored = readyRoutes.find((item) => (item.status === "draft" || item.status === "ready") && nextVehicles.some((vehicle) => vehicle.id === item.vehicle_id)) ?? null;
      setVehicleId(current => restored?.vehicle_id || nextVehicles.find(item => item.id === current)?.id || nextVehicles.find(item => item.status !== "maintenance")?.id || nextVehicles[0]?.id || "");
      if (restored) {
        setRoute(restored);
        setSelectedPickupIds(restored.stops.map((stop) => stop.pickup_id));
        setMessage(`Restored ${restored.status.toUpperCase()} route v${restored.version} from the backend.`);
      }
    } catch (err) {
      setError(getErrorMessage(err, "Could not load route-planning data."));
    } finally {
      setLoading(false);
    }
  }, []);

  useDeferredEffect(() => {
    void load();
  }, [load]);

  const selectedVehicle = vehicles.find((vehicle) => vehicle.id === vehicleId) ?? null;
  // The backend requires every ASSIGNED pickup on this vehicle in one route.
  // Do not offer a partial-trip selection that will fail at confirmation.
  const vehicleAssignedPickups = useMemo(
    () => pickups.filter((pickup) => pickup.status === "assigned" && pickup.assigned_vehicle?.id === vehicleId),
    [pickups, vehicleId],
  );
  const eligiblePickups = useMemo(
    () => vehicleAssignedPickups.filter((pickup) => pickup.route_eligible),
    [vehicleAssignedPickups],
  );
  const blockedPickups = useMemo(
    () => vehicleAssignedPickups.filter((pickup) => !pickup.route_eligible),
    [vehicleAssignedPickups],
  );
  const selectedPickups = useMemo(
    () => pickups.filter((pickup) => selectedPickupIds.includes(pickup.id)),
    [pickups, selectedPickupIds],
  );
  const totalWeight = selectedPickups.reduce((sum, pickup) => sum + Number(pickup.total_weight_kg ?? 0), 0);
  const capacity = Number(selectedVehicle?.capacity_kg ?? 0);
  const capacityExceeded = capacity > 0 && totalWeight > capacity;
  const selectedCount = selectedPickupIds.length;
  const completeSelection = vehicleAssignedPickups.length > 0
    && blockedPickups.length === 0
    && selectedCount === vehicleAssignedPickups.length
    && vehicleAssignedPickups.every((pickup) => selectedPickupIds.includes(pickup.id));
  const destinationName = selectedPickups.find((p) => p.waste_records.some((r) => r.assigned_facility_name))?.waste_records.find((r) => r.assigned_facility_name)?.assigned_facility_name ?? "Confirmed Treatment Facility";

  useDeferredEffect(() => {
    const allowed = new Set(eligiblePickups.map((pickup) => pickup.id));
    setSelectedPickupIds((current) => current.filter((id) => allowed.has(id)));
  }, [eligiblePickups]);

  useEffect(() => {
    if (!optimizing) return;
    const timer = window.setInterval(() => setStage((current) => (current + 1) % optimizeStages.length), 850);
    return () => window.clearInterval(timer);
  }, [optimizing]);

  const togglePickup = (pickupId: string) => {
    setSelectedPickupIds((current) => current.includes(pickupId) ? current.filter((id) => id !== pickupId) : [...current, pickupId]);
    setRoute(null);
    setMessage(null);
  };

  const toggleAll = () => {
    const allSelected = eligiblePickups.length > 0 && eligiblePickups.every((pickup) => selectedPickupIds.includes(pickup.id));
    setSelectedPickupIds(allSelected ? [] : eligiblePickups.map((pickup) => pickup.id));
    setRoute(null);
  };

  const optimize = async () => {
    setError(null);
    setMessage(null);
    if (!vehicleId) return setError("Select a vehicle before optimizing the route.");
    if (!completeSelection) return setError("Select every assigned pickup for this vehicle. Resolve any ineligible pickup first; partial routes cannot be confirmed.");
    if (capacityExceeded) return setError(`Selected waste weighs ${formatKg(totalWeight)} kg, above this vehicle's ${formatKg(capacity)} kg capacity.`);
    setOptimizing(true);
    setStage(0);
    try {
      const nextRoute = await api.post<OptimizedRoute>("/api/v1/routes/optimize", { vehicle_id: vehicleId, pickup_ids: selectedPickupIds });
      setRoute(nextRoute);
      setMessage(nextRoute.routing_provider === "haversine" ? "Road routing service unavailable. Fallback distance calculation was used." : "Route optimized. Review the sequence before confirming.");
    } catch (err) {
      setError(getErrorMessage(err, "Route optimization failed."));
    } finally {
      setOptimizing(false);
    }
  };

  const confirm = async () => {
    if (!route) return;
    setSubmitting(true);
    setError(null);
    try {
      const nextRoute = await api.post<OptimizedRoute>(`/api/v1/routes/${route.id}/confirm`);
      setRoute(nextRoute);
      setMessage("Route confirmed. Start it when the vehicle is ready.");
    } catch (err) {
      setError(getErrorMessage(err, "Route confirmation failed."));
    } finally {
      setSubmitting(false);
    }
  };

  const start = async () => {
    if (!route) return;
    setSubmitting(true);
    setError(null);
    try {
      const nextRoute = await api.post<OptimizedRoute>(`/api/v1/routes/${route.id}/start`);
      setRoute(nextRoute);
      setMessage("Route started. Live GPS tracking is now connected to this route.");
    } catch (err) {
      setError(getErrorMessage(err, "Could not start the route."));
    } finally {
      setSubmitting(false);
    }
  };

  const routeForMap = route ? withStopLabels(route, pickups) : null;

  return (
    <div className="mx-auto max-w-7xl">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="font-data text-[10px] uppercase tracking-[0.16em] text-slate">Operations / Route planning</p>
          <h1 className="mt-1 font-display text-2xl font-semibold text-charcoal">Smart Route Planner</h1>
          <p className="mt-1.5 max-w-2xl text-[14px] text-slate">Build a multi-stop collection route from real assigned pickup requests, then hand it directly to live tracking.</p>
        </div>
        <Button variant="outline" size="sm" onClick={() => void load()} disabled={loading}><RefreshCw size={14} className={loading ? "animate-spin" : ""} /> Refresh data</Button>
      </div>

      {error && <div className="mt-5 flex items-start gap-2 rounded-xl border border-signal-rust/20 bg-signal-rust-bg px-4 py-3 text-[13px] text-signal-rust" role="alert"><AlertTriangle size={16} className="mt-0.5 shrink-0" /> <span>{error}</span></div>}
      {message && <div className="mt-5 rounded-xl border border-signal-emerald/20 bg-signal-emerald-bg px-4 py-3 text-[13px] text-charcoal" role="status">{message}</div>}

      <div className="mt-6 grid gap-5 xl:grid-cols-[minmax(0,1.1fr)_minmax(320px,.9fr)]">
        <section className="rounded-2xl border border-mist-deep bg-paper p-5 shadow-[0_8px_30px_rgba(16,28,23,0.04)] sm:p-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div><div className="flex items-center gap-2"><MapPin size={16} className="text-forest" /><h2 className="font-display text-base font-semibold text-charcoal">Pickup requests</h2></div><p className="mt-1 text-[12px] text-slate">All assigned pickups for the selected vehicle must be included in the same route. Partial-trip planning is not supported.</p></div>
            <Button variant="outline" size="sm" onClick={toggleAll} disabled={!eligiblePickups.length}>{eligiblePickups.length > 0 && eligiblePickups.every((pickup) => selectedPickupIds.includes(pickup.id)) ? "Deselect all" : "Select all"}</Button>
          </div>
          {blockedPickups.length > 0 && <div className="mt-4 rounded-xl border border-signal-rust/20 bg-signal-rust-bg px-3.5 py-3 text-xs text-signal-rust" role="alert">{blockedPickups.length} assigned pickup(s) cannot be routed. Refresh or resolve their eligibility before planning.</div>}
          <div className="mt-5 space-y-2.5">
            {loading ? <p className="rounded-xl bg-mist/50 px-4 py-8 text-center text-sm text-slate">Loading eligible pickups…</p> : eligiblePickups.length === 0 ? <div className="rounded-xl border border-dashed border-mist-deep px-4 py-8 text-center"><p className="text-sm font-medium text-charcoal">No route-eligible pickups for this vehicle</p><p className="mt-1 text-xs text-slate">Newly assigned pickups appear here after the backend has assigned them to a vehicle.</p></div> : eligiblePickups.map((pickup) => {
              const checked = selectedPickupIds.includes(pickup.id);
              return <label key={pickup.id} className={`block cursor-pointer rounded-xl border p-3.5 transition-colors ${checked ? "border-forest bg-forest/[0.05]" : "border-mist-deep bg-paper hover:bg-mist/45"}`}>
                <input type="checkbox" className="sr-only" checked={checked} onChange={() => togglePickup(pickup.id)} />
                <div className="flex items-start gap-3"><span className={`mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded border text-paper ${checked ? "border-forest bg-forest" : "border-slate-light"}`}>{checked && <CheckCircle2 size={14} />}</span><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><span className="font-data text-[11px] text-charcoal">{pickup.id}</span><PriorityBadge priority={pickup.priority} /><Badge variant={pickup.status === "assigned" ? "emerald" : "default"}>{pickup.status.replaceAll("_", " ")}</Badge></div><p className="mt-1 font-display text-sm font-semibold text-charcoal">{pickup.hospital.name}</p><p className="mt-0.5 flex items-start gap-1 text-[11px] text-slate"><MapPin size={12} className="mt-0.5 shrink-0" /> {pickup.hospital.address_line}, {pickup.hospital.city}</p><div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-slate"><span>{formatKg(Number(pickup.total_weight_kg ?? 0))} kg total</span><span>{pickup.waste_records.length} waste batch{pickup.waste_records.length === 1 ? "" : "es"}</span>{pickup.requested_pickup_at && <span><Clock3 size={11} className="mr-1 inline" />{new Date(pickup.requested_pickup_at).toLocaleString()}</span>}</div></div><ChevronRight size={16} className={`mt-1 shrink-0 ${checked ? "text-forest" : "text-slate-light"}`} /></div>
              </label>;
            })}
          </div>
        </section>

        <section className="rounded-2xl border border-mist-deep bg-paper p-5 shadow-[0_8px_30px_rgba(16,28,23,0.04)] sm:p-6">
          <div className="flex items-center gap-2"><Truck size={16} className="text-forest" /><h2 className="font-display text-base font-semibold text-charcoal">Vehicle & load</h2></div>
          <label htmlFor="route-vehicle" className="mt-5 block text-[12px] font-medium text-slate">Assigned vehicle</label>
          <select id="route-vehicle" value={vehicleId} onChange={(event) => { setVehicleId(event.target.value); setRoute(null); setMessage(null); }} className="mt-1.5 h-11 w-full rounded-lg border border-mist-deep bg-paper px-3 text-sm text-charcoal focus:border-forest focus:outline-none">
            <option value="">Select vehicle</option>
            {vehicles.map((vehicle) => <option key={vehicle.id} value={vehicle.id} disabled={vehicle.status === "maintenance"}>{vehicle.vehicle_code} · {vehicle.status.replaceAll("_", " ")}</option>)}
          </select>
          {selectedVehicle && <div className="mt-4 rounded-xl bg-mist/55 p-4"><div className="flex items-center justify-between"><span className="font-display text-sm font-semibold text-charcoal">{selectedVehicle.vehicle_code}</span><Badge variant={selectedVehicle.status === "maintenance" ? "amber" : "emerald"}>{selectedVehicle.status.replaceAll("_", " ")}</Badge></div><div className="mt-3 grid grid-cols-2 gap-2"><Info label="Capacity" value={`${formatKg(capacity)} kg`} /><Info label="Location" value={selectedVehicle.location ?? "Latest GPS position"} /></div></div>}
          <div className="mt-5 grid grid-cols-3 gap-2"><Info label="Selected" value={`${selectedCount} stop${selectedCount === 1 ? "" : "s"}`} /><Info label="Waste load" value={`${formatKg(totalWeight)} kg`} /><Info label="Usage" value={capacity ? `${Math.min(999, Math.round((totalWeight / capacity) * 100))}%` : "—"} /></div>
          {capacityExceeded && <div className="mt-4 flex items-start gap-2 rounded-xl border border-signal-rust/20 bg-signal-rust-bg px-3.5 py-3 text-xs text-signal-rust"><AlertTriangle size={15} className="mt-0.5 shrink-0" /><span>Vehicle capacity exceeded by {formatKg(totalWeight - capacity)} kg. Remove a pickup or choose a larger vehicle.</span></div>}
          {!completeSelection && vehicleAssignedPickups.length > 0 && <p className="mt-4 text-xs text-signal-rust" role="status">Select all {vehicleAssignedPickups.length} assigned pickup(s) to enable optimization. Current selection: {selectedCount}.</p>}
          <Button className="mt-5 w-full" onClick={() => void optimize()} disabled={optimizing || loading || capacityExceeded || !completeSelection || !vehicleId}><Zap size={15} />{optimizing ? optimizeStages[stage] : "Optimize route"}</Button>
          <p className="mt-3 text-center text-[11px] text-slate">Backend validation remains authoritative for capacity, ownership, eligibility, coordinates, and destination.</p>
        </section>
      </div>

      <section className="mt-5 rounded-2xl border border-mist-deep bg-paper p-2 shadow-[0_8px_30px_rgba(16,28,23,0.04)] sm:p-3"><LiveTrackingMap route={routeForMap} location={null} /></section>

      {route && (
        <section className="mt-5 rounded-2xl border border-mist-deep bg-paper p-5 sm:p-6">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <RouteIcon size={17} className="text-forest" />
                <h2 className="font-display text-lg font-semibold text-charcoal">Route summary</h2>
                <Badge variant={route.status === "active" ? "emerald" : "default"}>{route.status.replaceAll("_", " ")}</Badge>
              </div>
              <p className="mt-1 text-[12px] text-slate">Version {route.version} · {route.routing_provider === "haversine" ? "Haversine fallback" : "OSRM road routing"}</p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" onClick={() => void confirm()} disabled={submitting || route.status !== "draft"}><CheckCircle2 size={14} /> {submitting ? "Saving…" : "Confirm route"}</Button>
              <Button onClick={() => void start()} disabled={submitting || route.status !== "ready"}><Truck size={14} /> Start route</Button>
              {route.status === "active" && <Button asChild variant="outline"><Link href="/dashboard/tracking">Open live tracking</Link></Button>}
            </div>
          </div>

          <div className="mt-5 grid grid-cols-2 gap-3 md:grid-cols-4">
            <Info label="Stops" value={String(route.stops.length)} />
            <Info label="Distance" value={`${Number(route.total_distance_km ?? 0).toFixed(1)} km`} />
            <Info label="ETA" value={`${route.estimated_duration_minutes ?? "—"} min`} />
            <Info label="Load" value={`${formatKg(Number(route.optimization_details?.total_load_kg ?? totalWeight))} kg`} />
          </div>

          <div className="mt-6 grid gap-5 lg:grid-cols-[1fr_280px]">
            <div>
              <p className="font-data text-[10px] uppercase tracking-[0.14em] text-slate">Optimized stop sequence</p>
              <div className="mt-3 space-y-2">
                {route.stops.slice().sort((a, b) => a.sequence - b.sequence).map((stop) => (
                  <div key={stop.id} className="flex items-center gap-3 rounded-xl border border-mist-deep px-3.5 py-3">
                    <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-forest text-[11px] font-semibold text-paper">{String(stop.sequence).padStart(2, "0")}</span>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium text-charcoal">{stop.label ?? `Pickup ${stop.sequence}`}</p>
                      <p className="text-[11px] text-slate">{formatStopStatus(stop.status)}</p>
                    </div>
                    <MapPin size={15} className="shrink-0 text-slate-light" />
                  </div>
                ))}
              </div>
            </div>

            <div className="space-y-4">
              <div className="rounded-xl border border-forest/20 bg-forest/[0.04] p-4">
                <p className="font-data text-[10px] uppercase tracking-[0.14em] text-slate">Final destination</p>
                <div className="mt-2 flex items-start gap-2">
                  <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-forest text-paper">✚</span>
                  <div>
                    <p className="font-display text-sm font-semibold text-charcoal">{destinationName}</p>
                    <p className="mt-0.5 text-[11px] text-slate">{formatDestinationState(route.destination_state ?? "collection")}</p>
                  </div>
                </div>
              </div>
              <div className="rounded-xl bg-mist/55 p-4">
                <p className="font-data text-[10px] uppercase tracking-[0.14em] text-slate">Workflow</p>
                <ol className="mt-3 space-y-3 text-xs text-slate">
                  <li className="flex gap-2"><span className="font-data text-forest">01</span>Review the optimized sequence</li>
                  <li className="flex gap-2"><span className="font-data text-forest">02</span>Confirm the persisted route</li>
                  <li className="flex gap-2"><span className="font-data text-forest">03</span>Start route to connect GPS tracking</li>
                </ol>
              </div>
            </div>
          </div>
        </section>
      )}
    </div>
  );
}

function withStopLabels(route: OptimizedRoute, pickups: PickupRequest[]): OptimizedRoute {
  const byId = new Map(pickups.map((pickup) => [pickup.id, pickup]));
  return { ...route, stops: route.stops.map((stop) => ({ ...stop, label: byId.get(stop.pickup_id)?.hospital.name ?? null })) };
}

function PriorityBadge({ priority }: { priority: string }) {
  return <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.06em] ${priority === "emergency" ? "bg-signal-rust-bg text-signal-rust" : priority === "urgent" ? "bg-signal-amber-bg text-signal-amber" : "bg-mist text-slate"}`}>{priority}</span>;
}

function Info({ label, value }: { label: string; value: string }) {
  return <div className="rounded-xl bg-mist/60 px-3 py-2.5"><p className="font-data text-[9px] uppercase tracking-[0.12em] text-slate-light">{label}</p><p className="mt-1 truncate text-xs font-medium text-charcoal">{value}</p></div>;
}

function formatKg(value: number) { return Number.isFinite(value) ? value.toFixed(1) : "0.0"; }
function formatStopStatus(value: string) { return value.replaceAll("_", " ").replace(/\b\w/g, (character) => character.toUpperCase()); }
function formatDestinationState(value: string) { return value.replaceAll("_", " ").replace(/\b\w/g, (character) => character.toUpperCase()); }
function getErrorMessage(error: unknown, fallback: string) {
  if (error instanceof ApiError) return error.message;
  return error instanceof Error ? error.message : fallback;
}
