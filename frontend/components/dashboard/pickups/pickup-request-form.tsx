"use client";

import { AlertCircle,ArrowRight } from "lucide-react";
import { useRouter,useSearchParams } from "next/navigation";
import { useEffect,useState } from "react";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { api,ApiError } from "@/lib/api";
import type { PickupPriority,PickupRequest,WasteRecordListResponse } from "@/types/waste";
import { PICKUP_PRIORITY_LABELS } from "@/types/waste";

export function PickupRequestForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const preselected = searchParams.get("waste_record_id");

  const [eligible, setEligible] = useState<WasteRecordListResponse | null>(null);
  const [selected, setSelected] = useState<Set<string>>(
    new Set(preselected ? [preselected] : [])
  );
  const [priority, setPriority] = useState<PickupPriority>("normal");
  const [notes, setNotes] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<WasteRecordListResponse>("/api/v1/waste?status=risk_assessed&page_size=100")
      .then(setEligible)
      .catch((err) => setError(err instanceof Error ? err.message : "Could not load eligible waste records."))
      .finally(() => setLoading(false));
  }, []);

  const toggle = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const onSubmit = async () => {
    setError(null);
    if (selected.size === 0) {
      setError("Select at least one waste batch.");
      return;
    }
    setSubmitting(true);
    try {
      const pickup = await api.post<PickupRequest>("/api/v1/pickups", {
        waste_record_ids: Array.from(selected),
        priority,
        notes: notes || undefined,
      });
      router.push(`/dashboard/pickups/${pickup.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't request this pickup.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="font-display text-2xl font-semibold text-charcoal">Request pickup</h1>
      <p className="mt-1.5 text-[14px] text-slate">
        Only risk-assessed batches can be scheduled for pickup.
      </p>

      <div className="manifest-edge mt-7 space-y-5 rounded-2xl border border-mist-deep bg-paper p-7">
        {error && (
          <div className="flex items-start gap-2 rounded-lg border border-signal-rust/20 bg-signal-rust-bg px-3.5 py-2.5 text-[13px] text-signal-rust">
            <AlertCircle size={15} className="mt-0.5 shrink-0" />
            {error}
          </div>
        )}

        <div>
          <Label>Waste batches</Label>
          {loading ? (
            <p className="text-[13.5px] text-slate">Loading eligible batches…</p>
          ) : !eligible || eligible.items.length === 0 ? (
            <p className="rounded-lg border border-dashed border-mist-deep px-3.5 py-3 text-[13px] text-slate">
              No risk-assessed batches are ready for pickup yet.
            </p>
          ) : (
            <div className="space-y-2 rounded-lg border border-mist-deep p-2">
              {eligible.items.map((record) => (
                <label
                  key={record.id}
                  className="flex cursor-pointer items-center gap-3 rounded-md px-2.5 py-2 hover:bg-mist"
                >
                  <input
                    type="checkbox"
                    checked={selected.has(record.id)}
                    onChange={() => toggle(record.id)}
                    className="h-4 w-4 accent-emerald"
                  />
                  <div className="flex-1">
                    <span className="font-data text-[13px] text-charcoal">
                      {record.waste_code}
                    </span>
                    <span className="ml-2 text-[12.5px] text-slate">
                      {record.category.name} · {record.quantity} {record.unit}
                    </span>
                  </div>
                </label>
              ))}
            </div>
          )}
        </div>

        <div>
          <Label htmlFor="priority">Priority</Label>
          <Select
            id="priority"
            value={priority}
            onChange={(e) => setPriority(e.target.value as PickupPriority)}
          >
            {Object.entries(PICKUP_PRIORITY_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </Select>
          <p className="mt-1.5 text-[12px] text-slate-light">
            Urgent and emergency pickups are scheduled immediately.
          </p>
        </div>

        <div>
          <Label htmlFor="notes">Notes (optional)</Label>
          <Textarea
            id="notes"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="e.g. Use the loading dock entrance"
          />
        </div>

        <Button
          className="group w-full"
          onClick={onSubmit}
          disabled={submitting || selected.size === 0}
        >
          {submitting ? "Requesting…" : "Request pickup"}
          {!submitting && (
            <ArrowRight size={16} className="transition-transform group-hover:translate-x-0.5" />
          )}
        </Button>
      </div>
    </div>
  );
}
