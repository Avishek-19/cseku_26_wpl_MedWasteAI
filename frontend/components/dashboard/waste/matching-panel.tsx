"use client";

import { AlertCircle,CheckCircle2,MapPin,ShieldCheck,Sparkles } from "lucide-react";
import { useEffect,useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api,ApiError } from "@/lib/api";
import type { MatchingRecord,WasteRecord } from "@/types/waste";

export function MatchingPanel({
  record,
  onRecordUpdated,
}: {
  record: WasteRecord;
  onRecordUpdated: () => void;
}) {
  const [history, setHistory] = useState<MatchingRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadHistory = () => {
    setLoading(true);
    api
      .get<MatchingRecord[]>(`/api/v1/waste/${record.id}/matching`)
      .then(setHistory)
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadHistory();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [record.id]);

  const notYetRiskAssessed = record.status === "reported" || record.status === "classified";
  const latest = history[0] ?? null;

  const runMatching = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.post(`/api/v1/waste/${record.id}/matching/run`);
      loadHistory();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't run matching.");
    } finally {
      setBusy(false);
    }
  };

  const confirm = async (destinationId?: string) => {
    setBusy(true);
    setError(null);
    try {
      await api.post(`/api/v1/waste/${record.id}/matching/confirm`, {
        destination_id: destinationId,
      });
      loadHistory();
      onRecordUpdated();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't confirm this match.");
    } finally {
      setBusy(false);
    }
  };

  if (notYetRiskAssessed) {
    return (
      <div className="manifest-edge mt-6 rounded-2xl border border-dashed border-mist-deep bg-paper p-7">
        <h2 className="font-display text-lg font-semibold text-charcoal">Destination match</h2>
        <p className="mt-2 text-[13.5px] text-slate">
          Confirm a risk assessment first — the platform will determine the required processing and then find a verified Waste Processing Facility with the required capability.
        </p>
      </div>
    );
  }

  const confirmedId = latest?.confirmed_facility_id ?? null;

  return (
    <div className="manifest-edge mt-6 rounded-2xl border border-mist-deep bg-paper p-7">
      <h2 className="font-display text-lg font-semibold text-charcoal">Destination match</h2>

      {loading ? (
        <p className="mt-4 text-[13.5px] text-slate">Loading…</p>
      ) : (
        <>
          {error && (
            <div className="mt-4 flex items-start gap-2 rounded-lg border border-signal-rust/20 bg-signal-rust-bg px-3.5 py-2.5 text-[13px] text-signal-rust">
              <AlertCircle size={15} className="mt-0.5 shrink-0" />
              {error}
            </div>
          )}

          {!latest && (
            <div className="mt-4">
              <p className="text-[13.5px] text-slate">
                Find a Waste Processing Facility for this batch by waste compatibility, required processing, verification, capacity, availability, and location.
              </p>
              <Button size="sm" className="mt-3" onClick={runMatching} disabled={busy}>
                <Sparkles size={14} />
                {busy ? "Matching…" : "Find a destination"}
              </Button>
            </div>
          )}

          {latest && (
            <div className="mt-4">
              <p className="text-[13px] text-slate">{latest.explanation}</p>
              {latest.processing_method && <div className="mt-3 rounded-lg bg-mist px-3 py-2 text-[12.5px] text-slate">Required processing: <strong>{latest.processing_method}</strong> · Decision: {latest.decision_method.replace(/_/g, " ")}{latest.requires_human_verification ? " · Human verification required" : ""}</div>}

              {latest.candidates.length === 0 ? (
                <div className="mt-4 rounded-xl border border-signal-amber/20 bg-signal-amber-bg p-4">
                  <p className="text-[13px] font-medium text-charcoal">No suitable facility found</p>
                  <p className="mt-1 text-[12.5px] text-slate">The batch is marked for manual review. Do not assign an incompatible facility.</p>
                  <div className="mt-3 flex flex-wrap gap-2">
                  <Button size="sm" variant="outline" onClick={runMatching} disabled={busy}>
                    <Sparkles size={14} />
                    Try again
                  </Button>
                  </div>
                </div>
              ) : (
                <ul className="mt-4 space-y-2.5">
                  {latest.candidates.map((c, i) => {
                    const isConfirmedChoice = confirmedId === c.id;
                    return (
                      <li
                        key={c.id}
                        className={
                          "rounded-xl border p-4 " +
                          (isConfirmedChoice
                            ? "border-emerald/30 bg-signal-emerald-bg"
                            : "border-mist-deep bg-mist/40")
                        }
                      >
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <span className="text-[14px] font-medium text-charcoal">
                              {c.name}
                            </span>
                            {i === 0 && !latest.is_confirmed && (
                              <Badge variant="emerald">Recommended</Badge>
                            )}
                            {isConfirmedChoice && (
                              <span className="flex items-center gap-1 text-[12px] text-emerald-dim">
                                <CheckCircle2 size={12} /> Confirmed
                              </span>
                            )}
                          </div>
                          <span className="font-data text-[13px] text-charcoal">
                            {c.score}/100
                          </span>
                        </div>
                        <div className="mt-1.5 flex items-center gap-3 text-[12px] text-slate-light">
                          <span className="flex items-center gap-1">
                            <MapPin size={11} /> {c.city}
                          </span>
                          {c.is_verified && (
                            <span className="flex items-center gap-1">
                              <ShieldCheck size={11} /> Verified
                            </span>
                          )}
                        </div>
                        {c.processing_method && <p className="mt-2 text-[12px] font-medium text-emerald">Processing: {c.processing_method}</p>}
                        <p className="mt-1 text-[12px] text-slate-light">{c.reasons.join(" · ")}</p>

                        {!latest.is_confirmed && (
                          <Button
                            size="sm"
                            variant={i === 0 ? "default" : "outline"}
                            className="mt-3"
                            onClick={() => confirm(c.id)}
                            disabled={busy}
                          >
                            Confirm {c.name}
                          </Button>
                        )}
                      </li>
                    );
                  })}
                </ul>
              )}

              {latest.is_confirmed && (
                <p className="mt-4 text-[12px] text-slate-light">This facility assignment is locked for the current pickup workflow. Reassignment should be performed by the platform workflow if the facility becomes unavailable.</p>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
