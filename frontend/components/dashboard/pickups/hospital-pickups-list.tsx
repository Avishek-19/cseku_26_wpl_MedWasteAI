"use client";

import { CalendarClock,Plus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect,useState } from "react";

import {
PickupPriorityBadge,
PickupStatusBadge,
} from "@/components/dashboard/pickups/pickup-badges";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { useTrackingWebSocket } from "@/hooks/use-tracking-websocket";
import { api } from "@/lib/api";
import type { PickupRequestListResponse,PickupStatus } from "@/types/waste";
import { PICKUP_STATUS_LABELS } from "@/types/waste";

export function HospitalPickupsList() {
  const router = useRouter();
  const [status, setStatus] = useState<PickupStatus | "">("");
  const [data, setData] = useState<PickupRequestListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true);
    const params = new URLSearchParams({ page: "1", page_size: "20" });
    if (status) params.set("status", status);
    api
      .get<PickupRequestListResponse>(`/api/v1/pickups?${params.toString()}`)
      .then((result) => {setData(result); setError(null);})
      .catch((err) => setError(err instanceof Error ? err.message : "Could not load hospital pickups."))
      .finally(() => setLoading(false));
  }, [status]);

  const vehicleIds = data?.items.map((item) => item.assigned_vehicle?.id).filter((id): id is string => Boolean(id)) ?? [];
  useTrackingWebSocket({
    vehicleIds,
    enabled: vehicleIds.length > 0,
    onEvent: (event) => {
      if (["pickup.status.updated", "destination.received", "waste.processing.completed", "waste.status.updated"].includes(event.event ?? "")) {
        const params = new URLSearchParams({ page: "1", page_size: "20" });
        if (status) params.set("status", status);
        void api.get<PickupRequestListResponse>(`/api/v1/pickups?${params.toString()}`)
          .then((result) => {setData(result); setError(null);})
          .catch((err) => setError(err instanceof Error ? err.message : "Could not refresh hospital pickups."));
      }
    },
  });

  return (
    <div>
      <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
        <div>
          <h1 className="font-display text-2xl font-semibold text-charcoal">Pickups</h1>
          <p className="mt-1.5 text-[14px] text-slate">
            Every pickup you&apos;ve requested, from scheduling through collection.
          </p>
        </div>
        <Button asChild>
          <Link href="/dashboard/pickups/new">
            <Plus size={16} /> Request pickup
          </Link>
        </Button>
      </div>

      <div className="mt-6">
        <Select
          value={status}
          onChange={(e) => setStatus(e.target.value as PickupStatus | "")}
          className="sm:w-52"
        >
          <option value="">All statuses</option>
          {Object.entries(PICKUP_STATUS_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </Select>
      </div>

      {error && <div role="alert" className="mt-4 rounded-lg border border-signal-rust/20 bg-signal-rust-bg p-3 text-sm text-signal-rust">
        {error} <Button variant="outline" size="sm" onClick={() => window.location.reload()}>Retry / refresh</Button>
      </div>}
      <div className="mt-6 overflow-hidden rounded-2xl border border-mist-deep bg-paper">
        {loading ? (
          <div className="p-10 text-center text-[14px] text-slate">Loading…</div>
        ) : !data || data.items.length === 0 ? (
          <div className="flex flex-col items-center gap-3 p-14 text-center">
            <CalendarClock size={28} className="text-slate-light" strokeWidth={1.5} />
            <p className="text-[14px] text-slate">
              {status ? "No pickups match this filter." : "No pickups requested yet."}
            </p>
            {!status && (
              <Button size="sm" variant="outline" asChild>
                <Link href="/dashboard/pickups/new">Request your first pickup</Link>
              </Button>
            )}
          </div>
        ) : (
          <table className="w-full text-left text-[13.5px]">
            <thead>
              <tr className="border-b border-mist-deep bg-mist/50 text-[11.5px] uppercase tracking-wide text-slate-light">
                <th className="px-5 py-3 font-medium">Batches</th>
                <th className="px-5 py-3 font-medium">Priority</th>
                <th className="px-5 py-3 font-medium">Vehicle</th>
                <th className="px-5 py-3 font-medium">Scheduled</th>
                <th className="px-5 py-3 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((pickup) => (
                <tr
                  key={pickup.id}
                  className="cursor-pointer border-b border-mist-deep last:border-0 hover:bg-mist/40"
                  onClick={() => router.push(`/dashboard/pickups/${pickup.id}`)}
                >
                  <td className="px-5 py-3 text-charcoal">
                    {pickup.waste_records.length} batch
                    {pickup.waste_records.length !== 1 ? "es" : ""}
                  </td>
                  <td className="px-5 py-3">
                    <PickupPriorityBadge priority={pickup.priority} />
                  </td>
                  <td className="font-data px-5 py-3 text-charcoal">
                    {pickup.assigned_vehicle?.vehicle_code ?? "—"}
                  </td>
                  <td className="px-5 py-3 text-slate">
                    {pickup.scheduled_at
                      ? new Date(pickup.scheduled_at).toLocaleString()
                      : "—"}
                  </td>
                  <td className="px-5 py-3">
                    <PickupStatusBadge status={pickup.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
