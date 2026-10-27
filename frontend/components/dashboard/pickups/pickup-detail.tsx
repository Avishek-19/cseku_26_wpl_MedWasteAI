"use client";

import { ArrowLeft,Copy,QrCode,RefreshCw,XCircle } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { useCallback,useEffect,useState } from "react";

import {
PickupPriorityBadge,
PickupStatusBadge,
} from "@/components/dashboard/pickups/pickup-badges";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/hooks/use-auth";
import { api,ApiError } from "@/lib/api";
import type { PickupRequest } from "@/types/waste";

export function PickupDetail({ pickupId }: { pickupId: string }) {
  const { user } = useAuth();
  const [pickup, setPickup] = useState<PickupRequest | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [handover, setHandover] = useState<{handover_qr: string; qr_svg_data_url: string; warning: string} | null>(null);
  const [qrLoading, setQrLoading] = useState(false);
  const revealHandover = async () => {
    setQrLoading(true);
    setError(null);
    try {
      const info = await api.get<{handover_qr:string; qr_svg_data_url:string; warning:string}>(
        `/api/v1/pickups/${encodeURIComponent(pickupId)}/handover-qr`
      );
      setHandover(info);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not retrieve handover QR.");
    } finally { setQrLoading(false); }
  };

  const load = useCallback(() => {
    setLoading(true);
    api
      .get<PickupRequest>(`/api/v1/pickups/${pickupId}`)
      .then(setPickup)
      .catch(() => setNotFound(true))
      .finally(() => setLoading(false));
  }, [pickupId]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, [load]);

  const retryAssign = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.post(`/api/v1/pickups/${pickupId}/assign`);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't assign a vehicle.");
    } finally {
      setBusy(false);
    }
  };

  const cancel = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.post(`/api/v1/pickups/${pickupId}/cancel`, {});
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't cancel this pickup.");
    } finally {
      setBusy(false);
    }
  };

  if (loading) return <p className="text-[14px] text-slate">Loading…</p>;

  if (notFound || !pickup) {
    return (
      <div className="mx-auto max-w-lg text-center">
        <p className="text-[14px] text-slate">This pickup couldn&apos;t be found.</p>
        <Link href="/dashboard/pickups" className="mt-3 inline-block text-[13.5px] text-emerald">
          Back to pickups
        </Link>
      </div>
    );
  }

  const isHospital = user?.role === "hospital";
  const canCancel = isHospital && (pickup.status === "requested" || pickup.status === "assigned");
  const canRetryAssign = isHospital && pickup.status === "requested";

  return (
    <div className="mx-auto max-w-2xl">
      <Link
        href="/dashboard/pickups"
        className="inline-flex items-center gap-1.5 text-[13px] text-slate hover:text-charcoal"
      >
        <ArrowLeft size={14} /> Back to pickups
      </Link>

      {error && (
        <div className="mt-4 rounded-lg border border-signal-rust/20 bg-signal-rust-bg px-3.5 py-2.5 text-[13px] text-signal-rust">
          {error}
        </div>
      )}

      <div className="manifest-edge mt-4 rounded-2xl border border-mist-deep bg-white p-7">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <PickupStatusBadge status={pickup.status} />
            <PickupPriorityBadge priority={pickup.priority} />
          </div>
          <span className="text-[12.5px] text-slate-light">
            Requested {new Date(pickup.created_at).toLocaleString()}
          </span>
        </div>

        <dl className="mt-6 grid grid-cols-2 gap-5">
          <div>
            <dt className="text-[12px] text-slate-light">Scheduled</dt>
            <dd className="mt-0.5 text-[14px] text-charcoal">
              {pickup.scheduled_at ? new Date(pickup.scheduled_at).toLocaleString() : "Not yet"}
            </dd>
          </div>
          <div>
            <dt className="text-[12px] text-slate-light">Vehicle</dt>
            <dd className="font-data mt-0.5 text-[14px] text-charcoal">
              {pickup.assigned_vehicle?.vehicle_code ?? "Unassigned"}
            </dd>
          </div>
          {pickup.collected_at && (
            <div>
              <dt className="text-[12px] text-slate-light">Collected</dt>
              <dd className="mt-0.5 text-[14px] text-charcoal">
                {new Date(pickup.collected_at).toLocaleString()}
              </dd>
            </div>
          )}
          {pickup.cancelled_at && (
            <div className="col-span-2">
              <dt className="text-[12px] text-slate-light">Cancelled</dt>
              <dd className="mt-0.5 text-[14px] text-charcoal">
                {new Date(pickup.cancelled_at).toLocaleString()}
                {pickup.cancellation_reason && ` — ${pickup.cancellation_reason}`}
              </dd>
            </div>
          )}
          {pickup.notes && (
            <div className="col-span-2">
              <dt className="text-[12px] text-slate-light">Notes</dt>
              <dd className="mt-0.5 text-[14px] text-charcoal">{pickup.notes}</dd>
            </div>
          )}
        </dl>

        <div className="manifest-edge mt-7 bg-mist/60 px-1 py-6">
          <p className="px-6 text-[12.5px] font-medium uppercase tracking-wide text-slate-light">
            Batches ({pickup.waste_records.length})
          </p>
          <ul className="mt-3 space-y-1.5 px-6">
            {pickup.waste_records.map((r) => (
              <li key={r.id} className="flex justify-between text-[13px] text-charcoal">
                <Link
                  href={`/dashboard/waste/${r.id}`}
                  className="font-data hover:text-emerald hover:underline"
                >
                  {r.waste_code}
                </Link>
                <span className="text-slate">
                  {r.category.name} · {r.quantity} {r.unit}
                </span>
              </li>
            ))}
          </ul>
        </div>

        {isHospital && pickup.status === "assigned" && (
          <section className="mt-6 rounded-xl border border-mist-deep bg-mist/40 p-4">
            <div className="flex items-center gap-2 font-semibold text-charcoal"><QrCode size={18}/> Hospital handover QR</div>
            <p className="mt-2 text-xs text-slate">Show this reference only to the assigned driver, in person at the hospital. QR is not GPS arrival proof.</p>
            {!handover ? (
              <Button type="button" variant="outline" className="mt-3" onClick={() => void revealHandover()} disabled={qrLoading}>
                {qrLoading ? "Retrieving…" : "Reveal handover QR"}
              </Button>
            ) : (
              <div className="mt-4 space-y-3">
                <Image src={handover.qr_svg_data_url} width={220} height={220} unoptimized alt="Handover QR for the assigned driver" className="rounded-lg bg-white p-2" />
                <p className="break-all font-data text-xs text-charcoal">{handover.handover_qr}</p>
                <Button type="button" variant="outline" size="sm" onClick={() => {void navigator.clipboard.writeText(handover.handover_qr).catch(() => setError("Clipboard not available; copy the reference manually."));}}>
                  <Copy size={14}/> Copy reference
                </Button>
                <p className="text-xs text-slate">{handover.warning}</p>
              </div>
            )}
          </section>
        )}

        {(canCancel || canRetryAssign) && (
          <div className="mt-6 flex flex-wrap gap-2">
            {canRetryAssign && (
              <Button size="sm" variant="outline" onClick={retryAssign} disabled={busy}>
                <RefreshCw size={14} />
                Try assigning again
              </Button>
            )}
            {canCancel && (
              <Button size="sm" variant="outline" onClick={cancel} disabled={busy}>
                <XCircle size={14} />
                Cancel pickup
              </Button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
