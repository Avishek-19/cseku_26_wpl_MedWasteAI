
"use client";

import { useDeferredEffect } from "@/hooks/use-deferred-effect";
import { ManualReceive } from "@/components/dashboard/manual-receive";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/hooks/use-auth";
import { useTrackingWebSocket } from "@/hooks/use-tracking-websocket";
import { api, ApiError } from "@/lib/api";
import type {
  ReceiveWasteResponse,
  WasteRecord,
} from "@/types/waste";

import {
  AlertTriangle,
  CheckCircle2,
  Factory,
  MapPin,
  Play,
  ShieldCheck,
} from "lucide-react";

import { useCallback, useState } from "react";

type FacilityProfile = {
  id: string;
  name: string;
  facility_type: string;
  processing_services: string[];
  availability_status: string;
  is_verified: boolean;
  capacity_kg: string;
  current_utilization_kg: string;
  available_capacity_kg: string;
  other_services: string[];
};

type Processing = {
  id: string;
  waste_record_id: string;
  facility_id: string;
  processing_method: string;
  status: string;
  proof_note: string | null;
};

const LABELS: Record<string, string> = {
  AUTOCLAVE: "Autoclaving",
  INCINERATION: "Incineration",
  CHEMICAL_TREATMENT: "Chemical treatment",
  MICROWAVE_TREATMENT: "Microwave treatment",
  SHARPS_DESTRUCTION: "Sharps destruction",
  PHARMACEUTICAL_TREATMENT: "Pharmaceutical treatment",
  RECYCLING: "Recycling",
  MATERIAL_RECOVERY: "Material recovery",
  FINAL_DISPOSAL: "Final disposal",
  SPECIALIZED_TREATMENT: "Specialized treatment",
};

