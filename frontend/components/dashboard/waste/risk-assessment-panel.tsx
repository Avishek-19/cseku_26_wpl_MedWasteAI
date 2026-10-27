"use client";

import { AlertCircle,CheckCircle2,History,Recycle,ShieldAlert } from "lucide-react";
import { useEffect,useState } from "react";

import { RiskLevelBadge } from "@/components/dashboard/waste/risk-level-badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { api,ApiError } from "@/lib/api";
import type {
RiskLevel,
SuggestedHandling,
WasteRecord,
WasteRiskAssessment,
} from "@/types/waste";
import { RISK_LEVEL_LABELS,SUGGESTED_HANDLING_LABELS } from "@/types/waste";

export function RiskAssessmentPanel({
  record,
  onRecordUpdated,
}: {
  record: WasteRecord;
  onRecordUpdated: () => void;
}) {
  const [history, setHistory] = useState<WasteRiskAssessment[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showHistory, setShowHistory] = useState(false);
  const [showOverride, setShowOverride] = useState(false);
  const [overrideLevel, setOverrideLevel] = useState<RiskLevel>("medium");
  const [overrideHandling, setOverrideHandling] = useState<SuggestedHandling>("dispose");
  const [overrideNotes, setOverrideNotes] = useState("");

  const loadHistory = () => {
    setLoading(true);
    api
      .get<WasteRiskAssessment[]>(`/api/v1/waste/${record.id}/risk-assessments`)
      .then(setHistory)
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadHistory();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [record.id]);

  const notYetClassified = record.status === "reported";
  const latest = history[0] ?? null;

  const runAssessment = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.post(`/api/v1/waste/${record.id}/risk-assessments/run`);
      loadHistory();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't run risk assessment.");
    } finally {
      setBusy(false);
    }
  };

  const confirmSuggestion = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.post(`/api/v1/waste/${record.id}/risk-assessments/confirm`);
      loadHistory();
      onRecordUpdated();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't confirm assessment.");
    } finally {
      setBusy(false);
    }
  };

  const submitOverride = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.post(`/api/v1/waste/${record.id}/risk-assessments/override`, {
        risk_level: overrideLevel,
        suggested_handling: overrideHandling,
        notes: overrideNotes || undefined,
      });
      setShowOverride(false);
      setOverrideNotes("");
      loadHistory();
      onRecordUpdated();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save the manual assessment.");
    } finally {
      setBusy(false);
    }
  };

  if (notYetClassified) {
    return (
      <div className="manifest-edge mt-6 rounded-2xl border border-dashed border-mist-deep bg-paper p-7">
        <h2 className="font-display text-lg font-semibold text-charcoal">Risk assessment</h2>
        <p className="mt-2 text-[13.5px] text-slate">
          Classify this waste first — risk assessment builds on the confirmed category.
        </p>
      </div>
    );
  }

  return (
    <div className="manifest-edge mt-6 rounded-2xl border border-mist-deep bg-paper p-7">
      <div className="flex items-center justify-between">
        <h2 className="font-display text-lg font-semibold text-charcoal">Risk assessment</h2>
        {history.length > 0 && (
          <button
            onClick={() => setShowHistory((v) => !v)}
            className="flex items-center gap-1.5 text-[12.5px] text-slate hover:text-charcoal"
          >
            <History size={13} />
            {showHistory ? "Hide history" : `History (${history.length})`}
          </button>
        )}
      </div>

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
                Run the rule-based risk engine to get a suggested risk level and handling.
              </p>
              <Button size="sm" className="mt-3" onClick={runAssessment} disabled={busy}>
                <ShieldAlert size={14} />
                {busy ? "Assessing…" : "Run risk assessment"}
              </Button>
            </div>
          )}

          {latest && (
            <div className="mt-4 rounded-xl border border-mist-deep bg-mist/40 p-5">
              <div className="flex flex-wrap items-center gap-2">
                <RiskLevelBadge level={latest.risk_level} />
                {latest.recyclability_decision && (
                  <span className="flex items-center gap-1 text-[12.5px] text-emerald-dim">
                    <Recycle size={13} /> Recyclable
                  </span>
                )}
                {latest.is_confirmed ? (
                  <span className="flex items-center gap-1 text-[12.5px] text-emerald-dim">
                    <CheckCircle2 size={13} /> Confirmed
                  </span>
                ) : (
                  <span className="text-[12.5px] text-slate-light">Awaiting confirmation</span>
                )}
              </div>

              <p className="mt-3 text-[14px] font-medium text-charcoal">
                Suggested handling: {SUGGESTED_HANDLING_LABELS[latest.suggested_handling]}
              </p>
              <p className="mt-1.5 text-[13px] leading-relaxed text-slate">{latest.explanation}</p>

              {latest.notes && (
                <p className="mt-2.5 text-[12.5px] italic text-slate">
                  Staff note: {latest.notes}
                </p>
              )}

              {!latest.is_confirmed && (
                <div className="mt-4 flex flex-wrap gap-2">
                  <Button size="sm" onClick={confirmSuggestion} disabled={busy}>
                    Confirm
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setShowOverride((v) => !v)}
                    disabled={busy}
                  >
                    Set manually
                  </Button>
                </div>
              )}

              {latest.is_confirmed && (
                <div className="mt-4 flex flex-wrap gap-2">
                  <Button size="sm" variant="outline" onClick={runAssessment} disabled={busy}>
                    <ShieldAlert size={14} />
                    Re-assess
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setShowOverride((v) => !v)}
                    disabled={busy}
                  >
                    Set manually
                  </Button>
                </div>
              )}
            </div>
          )}

          {showOverride && (
            <div className="mt-4 rounded-xl border border-dashed border-mist-deep p-5">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <Label htmlFor="override_risk_level">Risk level</Label>
                  <Select
                    id="override_risk_level"
                    value={overrideLevel}
                    onChange={(e) => setOverrideLevel(e.target.value as RiskLevel)}
                  >
                    {Object.entries(RISK_LEVEL_LABELS).map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </Select>
                </div>
                <div>
                  <Label htmlFor="override_handling">Suggested handling</Label>
                  <Select
                    id="override_handling"
                    value={overrideHandling}
                    onChange={(e) => setOverrideHandling(e.target.value as SuggestedHandling)}
                  >
                    {Object.entries(SUGGESTED_HANDLING_LABELS).map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </Select>
                </div>
              </div>

              <Label htmlFor="override_notes" className="mt-3">
                Reason (optional)
              </Label>
              <Textarea
                id="override_notes"
                value={overrideNotes}
                onChange={(e) => setOverrideNotes(e.target.value)}
                placeholder="Why does this differ from the suggestion?"
              />

              <div className="mt-3 flex gap-2">
                <Button size="sm" onClick={submitOverride} disabled={busy}>
                  Save assessment
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setShowOverride(false)}>
                  Cancel
                </Button>
              </div>
            </div>
          )}

          {showHistory && (
            <ul className="mt-5 space-y-2 border-t border-mist-deep pt-4">
              {history.map((entry) => (
                <li
                  key={entry.id}
                  className="flex items-center justify-between rounded-lg bg-mist/40 px-3.5 py-2.5 text-[12.5px]"
                >
                  <div className="flex items-center gap-2">
                    <RiskLevelBadge level={entry.risk_level} />
                    <span className="text-charcoal">
                      {SUGGESTED_HANDLING_LABELS[entry.suggested_handling]}
                    </span>
                    <span className="text-slate-light">
                      {entry.source === "manual" ? "Manual" : "Rule engine"}
                    </span>
                  </div>
                  <span className="text-slate-light">
                    {new Date(entry.created_at).toLocaleString()}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}
