"use client";

import { CalendarClock,CheckCircle2,Truck } from "lucide-react";
import Link from "next/link";
import { useEffect,useState } from "react";

import {
PickupPriorityBadge,
PickupStatusBadge,
} from "@/components/dashboard/pickups/pickup-badges";
import { Button } from "@/components/ui/button";
import { useTrackingWebSocket } from "@/hooks/use-tracking-websocket";
import { api,ApiError } from "@/lib/api";
import type { PickupRequest } from "@/types/waste";

export function CollectorPickupsList() {
  const [pickups, setPickups] = useState<PickupRequest[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    api
      .get<PickupRequest[]>("/api/v1/pickups/assigned")
      .then(setPickups)
      .catch((err) => setError(err instanceof Error ? err.message : "Unable to load pickups."))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, []);

  const vehicleIds = pickups
    .map((pickup) => pickup.assigned_vehicle?.id)
    .filter((id): id is string => Boolean(id));

  useTrackingWebSocket({
    vehicleIds,
    enabled: vehicleIds.length > 0,
    onEvent: (event) => {
      if (
        [
          "pickup.status.updated",
          "vehicle.destination.arrived",
          "destination.received",
          "route.completed",
        ].includes(event.event ?? "")
      ) {
        void load();
      }
    },
  });

  const runAction = async (
    id: string,
    action: "start-transit",
    label: string
  ) => {
    setBusyId(id);
    setError(null);
    try {
      await api.post(`/api/v1/pickups/${id}/${action}`);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : `Couldn't ${label}.`);
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div>
      <h1 className="font-display text-2xl font-semibold text-charcoal">
        Assigned pickups
      </h1>
      <p className="mt-1.5 text-[14px] text-slate">
        Batches scheduled for your vehicle, in order of pickup time.
      </p>

      {error && (
        <div className="mt-4 rounded-lg border border-signal-rust/20 bg-signal-rust-bg px-3.5 py-2.5 text-[13px] text-signal-rust">
          {error}
        </div>
      )}

      <div className="mt-6 space-y-3">
        {loading ? (
          <p className="text-[14px] text-slate">Loading…</p>
        ) : pickups.length === 0 ? (
          <div className="flex flex-col items-center gap-3 rounded-2xl border border-mist-deep bg-paper p-14 text-center">
            <CalendarClock size={28} className="text-slate-light" strokeWidth={1.5} />
            <p className="text-[14px] text-slate">
              No pickups assigned to you right now.
            </p>
          </div>
        ) : (
          pickups.map((pickup) => (
            <div
              key={pickup.id}
              className="manifest-edge rounded-2xl border border-mist-deep bg-paper p-6"
            >
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-2.5">
                  <Truck size={16} className="text-slate-light" />
                  <span className="font-data text-[13.5px] text-charcoal">
                    {pickup.assigned_vehicle?.vehicle_code}
                  </span>
                  <PickupPriorityBadge priority={pickup.priority} />
                  <PickupStatusBadge status={pickup.status} />
                </div>
                <span className="text-[12.5px] text-slate">
                  {pickup.scheduled_at
                    ? new Date(pickup.scheduled_at).toLocaleString()
                    : "Unscheduled"}
                </span>
              </div>

              <ul className="mt-4 space-y-1.5">
                {pickup.waste_records.map((r) => (
                  <li
                    key={r.id}
                    className="rounded-lg bg-mist/50 p-3 text-[13px] text-charcoal"
                  >
                    <div className="flex flex-wrap justify-between gap-2">
                      <span className="font-data">{r.waste_code}</span>
                      <span className="text-slate">
                        {r.category.name} · {r.quantity} {r.unit}
                      </span>
                    </div>
                    <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-slate-light">
                      <span>Risk/status: {r.status.replaceAll("_", " ")}</span>
                      {r.processing_method && (
                        <span>
                          Processing: {r.processing_method.replaceAll("_", " ")}
                        </span>
                      )}
                      {r.assigned_facility_name && (
                        <span>
                          Destination:{" "}
                          <strong className="font-medium text-charcoal">
                            {r.assigned_facility_name}
                          </strong>
                        </span>
                      )}
                    </div>
                  </li>
                ))}
              </ul>

              {pickup.notes && (
                <p className="mt-3 text-[12.5px] italic text-slate">
                  Note: {pickup.notes}
                </p>
              )}

              {pickup.status === "assigned" && (
                <Button size="sm" className="mt-4" asChild>
                  <Link href={`/dashboard/handover?pickup_id=${encodeURIComponent(pickup.id)}`}>
                    <CheckCircle2 size={14} /> Verify arrival &amp; handover
                  </Link>
                </Button>
              )}

              {pickup.status === "collected" && (
                <div className="mt-4 flex flex-col gap-2">
                  <p className="text-[12.5px] text-slate">
                    Collected — start transit to send this batch to the confirmed
                    Treatment Facility.
                  </p>
                  <Button
                    size="sm"
                    onClick={() =>
                      runAction(
                        pickup.id,
                        "start-transit",
                        "start transit to the treatment facility"
                      )
                    }
                    disabled={busyId === pickup.id}
                  >
                    <Truck size={14} />
                    {busyId === pickup.id ? "Starting…" : "Start transit"}
                  </Button>
                </div>
              )}

              {pickup.status === "in_transit" && (
                <p className="mt-4 text-[12.5px] text-slate-light">
                  On its way — the destination will confirm receipt.
                </p>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}