export function IncomingShipments() {
  const { user } = useAuth();

  const [shipments, setShipments] = useState<WasteRecord[]>([]);

  const [profile, setProfile] =
    useState<FacilityProfile | null>(null);

  const [processing, setProcessing] = useState<
    Record<string, Processing | null>
  >({});

  const [documents, setDocuments] = useState<
    Record<string, File | null>
  >({});

  const [loading, setLoading] = useState(true);

  const [quantities, setQuantities] = useState<
    Record<string, string>
  >({});

  const [proofs, setProofs] = useState<
    Record<string, string>
  >({});

  const [busyId, setBusyId] = useState<string | null>(null);

  const [error, setError] = useState<string | null>(null);

  const [results, setResults] = useState<
    Record<string, ReceiveWasteResponse>
  >({});

  // Load facility shipments and their processing records.
  const load = useCallback(async () => {
    if (!user) return;

    setLoading(true);
    setError(null);

    try {
      const incoming = await api.get<WasteRecord[]>(
        "/api/v1/destinations/incoming"
      );

      setShipments(incoming);

      if (user.role === "facility") {
        const facility = await api.get<FacilityProfile>(
          "/api/v1/destinations/facility-profile"
        );

        setProfile(facility);
      } else {
        setProfile(null);
      }

      const processingEntries = await Promise.all(
        incoming
          .filter((record) =>
            [
              "destination_received",
              "processing",
              "proof_submitted",
              "verified",
              "completed",
            ].includes(record.status)
          )
          .map(async (record) => {
            const result = await api
              .get<Processing | null>(
                `/api/v1/processing/${record.id}`
              )
              .catch(() => null);

            return [record.id, result] as const;
          })
      );

      setProcessing(
        Object.fromEntries(processingEntries)
      );
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Couldn't load facility data."
      );
    } finally {
      setLoading(false);
    }
  }, [user]);

  // Initial load.
  useDeferredEffect(() => {
    void load();
  }, [load]);

  // Subscribe to live workflow updates.
  const vehicleIds = shipments
    .map(
      (record) =>
        (record as WasteRecord & {
          vehicle_id?: string;
        }).vehicle_id
    )
    .filter((id): id is string => Boolean(id));

  useTrackingWebSocket({
    vehicleIds,
    enabled: vehicleIds.length > 0,

    onEvent: (event) => {
      if (
        [
          "vehicle.destination.arrived",
          "destination.received",
          "waste.processing.started",
          "waste.processing.proof_submitted",
          "waste.processing.completed",
        ].includes(event.event ?? "")
      ) {
        void load();
      }
    },
  });

  // Existing verified-arrival receipt.
  const receive = async (recordId: string) => {
    setBusyId(recordId);
    setError(null);

    try {
      const qty = quantities[recordId];

      const result = await api.post<ReceiveWasteResponse>(
        `/api/v1/destinations/${recordId}/receive`,
        {
          ...(qty
            ? { received_quantity: qty }
            : {}),
        }
      );

      setResults((previous) => ({
        ...previous,
        [recordId]: result,
      }));

      await load();
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Couldn't confirm receipt."
      );
    } finally {
      setBusyId(null);
    }
  };

  // Start waste processing.
  const startProcessing = async (
    record: WasteRecord
  ) => {
    setBusyId(record.id);
    setError(null);

    try {
      const method =
        record.processing_method ||
        profile?.processing_services?.[0];

      if (!method) {
        throw new Error(
          "No processing capability is configured for this facility."
        );
      }

      const result = await api.post<Processing>(
        `/api/v1/processing/${record.id}/start`,
        {
          processing_method: method,
        }
      );

      setProcessing((previous) => ({
        ...previous,
        [record.id]: result,
      }));

      await load();
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Couldn't start processing."
      );
    } finally {
      setBusyId(null);
    }
  };

  // Submit processing proof and optional PDF/image evidence.
  const submitProof = async (
    recordId: string
  ) => {
    setBusyId(recordId);
    setError(null);

    try {
      const proof =
        proofs[recordId]?.trim() ?? "";

      if (proof.length < 3) {
        throw new Error(
          "Proof note must be at least 3 characters."
        );
      }

      const evidence = documents[recordId];

      if (evidence) {
        await api.upload(
          `/api/v1/processing/${recordId}/document`,
          evidence
        );
      }

      const result = await api.post<Processing>(
        `/api/v1/processing/${recordId}/proof`,
        {
          proof_note: proof,
        }
      );

      setProcessing((previous) => ({
        ...previous,
        [recordId]: result,
      }));

      setDocuments((previous) => ({
        ...previous,
        [recordId]: null,
      }));

      await load();
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Couldn't submit proof.";

      setError(message);
    } finally {
      setBusyId(null);
    }
  };

  // Complete treatment after proof submission.
  const complete = async (
    recordId: string
  ) => {
    setBusyId(recordId);
    setError(null);

    try {
      const result = await api.post<Processing>(
        `/api/v1/processing/${recordId}/complete`
      );

      setProcessing((previous) => ({
        ...previous,
        [recordId]: result,
      }));

      await load();
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Couldn't complete processing."
      );
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="mx-auto max-w-5xl">
      {/* Page header */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="font-data text-[11px] uppercase tracking-[0.14em] text-emerald">
            Waste Processing Facility
          </p>

          <h1 className="mt-2 font-display text-2xl font-semibold text-charcoal">
            Incoming & processing
          </h1>

          <p className="mt-1.5 text-[14px] text-slate">
            Receive assigned waste, process it using an
            authorized capability, submit proof, and
            complete the chain of custody.
          </p>
        </div>

        {profile && (
          <div className="rounded-xl border border-mist-deep bg-paper px-4 py-3 text-right text-[12px]">
            <div className="flex items-center justify-end gap-1.5 font-medium text-charcoal">
              <Factory size={14} />
              {profile.name}
            </div>

            <div className="mt-1 flex items-center justify-end gap-1.5 text-slate">
              <ShieldCheck size={13} />

              {profile.is_verified
                ? "Verified"
                : "Pending verification"}
            </div>
          </div>
        )}
      </div>

      {/* Facility processing capabilities */}
      {profile && (
        <div className="mt-5 rounded-2xl border border-mist-deep bg-paper p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-[13px] font-medium text-charcoal">
                Configured capabilities
              </p>

              <p className="mt-1 text-[12px] text-slate">
                Only these services can be used
                to process assigned waste.
              </p>
            </div>

            <span className="text-[12px] text-slate">
              Capacity{" "}
              {profile.current_utilization_kg} /{" "}
              {profile.capacity_kg} kg ·{" "}
              {profile.available_capacity_kg} kg available
            </span>
          </div>

          <div className="mt-3 flex flex-wrap gap-2">
            {profile.processing_services.length
              ? profile.processing_services.map(
                  (service) => (
                    <span
                      key={service}
                      className="rounded-full bg-mist px-3 py-1 text-[12px] text-slate"
                    >
                      {LABELS[service] ?? service}
                    </span>
                  )
                )
              : null}

            {(profile.other_services ?? []).map(
              (service) => (
                <span
                  key={service}
                  className="rounded-full border border-mist-deep bg-paper px-3 py-1 text-[12px] text-slate"
                >
                  {service}
                </span>
              )
            )}

            {!profile.processing_services.length &&
              !(profile.other_services ?? []).length && (
                <span className="text-[12px] text-signal-rust">
                  No processing service configured.
                </span>
              )}
          </div>
        </div>
      )}

      {/* Error message */}
      {error && (
        <div className="mt-4 rounded-lg border border-signal-rust/20 bg-signal-rust-bg px-3.5 py-2.5 text-[13px] text-signal-rust">
          {error}
        </div>
      )}

      {/* Incoming shipments */}
      <div className="mt-6 space-y-3">
        {loading ? (
          <p className="text-[14px] text-slate">
            Loading…
          </p>
        ) : shipments.length === 0 ? (
          <div className="flex flex-col items-center gap-3 rounded-2xl border border-mist-deep bg-paper p-14 text-center">
            <Factory
              size={28}
              className="text-slate-light"
              strokeWidth={1.5}
            />

            <p className="text-[14px] text-slate">
              No assigned shipments are currently in transit.
            </p>

            <p className="max-w-md text-[12px] text-slate-light">
              A hospital must confirm a facility match and
              a collector must start transit before the
              shipment appears here.
            </p>
          </div>
        ) : (
          shipments.map((record) => {
            const result = results[record.id];
            const proc = processing[record.id];

            return (
              <div
                key={record.id}
                className="manifest-edge rounded-2xl border border-mist-deep bg-paper p-6"
              >
                {/* Shipment header */}
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <span className="font-data text-[14px] text-charcoal">
                    {record.waste_code}
                  </span>

                  <span className="flex items-center gap-1 text-[12px] text-slate-light">
                    <MapPin size={12} />
                    {record.status === "in_transit"
                      ? "In transit"
                      : record.status}
                  </span>
                </div>

                <p className="mt-1 text-[13px] text-slate">
                  {record.category.name} · reported{" "}
                  {record.quantity} {record.unit}
                </p>

                {record.processing_method && (
                  <p className="mt-2 text-[12.5px] font-medium text-emerald">
                    Required processing:{" "}
                    {LABELS[record.processing_method] ??
                      record.processing_method}
                  </p>
                )}

                {/* Receipt result */}
                {result ? (
                  <div
                    className={`mt-4 flex items-start gap-2 rounded-lg px-3.5 py-2.5 text-[13px] ${
                      result.incident
                        ? "border border-signal-amber/20 bg-signal-amber-bg text-signal-amber"
                        : "border border-emerald/20 bg-signal-emerald-bg text-emerald-dim"
                    }`}
                  >
                    {result.incident ? (
                      <AlertTriangle
                        size={15}
                        className="mt-0.5 shrink-0"
                      />
                    ) : (
                      <CheckCircle2
                        size={15}
                        className="mt-0.5 shrink-0"
                      />
                    )}

                    <span>
                      Received {result.received_quantity}{" "}
                      {record.unit} (
                      {result.variance_percent}% variance).
                      {result.incident &&
                        ` ${result.incident.description}`}
                    </span>
                  </div>
                ) : record.status === "in_transit" ? (
                  <div className="mt-4 flex flex-wrap items-end gap-3">
                    <div>
                      <label className="mb-1.5 block text-[12px] text-slate-light">
                        Received quantity ({record.unit})
                      </label>

                      <Input
                        type="number"
                        min="0"
                        step="0.01"
                        placeholder={String(
                          record.quantity
                        )}
                        value={
                          quantities[record.id] ?? ""
                        }
                        onChange={(event) =>
                          setQuantities((previous) => ({
                            ...previous,
                            [record.id]:
                              event.target.value,
                          }))
                        }
                        className="w-40"
                      />
                    </div>

                    <Button
                      size="sm"
                      onClick={() =>
                        receive(record.id)
                      }
                      disabled={
                        busyId === record.id
                      }
                    >
                      {busyId === record.id
                        ? "Confirming…"
                        : "Confirm GPS-verified receipt"}
                    </Button>
                  </div>
                ) : null}

                {/* New manual facility receipt */}
                {record.status === "in_transit" &&
                  !result && (
                    <ManualReceive
                      recordId={record.id}
                      quantity={record.quantity}
                      onReceived={() => load()}
                    />
                  )}

                {/* Start processing */}
                {record.status ===
                  "destination_received" &&
                  !proc && (
                    <Button
                      size="sm"
                      className="mt-4"
                      onClick={() =>
                        startProcessing(record)
                      }
                      disabled={
                        busyId === record.id
                      }
                    >
                      <Play size={14} />

                      {busyId === record.id
                        ? "Starting…"
                        : `Start ${
                            LABELS[
                              record.processing_method ?? ""
                            ] ?? "processing"
                          }`}
                    </Button>
                  )}

                {/* Processing form */}
                {proc &&
                  proc.status === "processing" && (
                    <div className="mt-4 space-y-3">
                      <div className="rounded-lg bg-mist px-3 py-2 text-[12.5px] text-slate">
                        Processing:{" "}
                        <strong>
                          {LABELS[
                            proc.processing_method
                          ] ??
                            proc.processing_method}
                        </strong>
                      </div>

                      <div>
                        <label className="mb-1.5 block text-[12px] text-slate-light">
                          Processing proof / batch note
                          (min 3 characters)
                        </label>

                        <textarea
                          value={
                            proofs[record.id] ?? ""
                          }
                          onChange={(event) =>
                            setProofs((previous) => ({
                              ...previous,
                              [record.id]:
                                event.target.value,
                            }))
                          }
                          className="min-h-20 w-full rounded-lg border border-mist-deep bg-paper px-3 py-2 text-[13px] outline-none focus:border-emerald/40"
                          placeholder="Describe the completed treatment, recycling, recovery or disposal evidence."
                        />
                      </div>

                      <label className="block text-[12px] text-slate">
                        Processing document
                        (PDF or image, max 10 MB)

                        <input
                          type="file"
                          accept="application/pdf,image/jpeg,image/png,image/webp"
                          className="mt-1 block w-full text-sm"
                          onChange={(event) =>
                            setDocuments(
                              (previous) => ({
                                ...previous,
                                [record.id]:
                                  event.target
                                    .files?.[0] ??
                                  null,
                              })
                            )
                          }
                        />
                      </label>

                      <p className="text-xs text-slate">
                        The processing note and
                        document will be visible
                        to the hospital under
                        this waste batch.
                      </p>

                      <Button
                        size="sm"
                        onClick={() =>
                          submitProof(record.id)
                        }
                        disabled={
                          busyId === record.id
                        }
                      >
                        {busyId === record.id
                          ? "Submitting…"
                          : "Submit proof"}
                      </Button>
                    </div>
                  )}

                {/* Proof submitted */}
                {proc &&
                  proc.status ===
                    "proof_submitted" && (
                    <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-emerald/20 bg-signal-emerald-bg px-3.5 py-3">
                      <div className="text-[13px] text-emerald-dim">
                        <CheckCircle2
                          size={14}
                          className="mr-1 inline"
                        />

                        Proof submitted.
                        Ready for verification.
                      </div>

                      <Button
                        size="sm"
                        onClick={() =>
                          complete(record.id)
                        }
                        disabled={
                          busyId === record.id
                        }
                      >
                        {busyId === record.id
                          ? "Completing…"
                          : "Verify & complete"}
                      </Button>
                    </div>
                  )}

                {/* Completed processing */}
                {proc &&
                  proc.status ===
                    "completed" && (
                    <div className="mt-4 rounded-lg border border-emerald/20 bg-signal-emerald-bg px-3.5 py-2.5 text-[13px] text-emerald-dim">
                      <CheckCircle2
                        size={15}
                        className="mr-1 inline"
                      />

                      Processing completed and
                      verified.
                    </div>
                  )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
