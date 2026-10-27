"use client";
import { useDeferredEffect } from "@/hooks/use-deferred-effect";

import { api } from "@/lib/api";
import { WASTE_EVENT_LABELS,type WasteEvent,type WasteEventType } from "@/types/waste";
import { CalendarClock,CheckCircle2,MapPin,PackageSearch,ShieldAlert,Sparkles,Truck,XCircle } from "lucide-react";
import { useState } from "react";

type EventIcon = typeof PackageSearch;
const EVENT_ICON: Partial<Record<WasteEventType, EventIcon>> = {
  reported: PackageSearch, classified: Sparkles, risk_assessed: ShieldAlert, matched: MapPin,
  pickup_requested: CalendarClock, pickup_assigned: Truck, pickup_cancelled: XCircle,
  collected: CheckCircle2, in_transit: Truck, destination_received: CheckCircle2,
  processing: Truck, proof_submitted: CheckCircle2, verified: ShieldAlert, completed: CheckCircle2,
};
const EVENT_TONE: Partial<Record<WasteEventType, string>> = {
  reported: "bg-forest/[0.08] text-forest", classified: "bg-forest/[0.08] text-forest",
  risk_assessed: "bg-signal-amber-bg text-signal-amber", matched: "bg-forest/[0.08] text-forest",
  pickup_requested: "bg-signal-amber-bg text-signal-amber", pickup_assigned: "bg-forest/[0.08] text-forest",
  pickup_cancelled: "bg-signal-rust-bg text-signal-rust", collected: "bg-signal-emerald-bg text-emerald-dim",
  in_transit: "bg-forest/[0.08] text-forest", destination_received: "bg-signal-emerald-bg text-emerald-dim",
  processing: "bg-signal-amber-bg text-signal-amber", proof_submitted: "bg-forest/[0.08] text-forest",
  verified: "bg-signal-emerald-bg text-emerald-dim", completed: "bg-signal-emerald-bg text-emerald-dim",
};
function getEventIcon(type: WasteEventType): EventIcon { return EVENT_ICON[type] ?? PackageSearch; }
function getEventTone(type: WasteEventType): string { return EVENT_TONE[type] ?? "bg-mist text-slate"; }
function getEventLabel(type: WasteEventType): string {
  return WASTE_EVENT_LABELS[type] ?? type.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
function metadataChips(event: WasteEvent): string[] {
  const chips: string[] = []; const m = event.event_metadata ?? {};
  if (m.simulated === true) chips.push("SIMULATED / DEMO ONLY");
  if (typeof m.document_name === "string") chips.push(m.document_name);
  if (typeof m.vehicle_code === "string") chips.push(m.vehicle_code);
  if (typeof m.destination_name === "string") chips.push(m.destination_name);
  if (typeof m.processing_method === "string") chips.push(m.processing_method);
  if (typeof m.risk_level === "string") chips.push(`${m.risk_level} risk`);
  if (typeof m.category === "string") chips.push(m.category);
  if (typeof m.score === "number") chips.push(`score ${m.score}/100`);
  return chips;
}
export function TimelinePanel({ recordId }: { recordId: string }) {
  const [events, setEvents] = useState<WasteEvent[]>([]); const [loading, setLoading] = useState(true); const [error, setError] = useState(false);
  useDeferredEffect(() => { let cancelled=false; setLoading(true); setError(false); api.get<WasteEvent[]>(`/api/v1/waste/${recordId}/timeline`).then((d)=>{if(!cancelled)setEvents(d)}).catch(()=>{if(!cancelled){setEvents([]);setError(true)}}).finally(()=>{if(!cancelled)setLoading(false)}); return ()=>{cancelled=true}; }, [recordId]);
  if (loading) return <div className="mt-6 rounded-2xl border border-mist-deep bg-paper p-7"><div className="animate-pulse"><div className="h-5 w-40 rounded bg-mist"/><div className="mt-2 h-3 w-64 rounded bg-mist"/><div className="mt-6 space-y-6">{[1,2,3].map((n)=><div key={n} className="flex gap-4"><div className="h-8 w-8 shrink-0 rounded-full bg-mist"/><div className="flex-1"><div className="h-4 w-48 rounded bg-mist"/><div className="mt-2 h-3 w-32 rounded bg-mist"/></div></div>)}</div></div></div>;
  if (error) return <div className="mt-6 rounded-2xl border border-signal-rust/20 bg-paper p-7"><h2 className="font-display text-lg font-semibold text-charcoal">Chain of custody</h2><p className="mt-2 text-[13px] text-slate">The custody timeline could not be loaded right now.</p></div>;
  if (!events.length) return null;
  return <div className="manifest-edge mt-6 rounded-2xl border border-mist-deep bg-paper p-7"><h2 className="font-display text-lg font-semibold text-charcoal">Chain of custody</h2><p className="mt-1 text-[13px] text-slate">Every recorded event for this batch, in order.</p><ol className="mt-6 space-y-0">{events.map((event,i)=>{const Icon=getEventIcon(event.event_type);const last=i===events.length-1;const chips=metadataChips(event);return <li key={event.id} className="relative flex gap-4 pb-7 last:pb-0">{!last&&<span className="absolute left-[15px] top-8 bottom-0 w-px bg-mist-deep"/>}<span className={`relative z-10 flex h-8 w-8 shrink-0 items-center justify-center rounded-full ${getEventTone(event.event_type)}`}><Icon size={15} strokeWidth={2} aria-hidden="true"/></span><div className="min-w-0 flex-1 pt-0.5"><div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1"><p className="text-[14px] font-medium text-charcoal">{event.event_metadata?.manual_arrival === true ? "Manual Hospital Arrival (DEMO)" : getEventLabel(event.event_type)}</p><time className="text-[12px] text-slate-light">{new Date(event.created_at).toLocaleString()}</time></div><p className="mt-0.5 text-[12.5px] text-slate-light">{event.actor ? event.actor.full_name : "System"}{event.quantity && ` · ${event.quantity} recorded`}</p>{event.notes&&<p className="mt-1.5 text-[13px] leading-relaxed text-slate">{event.notes}</p>}{chips.length>0&&<div className="mt-2 flex flex-wrap gap-1.5">{chips.map((chip,idx)=><span key={`${chip}-${idx}`} className="font-data rounded bg-mist px-2 py-0.5 text-[11px] text-slate">{chip}</span>)}</div>}</div></li>})}</ol></div>;
}