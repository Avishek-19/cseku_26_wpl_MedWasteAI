"use client";

import {
AlertCircle,
BrainCircuit,
CheckCircle2,
Eye,
FlaskConical,
Recycle,
Settings2,
ShieldAlert,
Sparkles,
TrendingDown,
TrendingUp,
} from "lucide-react";
import { useState,type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { api,ApiError } from "@/lib/api";
import type { AIAnalysisResponse,WasteRecord } from "@/types/waste";

export function AIIntelligencePanel({ record }: { record: WasteRecord }) {
  const [analysis, setAnalysis] = useState<AIAnalysisResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await api.post<AIAnalysisResponse>(
        `/api/v1/waste/${record.id}/ai/analyze`,
      );
      setAnalysis(result);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't run local AI analysis.");
    } finally {
      setBusy(false);
    }
  };

  const trendIcon =
    analysis?.trend.direction === "rising" ? (
      <TrendingUp size={15} />
    ) : analysis?.trend.direction === "falling" ? (
      <TrendingDown size={15} />
    ) : null;

  return (
    <section className="manifest-edge mt-6 rounded-2xl border border-emerald/20 bg-white p-7">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <span className="flex size-8 items-center justify-center rounded-lg bg-emerald/10 text-emerald">
              <BrainCircuit size={17} />
            </span>
            <div>
              <h2 className="font-display text-lg font-semibold text-charcoal">Local AI intelligence</h2>
              <p className="text-[12px] text-slate-light">Advisory analysis · rule-validated · human verification required</p>
            </div>
          </div>
        </div>
        <Button size="sm" variant="emerald" onClick={run} disabled={busy}>
          <Sparkles size={14} />
          {busy ? "Analyzing…" : analysis ? "Run again" : "Run local AI"}
        </Button>
      </div>

      {error && (
        <div className="mt-4 flex items-start gap-2 rounded-lg border border-signal-rust/20 bg-signal-rust-bg px-3.5 py-2.5 text-[13px] text-signal-rust">
          <AlertCircle size={15} className="mt-0.5 shrink-0" />
          {error}
        </div>
      )}

      {!analysis && !busy && !error && (
        <div className="mt-5 rounded-xl border border-dashed border-mist-deep bg-mist/30 p-5">
          <p className="text-[13.5px] leading-relaxed text-slate">
            Run the local intelligence layer to review classification, risk, recyclability,
            image availability, anomalies, trends, and the existing destination recommendation.
            No cloud AI API is used.
          </p>
        </div>
      )}

      {analysis && (
        <>
          <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Insight
              icon={<Sparkles size={15} />}
              label="Classification"
              value={analysis.classification.category_name}
              detail={`${Math.round(analysis.classification.confidence * 100)}% confidence`}
            />
            <Insight
              icon={<ShieldAlert size={15} />}
              label="Risk estimate"
              value={analysis.risk.risk_level}
              detail={analysis.risk.suggested_handling}
            />
            <Insight
              icon={<Recycle size={15} />}
              label="Recyclability"
              value={analysis.recyclability.recyclable ? "Potentially recyclable" : "Not recyclable"}
              detail={`${Math.round(analysis.recyclability.confidence * 100)}% rule confidence`}
            />
            <Insight
              icon={<Settings2 size={15} />}
              label="Required processing"
              value={analysis.processing.required_processing}
              detail={`${Math.round(analysis.processing.confidence * 100)}% advisory confidence`}
            />
          </div>

          <div className="mt-3 grid gap-3 lg:grid-cols-2">
            <InsightCard icon={<Eye size={15} />} title="Image analysis">
              <p>{analysis.image.observations}</p>
              <Meta>
                {analysis.image.status === "completed"
                  ? `Model: ${analysis.image.model}`
                  : analysis.image.status.replaceAll("_", " ")}
              </Meta>
            </InsightCard>

            <InsightCard icon={<FlaskConical size={15} />} title="Anomaly detection">
              <p>{analysis.anomaly.message}</p>
              <Meta>
                Score {analysis.anomaly.score.toFixed(2)}
                {analysis.anomaly.baseline_median !== null &&
                  ` · median ${analysis.anomaly.baseline_median}`}
              </Meta>
            </InsightCard>

            <InsightCard icon={trendIcon ?? <TrendingUp size={15} />} title="Trend estimate">
              <p>{analysis.trend.message}</p>
              <Meta>
                {analysis.trend.direction.replaceAll("_", " ")}
                {analysis.trend.next_period_quantity !== null &&
                  ` · next period ≈ ${analysis.trend.next_period_quantity} ${record.unit}`}
              </Meta>
            </InsightCard>

            <InsightCard icon={<Settings2 size={15} />} title="Processing requirement">
              <p>{analysis.processing.reasoning}</p>
              <Meta>Accepted methods: {analysis.processing.acceptable_methods.join(", ")}</Meta>
            </InsightCard>

            <InsightCard icon={<CheckCircle2 size={15} />} title="Destination assistance">
              <p>
                {analysis.matching.recommendation
                  ? `Current recommendation: ${analysis.matching.recommendation}`
                  : analysis.matching.explanation}
              </p>
              <Meta>
                {analysis.matching.candidates.length
                  ? `${analysis.matching.candidates.length} ranked candidate(s)`
                  : analysis.matching.status.replaceAll("_", " ")}
              </Meta>
            </InsightCard>
          </div>

          <div className="mt-4 rounded-xl border border-emerald/15 bg-emerald/5 p-4">
            <p className="text-[12px] font-semibold uppercase tracking-[0.12em] text-emerald-dim">
              AI recommendation
            </p>
            <p className="mt-1.5 text-[13px] leading-relaxed text-slate">
              {analysis.processing.reasoning}
            </p>
            <p className="mt-2 text-[12.5px] leading-relaxed text-slate">
              {analysis.classification.reasoning} {analysis.risk.reasoning}
            </p>
            <p className="mt-2 text-[11.5px] leading-relaxed text-slate-light">
              {analysis.disclaimer}
            </p>
            <p className="mt-2 font-data text-[10.5px] uppercase tracking-[0.1em] text-slate-light">
              Engine: {analysis.provider}
              {analysis.model ? ` · ${analysis.model}` : ""}
            </p>
          </div>
        </>
      )}
    </section>
  );
}

function Insight({
  icon,
  label,
  value,
  detail,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <div className="rounded-xl border border-mist-deep bg-mist/40 p-4">
      <div className="flex items-center gap-1.5 text-[11.5px] text-slate-light">
        {icon}
        {label}
      </div>
      <p className="mt-2 text-[15px] font-semibold capitalize text-charcoal">{value}</p>
      <p className="mt-1 text-[11.5px] text-slate-light">{detail}</p>
    </div>
  );
}

function InsightCard({
  icon,
  title,
  children,
}: {
  icon: ReactNode;
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="rounded-xl border border-mist-deep bg-paper p-4">
      <div className="flex items-center gap-1.5 text-[12px] font-semibold text-charcoal">
        {icon}
        {title}
      </div>
      <div className="mt-2 text-[12.5px] leading-relaxed text-slate">{children}</div>
    </div>
  );
}

function Meta({ children }: { children: ReactNode }) {
  return <p className="mt-2 font-data text-[10.5px] uppercase tracking-[0.08em] text-slate-light">{children}</p>;
}
