"use client";

import { AlertCircle,CheckCircle2,History,Sparkles } from "lucide-react";
import { useEffect,useState } from "react";

import { ConfidenceBadge } from "@/components/dashboard/waste/confidence-badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { api,ApiError } from "@/lib/api";
import type { WasteCategory,WasteClassification,WasteRecord } from "@/types/waste";

export function ClassificationPanel({
  record,
  onRecordUpdated,
}: {
  record: WasteRecord;
  onRecordUpdated: () => void;
}) {
  const [history, setHistory] = useState<WasteClassification[]>([]);
  const [categories, setCategories] = useState<WasteCategory[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showHistory, setShowHistory] = useState(false);
  const [showOverride, setShowOverride] = useState(false);
  const [overrideCategory, setOverrideCategory] = useState("");
  const [overrideNotes, setOverrideNotes] = useState("");

  const loadHistory = () => {
    setLoading(true);
    api
      .get<WasteClassification[]>(`/api/v1/waste/${record.id}/classifications`)
      .then(setHistory)
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadHistory();
    api.get<WasteCategory[]>("/api/v1/waste/categories").then(setCategories);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [record.id]);

  const latest = history[0] ?? null;

  const runClassification = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.post(`/api/v1/waste/${record.id}/classifications/run`);
      loadHistory();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't run classification.");
    } finally {
      setBusy(false);
    }
  };

  const confirmSuggestion = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.post(`/api/v1/waste/${record.id}/classifications/confirm`);
      loadHistory();
      onRecordUpdated();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't confirm classification.");
    } finally {
      setBusy(false);
    }
  };

  const submitOverride = async () => {
    if (!overrideCategory) return;
    setBusy(true);
    setError(null);
    try {
      await api.post(`/api/v1/waste/${record.id}/classifications/override`, {
        category_id: overrideCategory,
        notes: overrideNotes || undefined,
      });
      setShowOverride(false);
      setOverrideCategory("");
      setOverrideNotes("");
      loadHistory();
      onRecordUpdated();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save the manual classification.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="manifest-edge mt-6 rounded-2xl border border-mist-deep bg-paper p-7">
      <div className="flex items-center justify-between">
        <h2 className="font-display text-lg font-semibold text-charcoal">Classification</h2>
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
                This batch hasn&apos;t been classified yet. Run the rule-based
                classifier to get a suggested category.
              </p>
              <Button size="sm" className="mt-3" onClick={runClassification} disabled={busy}>
                <Sparkles size={14} />
                {busy ? "Classifying…" : "Run classification"}
              </Button>
            </div>
          )}

          {latest && (
            <div className="mt-4 rounded-xl border border-mist-deep bg-mist/40 p-5">
              <div className="flex flex-wrap items-center gap-2">
                <ConfidenceBadge confidence={latest.confidence} />
                {latest.is_confirmed ? (
                  <span className="flex items-center gap-1 text-[12.5px] text-emerald-dim">
                    <CheckCircle2 size={13} /> Confirmed
                  </span>
                ) : (
                  <span className="text-[12.5px] text-slate-light">Awaiting confirmation</span>
                )}
              </div>

              <p className="mt-3 text-[14px] font-medium text-charcoal">
                Suggested: {latest.suggested_category.name}
              </p>
              <p className="mt-1.5 text-[13px] leading-relaxed text-slate">{latest.explanation}</p>

              {latest.matched_rules.length > 0 && (
                <div className="mt-2.5 flex flex-wrap gap-1.5">
                  {latest.matched_rules.map((m, i) => (
                    <span
                      key={i}
                      className="font-data rounded bg-paper px-2 py-1 text-[11px] text-slate"
                    >
                      {m.category_code}: {m.matched_keywords.join(", ")}
                    </span>
                  ))}
                </div>
              )}

              {latest.notes && (
                <p className="mt-2.5 text-[12.5px] italic text-slate">
                  Staff note: {latest.notes}
                </p>
              )}

              {!latest.is_confirmed && (
                <div className="mt-4 flex flex-wrap gap-2">
                  <Button size="sm" onClick={confirmSuggestion} disabled={busy || latest.suggested_category.code === "PENDING"}>
                    Confirm as {latest.suggested_category.name}
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setShowOverride((v) => !v)}
                    disabled={busy}
                  >
                    Choose a different category
                  </Button>
                </div>
              )}

              {latest.is_confirmed && (
                <div className="mt-4 flex flex-wrap gap-2">
                  <Button size="sm" variant="outline" onClick={runClassification} disabled={busy}>
                    <Sparkles size={14} />
                    Re-classify
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setShowOverride((v) => !v)}
                    disabled={busy}
                  >
                    Choose a different category
                  </Button>
                </div>
              )}
            </div>
          )}

          {showOverride && (
            <div className="mt-4 rounded-xl border border-dashed border-mist-deep p-5">
              <Label htmlFor="override_category">Manual category</Label>
              <Select
                id="override_category"
                value={overrideCategory}
                onChange={(e) => setOverrideCategory(e.target.value)}
              >
                <option value="" disabled>
                  Select a category
                </option>
                {categories.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </Select>

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
                <Button
                  size="sm"
                  onClick={submitOverride}
                  disabled={busy || !overrideCategory}
                >
                  Save classification
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
                    <span className="text-charcoal">{entry.suggested_category.name}</span>
                    <ConfidenceBadge confidence={entry.confidence} />
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
