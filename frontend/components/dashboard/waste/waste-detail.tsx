"use client";

import { ArrowLeft,CalendarClock,FileText,Image as ImageIcon,Paperclip } from "lucide-react";
import Link from "next/link";
import { useCallback,useEffect,useState } from "react";

import { AIIntelligencePanel } from "@/components/dashboard/waste/ai-intelligence-panel";
import { ClassificationPanel } from "@/components/dashboard/waste/classification-panel";
import { MatchingPanel } from "@/components/dashboard/waste/matching-panel";
import { RiskAssessmentPanel } from "@/components/dashboard/waste/risk-assessment-panel";
import { WasteStatusBadge } from "@/components/dashboard/waste/status-badge";
import { TimelinePanel } from "@/components/dashboard/waste/timeline-panel";
import { Button } from "@/components/ui/button";
import { api,apiFileUrl } from "@/lib/api";
import type { WasteRecord } from "@/types/waste";

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

type ProcessingReport = {available:boolean;simulated?:boolean; processing_method?:string;status?:string;proof_note?:string|null;started_at?:string|null;proof_submitted_at?:string|null;completed_at?:string|null};
export function WasteDetail({ recordId }: { recordId: string }) {
  const [record, setRecord] = useState<WasteRecord | null>(null);
  const [processingReport, setProcessingReport] = useState<ProcessingReport|null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [uploading, setUploading] = useState(false);
  const [timelineNonce, setTimelineNonce] = useState(0);

  const load = useCallback(() => {
    setLoading(true);
    api
      .get<WasteRecord>(`/api/v1/waste/${recordId}`)
      .then(data => { setRecord(data); setNotFound(false);
        const count = Number(new URLSearchParams(window.location.search).get("upload_failed") ?? 0);
        if (count > 0) setUploadError(`${count} attachment(s) could not be uploaded. The waste report was saved; add the missing files below.`);
      })
      .catch(() => setNotFound(true))
      .finally(() => setLoading(false));
    // Every panel action (classify, assess, match, etc.) can add a new
    // timeline event even when it doesn't change the record's own status
    // (e.g. confirming a match) — so re-key the timeline on every load().
    api.get<ProcessingReport>(`/api/v1/waste/${recordId}/processing-report`).then(setProcessingReport).catch(()=>setProcessingReport(null));
    setTimelineNonce((n) => n + 1);
  }, [recordId]);

  useEffect(() => {
    // Fetch on mount and whenever the record ID changes — the standard
    // "load from an external session" pattern used across the dashboard.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, [load]);

  const handleUpload = async (file: File) => {
    setUploading(true); setUploadError("");
    try {
      await api.upload(`/api/v1/waste/${recordId}/attachments`, file);
      load();
    } catch (e) {
      setUploadError(e instanceof Error ? e.message : "File upload failed");
    } finally {
      setUploading(false);
    }
  };

  if (loading) {
    return <p className="text-[14px] text-slate">Loading…</p>;
  }

  if (notFound || !record) {
    return (
      <div className="mx-auto max-w-lg text-center">
        <p className="text-[14px] text-slate">This waste record couldn&apos;t be found.</p>
        <Link href="/dashboard/waste" className="mt-3 inline-block text-[13.5px] text-emerald">
          Back to waste history
        </Link>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-2xl">
      <Link
        href="/dashboard/waste"
        className="inline-flex items-center gap-1.5 text-[13px] text-slate hover:text-charcoal"
      >
        <ArrowLeft size={14} /> Back to waste
      </Link>

      <div className="manifest-edge mt-4 overflow-hidden rounded-2xl border border-mist-deep bg-white">
        <div className="flex items-center justify-between px-7 pt-7">
          <div>
            <p className="font-data text-[11px] uppercase tracking-[0.14em] text-slate-light">
              Waste record
            </p>
            <p className="font-data mt-1 text-xl font-medium text-charcoal">
              {record.waste_code}
            </p>
          </div>
          <WasteStatusBadge status={record.status} />
        </div>

        {record.status === "risk_assessed" && (
          <div className="mx-7 mt-5 flex items-center justify-between rounded-lg border border-emerald/20 bg-signal-emerald-bg px-4 py-3">
            <p className="text-[13px] text-emerald-dim">Ready to be scheduled for pickup.</p>
            <Link href={`/dashboard/pickups/new?waste_record_id=${record.id}`}>
              <Button size="sm" variant="emerald">
                <CalendarClock size={14} /> Request pickup
              </Button>
            </Link>
          </div>
        )}

        <dl className="mt-6 grid grid-cols-2 gap-5 px-7">
          <div>
            <dt className="text-[12px] text-slate-light">Category</dt>
            <dd className="mt-0.5 text-[14px] text-charcoal">{record.category.name}</dd>
          </div>
          <div>
            <dt className="text-[12px] text-slate-light">Quantity</dt>
            <dd className="mt-0.5 text-[14px] text-charcoal">
              {record.quantity} {record.unit}
            </dd>
          </div>
          <div>
            <dt className="text-[12px] text-slate-light">Generated</dt>
            <dd className="mt-0.5 text-[14px] text-charcoal">
              {new Date(record.generated_at).toLocaleString()}
            </dd>
          </div>
          <div>
            <dt className="text-[12px] text-slate-light">Reported</dt>
            <dd className="mt-0.5 text-[14px] text-charcoal">
              {new Date(record.created_at).toLocaleString()}
            </dd>
          </div>
          {record.received_quantity && (
            <div>
              <dt className="text-[12px] text-slate-light">Received weight</dt>
              <dd className="mt-0.5 text-[14px] text-charcoal">
                {record.received_quantity} {record.unit}
                {record.received_at &&
                  ` · ${new Date(record.received_at).toLocaleDateString()}`}
              </dd>
            </div>
          )}
          {record.description && (
            <div className="col-span-2">
              <dt className="text-[12px] text-slate-light">Description</dt>
              <dd className="mt-0.5 text-[14px] leading-relaxed text-charcoal">
                {record.description}
              </dd>
            </div>
          )}
        </dl>

        <div className="manifest-edge mt-7 bg-mist/60 px-7 py-6">
          <p className="text-[12.5px] font-medium uppercase tracking-wide text-slate-light">
            Attachments
          </p>

          {uploadError && <p className="mb-3 text-sm text-signal-rust" role="alert">{uploadError}</p>}
          {record.attachments.length === 0 ? (
            <p className="mt-2 text-[13.5px] text-slate">No files attached yet.</p>
          ) : (
            <ul className="mt-3 space-y-2">
              {record.attachments.map((a) => (
                <li key={a.id}>
                  <a
                    href={apiFileUrl(
                      `/api/v1/waste/${record.id}/attachments/${a.id}/download`
                    )}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-2.5 rounded-lg border border-mist-deep bg-paper px-3.5 py-2.5 text-[13px] text-charcoal transition-colors hover:bg-mist"
                  >
                    {a.content_type.startsWith("image/") ? (
                      <ImageIcon size={15} className="shrink-0 text-slate-light" />
                    ) : (
                      <FileText size={15} className="shrink-0 text-slate-light" />
                    )}
                    <span className="flex-1 truncate">{a.original_filename}</span>
                    <span className="shrink-0 text-[11.5px] text-slate-light">
                      {formatBytes(a.size_bytes)}
                    </span>
                  </a>
                </li>
              ))}
            </ul>
          )}

          <label className="mt-3 flex cursor-pointer items-center gap-2 text-[13px] text-emerald hover:underline">
            <Paperclip size={14} />
            {uploading ? "Uploading…" : "Add a file"}
            <input
              type="file"
              accept="image/jpeg,image/png,image/webp,application/pdf"
              className="hidden"
              disabled={uploading}
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) handleUpload(file);
                e.target.value = "";
              }}
            />
          </label>
        </div>
      </div>

      {processingReport?.available&&<section className="mt-6 rounded-2xl border border-mist-deep bg-white p-6" aria-label="Treatment report">
        <div className="flex flex-wrap justify-between gap-3"><h2 className="text-lg font-semibold">Treatment Facility Processing Report {processingReport.simulated&&<span className="ml-2 text-sm text-amber-700">SIMULATED / DEMO ONLY</span>}</h2><button type="button" onClick={()=>window.print()} className="rounded-lg border border-mist-deep px-3 py-2 text-sm">Print / Save as PDF</button></div>
        <dl className="mt-4 grid grid-cols-2 gap-3 text-sm"><div><dt>Method</dt><dd className="font-semibold">{processingReport.processing_method}</dd></div><div><dt>Status</dt><dd className="font-semibold">{processingReport.status}</dd></div>
          {processingReport.started_at&&<div><dt>Started</dt><dd>{new Date(processingReport.started_at).toLocaleString()}</dd></div>}
          {processingReport.completed_at&&<div><dt>Completed</dt><dd>{new Date(processingReport.completed_at).toLocaleString()}</dd></div>}</dl>
        {processingReport.proof_note?<p className="mt-4 whitespace-pre-wrap rounded-lg bg-mist p-4 text-sm">{processingReport.proof_note}</p>:<p className="mt-4 text-sm">The facility has not submitted its processing report yet.</p>}
        <p className="mt-3 text-xs text-slate">Uploaded facility evidence appears in the Attachments section above. Demo-only events are marked SIMULATED in the history.</p>
      </section>}
      <TimelinePanel key={timelineNonce} recordId={record.id} />

      <AIIntelligencePanel record={record} />
      <ClassificationPanel record={record} onRecordUpdated={load} />
      <RiskAssessmentPanel record={record} onRecordUpdated={load} />
      <MatchingPanel record={record} onRecordUpdated={load} />
    </div>
  );
}