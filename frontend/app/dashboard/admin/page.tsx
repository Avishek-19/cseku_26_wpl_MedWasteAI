"use client";
import { useDeferredEffect } from "@/hooks/use-deferred-effect";

import { StatCard } from "@/components/dashboard/stat-card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/hooks/use-auth";
import { api } from "@/lib/api";
import type { UserRole } from "@/types/auth";
import { AlertTriangle,FileClock,ShieldCheck,Users } from "lucide-react";
import Link from "next/link";
import { useCallback,useState } from "react";

type Overview={users_total:number;active_users:number;pending_hospitals:number;pending_collectors:number;pending_facilities:number;open_incidents:number;waste_batches:number;audit_events:number};
type Verify={id:string;user_id:string;user_name:string;email:string;organization_name:string;registration_number:string;city:string;is_verified:boolean;created_at:string};
type Incident={id:string;waste_code:string;incident_type:string;severity:string;description:string;is_resolved:boolean;created_at:string};
type Category={id:string;code:string;name:string;description:string|null;is_recyclable:boolean;is_active:boolean};
type Rule={id:string;category_id:string;category_name:string;base_risk_level:string;quantity_escalation_threshold:number|null;is_active:boolean};
type Audit={id:string;actor_name:string|null;action:string;entity_type:string;entity_id:string|null;created_at:string;details:Record<string,unknown>};
type AdminUser={id:string;email:string;full_name:string;role:UserRole;is_active:boolean;is_verified:boolean};

const roles:[UserRole,string][]=[["hospital","Hospitals"],["collector","Collectors"],["facility","Waste Processing Facilities"]];

export default function AdminPage(){
 const {user}=useAuth(); const [tab,setTab]=useState("overview"); const [overview,setOverview]=useState<Overview|null>(null); const [users,setUsers]=useState<AdminUser[]>([]); const [ver,setVer]=useState<Verify[]>([]); const [verRole,setVerRole]=useState<UserRole>("hospital"); const [incidents,setIncidents]=useState<Incident[]>([]); const [categories,setCategories]=useState<Category[]>([]); const [rules,setRules]=useState<Rule[]>([]); const [audit,setAudit]=useState<Audit[]>([]); const [error,setError]=useState("");
 const load=useCallback(async()=>{setError(""); try { const [o,u,c,r,i,a,v]=await Promise.all([api.get<Overview>("/api/v1/admin/overview"),api.get<AdminUser[]>("/api/v1/admin/users"),api.get<Category[]>("/api/v1/admin/categories"),api.get<Rule[]>("/api/v1/admin/risk-rules"),api.get<Incident[]>("/api/v1/admin/incidents"),api.get<Audit[]>("/api/v1/admin/audit-logs?limit=100"),api.get<{items:Verify[];total:number}>(`/api/v1/admin/verification/${verRole}?pending_only=false`)]); setOverview(o);setUsers(u);setCategories(c);setRules(r);setIncidents(i);setAudit(a);setVer(v.items);} catch(e){setError(e instanceof Error?e.message:"Unable to load admin data.");}},[verRole]);
 useDeferredEffect(()=>{if(user?.role==="admin") load();},[user,load]);
 if(!user || user.role!=="admin") return <div className="mx-auto max-w-4xl"><div className="rounded-2xl border border-mist-deep bg-paper p-8"><h1 className="font-display text-xl font-semibold text-charcoal">Administrator access required</h1><p className="mt-2 text-sm text-slate">This workspace is restricted to verified platform administrators.</p></div></div>;
 const tabs=["overview","verification","users","categories","rules","incidents","workflow failures","pickup exceptions","receipt exceptions","audit"];
 return <div className="mx-auto max-w-7xl space-y-7">
  <div><p className="font-data text-[11px] uppercase tracking-[.14em] text-emerald">Control center</p><h1 className="mt-2 font-display text-3xl font-semibold text-charcoal">Admin & governance</h1><p className="mt-1 text-sm text-slate">Verify organizations, manage rules, resolve incidents, and review platform activity.</p></div>
  <div className="flex flex-wrap gap-3"><Link href="/dashboard/governance" className="rounded-xl border border-[#d1c8de] bg-[#f0ecf5] px-4 py-3 text-sm font-semibold text-[#422965] hover:bg-[#e5e0ed]">Review organizations & permits →</Link><Link href="/dashboard/finance-admin" className="rounded-xl border border-[#ddd9e2] bg-white px-4 py-3 text-sm font-semibold text-[#4b3966] hover:bg-[#f5f3f7]">Manage contracts & billing →</Link></div>
  {error&&<div className="rounded-xl border border-signal-rust/20 bg-signal-rust-bg px-4 py-3 text-sm text-signal-rust">{error}</div>}
  <div className="flex flex-wrap gap-2 border-b border-mist-deep pb-3">{tabs.map(t=><button key={t} onClick={()=>setTab(t)} className={`rounded-lg px-3 py-2 text-[13px] font-medium ${tab===t?"bg-forest text-paper":"text-slate hover:bg-mist"}`}>{t[0].toUpperCase()+t.slice(1)}</button>)}</div>
  {tab==="overview"&&<>
   <div className="grid grid-cols-2 gap-4 lg:grid-cols-4"><StatCard label="Total users" value={String(overview?.users_total??"—")} /><StatCard label="Active users" value={String(overview?.active_users??"—")} tone="emerald"/><StatCard label="Open incidents" value={String(overview?.open_incidents??"—")} tone="amber"/><StatCard label="Waste batches" value={String(overview?.waste_batches??"—")} /></div>
   <div className="grid gap-4 md:grid-cols-3">{roles.map(([r,label])=>{const key=r==="hospital"?"pending_hospitals":r==="collector"?"pending_collectors":"pending_facilities";return <div key={r} className="rounded-xl border border-mist-deep bg-paper p-5"><div className="flex items-center gap-2 text-slate"><ShieldCheck size={16}/><span className="text-sm">{label}</span></div><p className="mt-3 font-display text-2xl font-semibold text-charcoal">{overview?.[key] ?? "—"}</p><p className="text-xs text-slate-light">pending verification</p></div>})}</div>
   <div className="grid gap-4 md:grid-cols-3"><Mini icon={<Users size={17}/>} title="User governance" text="Disable compromised or inactive accounts without deleting historical records."/><Mini icon={<AlertTriangle size={17}/>} title="Incident control" text="Resolve operational discrepancies with a traceable admin audit event."/><Mini icon={<FileClock size={17}/>} title="Audit trail" text={`${overview?.audit_events??0} recorded admin events.`}/></div>
  </>}
  {tab==="verification"&&<Verification role={verRole} setRole={setVerRole} items={ver} reload={load}/>} 
  {tab==="users"&&<UsersPanel users={users} reload={load}/>} 
  {tab==="categories"&&<Categories categories={categories} reload={load}/>} 
  {tab==="rules"&&<Rules rules={rules} reload={load}/>} 
  {tab==="incidents"&&<Incidents items={incidents} reload={load}/>} 
  {tab==="workflow failures"&&<WorkflowDeadLetters/>}
  {tab==="pickup exceptions"&&<PickupArrivalExceptions/>}
  {tab==="receipt exceptions"&&<ReceiptExceptions/>}
  {tab==="audit"&&<Audit items={audit}/>} 
 </div>
}
function Mini({icon,title,text}:{icon:React.ReactNode;title:string;text:string}){return <div className="rounded-xl border border-mist-deep bg-paper p-5"><div className="flex items-center gap-2 text-emerald">{icon}<span className="font-medium text-charcoal">{title}</span></div><p className="mt-2 text-sm leading-6 text-slate">{text}</p></div>}
function Verification({role,setRole,items,reload}:{role:UserRole;setRole:(r:UserRole)=>void;items:Verify[];reload:()=>Promise<void>}){return <section><div className="mb-4 flex flex-wrap gap-2">{roles.map(([r,l])=><Button key={r} size="sm" variant={role===r?"default":"outline"} onClick={()=>setRole(r)}>{l}</Button>)}</div><Table headers={["Organization","Contact","Registration","Location","Status","Action"]}>{items.map(x=><tr key={x.id} className="border-t border-mist-deep"><td className="px-4 py-3"><p className="font-medium text-charcoal">{x.organization_name}</p><p className="text-xs text-slate">{x.email}</p></td><td className="px-4 py-3 text-sm">{x.user_name}</td><td className="px-4 py-3 text-sm">{x.registration_number}</td><td className="px-4 py-3 text-sm">{x.city}</td><td className="px-4 py-3 text-sm">{x.is_verified?<span className="text-emerald-dim">Verified</span>:<span className="text-signal-amber">Pending</span>}</td><td className="px-4 py-3"><Button size="sm" variant={x.is_verified?"outline":"emerald"} onClick={async()=>{await api.patch(`/api/v1/admin/verification/${role}/${x.id}?verified=${!x.is_verified}`);await reload();}}>{x.is_verified?"Revoke":"Verify"}</Button></td></tr>)}</Table></section>}
function UsersPanel({users,reload}:{users:AdminUser[];reload:()=>Promise<void>}){return <Table headers={["User","Role","Account","Verification","Action"]}>{users.map(x=><tr key={x.id} className="border-t border-mist-deep"><td className="px-4 py-3"><p className="font-medium text-charcoal">{x.full_name}</p><p className="text-xs text-slate">{x.email}</p></td><td className="px-4 py-3 text-sm capitalize">{x.role}</td><td className="px-4 py-3 text-sm">{x.is_active?"Active":"Disabled"}</td><td className="px-4 py-3 text-sm">{x.is_verified?"Verified":"Pending"}</td><td className="px-4 py-3"><Button size="sm" variant="outline" disabled={x.role==="admin"} onClick={async()=>{await api.patch(`/api/v1/admin/users/${x.id}`,{is_active:!x.is_active,is_verified:x.is_verified});await reload();}}>{x.is_active?"Disable":"Enable"}</Button></td></tr>)}</Table>}
function Categories({categories,reload}:{categories:Category[];reload:()=>Promise<void>}){const [name,setName]=useState("");const [code,setCode]=useState("");return <section className="space-y-5"><div className="rounded-xl border border-mist-deep bg-paper p-5"><h2 className="font-display font-semibold">Add category</h2><div className="mt-3 grid gap-3 md:grid-cols-[1fr_1fr_auto]"><Input value={code} onChange={e=>setCode(e.target.value)} placeholder="code e.g. contaminated-glass"/><Input value={name} onChange={e=>setName(e.target.value)} placeholder="Category name"/><Button onClick={async()=>{await api.post("/api/v1/admin/categories",{code,name,is_recyclable:false});setCode("");setName("");await reload();}}>Create</Button></div></div><Table headers={["Code","Name","Recyclable","Status","Action"]}>{categories.map(c=><tr key={c.id} className="border-t border-mist-deep"><td className="px-4 py-3 font-data text-xs">{c.code}</td><td className="px-4 py-3 text-sm font-medium">{c.name}</td><td className="px-4 py-3 text-sm">{c.is_recyclable?"Yes":"No"}</td><td className="px-4 py-3 text-sm">{c.is_active?"Active":"Retired"}</td><td className="px-4 py-3"><Button size="sm" variant="outline" onClick={async()=>{await api.patch(`/api/v1/admin/categories/${c.id}`,{is_active:!c.is_active});await reload();}}>{c.is_active?"Retire":"Reactivate"}</Button></td></tr>)}</Table></section>}
function Rules({rules,reload}:{rules:Rule[];reload:()=>Promise<void>}){return <Table headers={["Category","Base risk","Quantity threshold (kg)","Active","Action"]}>{rules.map(r=><tr key={r.id} className="border-t border-mist-deep"><td className="px-4 py-3 text-sm font-medium">{r.category_name}</td><td className="px-4 py-3 text-sm capitalize">{r.base_risk_level}</td><td className="px-4 py-3 text-sm">{r.quantity_escalation_threshold??"—"}</td><td className="px-4 py-3 text-sm">{r.is_active?"Yes":"No"}</td><td className="px-4 py-3"><RuleEdit rule={r} reload={reload}/></td></tr>)}</Table>}
function RuleEdit({rule,reload}:{rule:Rule;reload:()=>Promise<void>}){const [risk,setRisk]=useState(rule.base_risk_level);const [threshold,setThreshold]=useState(rule.quantity_escalation_threshold?.toString()??"");return <div className="flex flex-wrap gap-2"><select value={risk} onChange={e=>setRisk(e.target.value)} className="h-9 rounded-md border border-mist-deep bg-paper px-2 text-xs"><option>low</option><option>medium</option><option>high</option><option>critical</option></select><Input className="w-28" value={threshold} onChange={e=>setThreshold(e.target.value)} placeholder="kg"/><Button size="sm" onClick={async()=>{await api.put(`/api/v1/admin/risk-rules/${rule.category_id}`,{base_risk_level:risk,quantity_escalation_threshold:threshold?Number(threshold):null,is_active:rule.is_active});await reload();}}>Save</Button></div>}
function Incidents({items,reload}:{items:Incident[];reload:()=>Promise<void>}){return <Table headers={["Waste","Type","Severity","Description","Status","Action"]}>{items.map(i=><tr key={i.id} className="border-t border-mist-deep"><td className="px-4 py-3 font-data text-xs">{i.waste_code}</td><td className="px-4 py-3 text-xs">{i.incident_type}</td><td className="px-4 py-3 text-xs uppercase">{i.severity}</td><td className="max-w-md px-4 py-3 text-sm">{i.description}</td><td className="px-4 py-3 text-sm">{i.is_resolved?"Resolved":"Open"}</td><td className="px-4 py-3"><Button size="sm" variant="outline" onClick={async()=>{await api.patch(`/api/v1/admin/incidents/${i.id}`,{is_resolved:!i.is_resolved});await reload();}}>{i.is_resolved?"Reopen":"Resolve"}</Button></td></tr>)}</Table>}
function Audit({items}:{items:Audit[]}){return <Table headers={["Time","Actor","Action","Entity","Details"]}>{items.map(a=><tr key={a.id} className="border-t border-mist-deep"><td className="px-4 py-3 text-xs text-slate">{new Date(a.created_at).toLocaleString()}</td><td className="px-4 py-3 text-sm">{a.actor_name??"System"}</td><td className="px-4 py-3 font-data text-xs">{a.action}</td><td className="px-4 py-3 text-xs">{a.entity_type}{a.entity_id?` · ${a.entity_id.slice(0,8)}`:""}</td><td className="max-w-sm px-4 py-3 text-xs text-slate">{JSON.stringify(a.details)}</td></tr>)}</Table>}
function Table({headers,children}:{headers:string[];children:React.ReactNode}){return <div className="overflow-x-auto rounded-xl border border-mist-deep bg-paper"><table className="w-full min-w-[760px] text-left"><thead className="bg-mist/50"><tr>{headers.map(h=><th key={h} className="px-4 py-3 font-data text-[10px] uppercase tracking-[.1em] text-slate-light">{h}</th>)}</tr></thead><tbody>{children}</tbody></table></div>}


function ReceiptExceptions(){
 const [id,setId]=useState("");
 const [reason,setReason]=useState("");
 const [state,setState]=useState("");
 const [busy,setBusy]=useState(false);
 const submit=async()=>{
  if(!/^[0-9a-f-]{36}$/i.test(id.trim()) || reason.trim().length<20){
   setState("Enter a valid 36-character waste batch ID and a specific reason of at least 20 characters.");return;
  }
  setBusy(true);setState("");
  try{
   await api.post(`/api/v1/admin/waste/${id.trim()}/receipt-exception`,{reason:reason.trim()});
   setState("Audited exception granted for 20 minutes. A separate facility operator must confirm the actual handover.");
   setId("");setReason("");
  }catch(e){setState(e instanceof Error?e.message:"Unable to approve exception.");}
  finally{setBusy(false);}
 };
 return <div className="max-w-2xl space-y-4 rounded-2xl border border-mist-deep bg-paper p-6">
  <div className="flex items-center gap-2 text-emerald"><ShieldCheck size={18}/><h2 className="font-display text-xl font-semibold text-charcoal">Facility arrival exception</h2></div>
  <p className="text-sm leading-6 text-slate">Only for independently verified emergency handovers when physical GPS evidence is unavailable. Approval is logged, expires after 20 minutes and does not mark waste received. Simulation does not qualify as real arrival proof.</p>
  <label className="block space-y-1"><span className="text-sm font-medium text-charcoal">Waste batch ID</span><Input value={id} onChange={e=>setId(e.target.value)} placeholder="Paste waste record UUID"/></label>
  <label className="block space-y-1"><span className="text-sm font-medium text-charcoal">Documented reason</span><textarea value={reason} onChange={e=>setReason(e.target.value)} maxLength={500} rows={4} className="w-full rounded-lg border border-mist-deep bg-paper p-3 text-sm text-charcoal" placeholder="Explain independent physical checks and why GPS proof cannot be provided"/></label>
  <Button disabled={busy} onClick={submit}>{busy?"Recording…":"Record audited exception"}</Button>
  {state&&<p role="status" className="rounded-lg bg-mist p-3 text-sm text-charcoal">{state}</p>}
 </div>;
}


/** Issue 9: supervisor review of pickup GPS exceptions (separate from facility receipt). */
type PickupArrivalCandidate = {
  pickup_id: string;
  stop_id: string;
  hospital_name: string;
  vehicle_code: string;
  assigned_driver_id: string;
  estimated_arrival_at: string | null;
  driver_requested_at: string | null;
  driver_reported_reason: string | null;
};

function PickupArrivalExceptions() {
  const [candidates, setCandidates] = useState<PickupArrivalCandidate[]>([]);
  const [pickupId, setPickupId] = useState("");
  const [reason, setReason] = useState("");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [approved, setApproved] = useState(false);
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const rows = await api.get<PickupArrivalCandidate[]>("/api/v1/admin/pickup-arrival-exception-candidates");
      setCandidates(rows);
      setPickupId((current) => rows.some((r) => r.pickup_id === current) ? current : "");
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Could not load active pickup stops.");
    } finally { setLoading(false); }
  }, []);
  useDeferredEffect(() => { void load(); }, [load]);
  const submit = async () => {
    const why = reason.trim();
    if (!pickupId || why.length < 12 || why.length > 500 || !candidates.some((c) => c.pickup_id === pickupId)) {
      setApproved(false);
      setMessage("Select an active en-route pickup and provide a specific reason (12–500 characters).");
      return;
    }
    setBusy(true); setApproved(false); setMessage("");
    try {
      await api.post(`/api/v1/pickups/${encodeURIComponent(pickupId)}/arrival-exception-approval`, {reason: why});
      setApproved(true);
      setMessage("Approval recorded for 20 minutes. Independently share the exact documented reason with the assigned driver. The driver must still scan the hospital QR and submit that SAME reason; approval alone does not mark arrival or collection.");
      await load();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Approval was not recorded.");
    } finally { setBusy(false); }
  };
  const chosen = candidates.find((c) => c.pickup_id === pickupId);
  return <section className="max-w-3xl space-y-4 rounded-2xl border border-mist-deep bg-paper p-6">
    <div className="flex items-center gap-2 text-emerald"><ShieldCheck size={18}/><h2 className="font-display text-xl font-semibold text-charcoal">Hospital pickup · GPS arrival exception</h2></div>
    <p className="text-sm leading-6 text-slate">Use this only after independently verifying the driver and physical hospital handover where trusted GPS is unavailable. Simulation is not arrival evidence. This is separate from facility receipt approval.</p>
    <div className="flex flex-wrap items-center justify-between gap-2"><label htmlFor="pickup-arrival-candidate" className="text-sm font-medium text-charcoal">Active en-route pickup</label><Button size="sm" variant="outline" onClick={() => void load()} disabled={loading || busy}>{loading ? "Refreshing…" : "Refresh list"}</Button></div>
    <select id="pickup-arrival-candidate" value={pickupId} disabled={loading || busy} onChange={(e) => {setPickupId(e.target.value);setApproved(false);setMessage("");}} className="w-full rounded-lg border border-mist-deep bg-paper px-3 py-3 text-sm text-charcoal">
      <option value="">{loading ? "Loading active stops…" : "Select a pickup"}</option>
      {candidates.map((c) => <option key={c.stop_id} value={c.pickup_id}>{c.hospital_name} · {c.vehicle_code} · {c.pickup_id.slice(0,8)}</option>)}
    </select>
    {!loading && candidates.length === 0 && <p className="text-sm text-slate">No active en-route pickup stops require review right now.</p>}
    {chosen && <div className="rounded-lg bg-mist p-3 text-xs text-slate"><p>Pickup: <span className="font-data">{chosen.pickup_id}</span></p><p>Assigned driver: <span className="font-data">{chosen.assigned_driver_id}</span></p><p>Estimated arrival: {chosen.estimated_arrival_at ? new Date(chosen.estimated_arrival_at).toLocaleString() : "Not estimated"}</p><p>Driver review request: {chosen.driver_requested_at ? new Date(chosen.driver_requested_at).toLocaleString() : "No recent request"}</p>{chosen.driver_reported_reason && <p>Driver-reported GPS problem (unverified): {chosen.driver_reported_reason}</p>}</div>}
    <label className="block space-y-1"><span className="text-sm font-medium text-charcoal">Independent physical verification and no-GPS reason</span><textarea value={reason} onChange={(e) => {setReason(e.target.value);setApproved(false);}} maxLength={500} rows={4} placeholder="State what was independently verified and why trusted GPS evidence is unavailable" className="w-full rounded-lg border border-mist-deep bg-paper p-3 text-sm text-charcoal"/></label>
    <p className="text-xs text-slate">The reason is audit-logged. The assigned driver must enter exactly the same reason on the hospital handover page within 20 minutes and present the hospital QR. Do not include QR secrets in this form.</p>
    <Button disabled={busy || loading || !pickupId || reason.trim().length < 12} onClick={() => void submit()}>{busy ? "Recording…" : "Approve no-GPS pickup arrival"}</Button>
    {message && <p role="status" className={`rounded-lg p-3 text-sm ${approved ? "bg-mist text-charcoal" : "bg-signal-rust-bg text-signal-rust"}`}>{message}</p>}
  </section>;
}


/** Durable workflow failures are separate from the main worker heartbeat. */
type WorkflowFailure = {id:string;record_id:string|null;attempts:number;last_error:string|null;dead_lettered_at:string|null};
function WorkflowDeadLetters() {
  const [events,setEvents]=useState<WorkflowFailure[]>([]);
  const [reasons,setReasons]=useState<Record<string,string>>({});
  const [loading,setLoading]=useState(true);
  const [busy,setBusy]=useState("");
  const [message,setMessage]=useState("");
  const reload=async()=>{
    setLoading(true);
    try {setEvents(await api.get<WorkflowFailure[]>("/api/v1/admin/workflow/dead-letters"));}
    catch(e){setMessage(e instanceof Error?e.message:"Could not load failed events.");}
    finally {setLoading(false);}
  };
  useDeferredEffect(()=>{void reload();},[]);
  const requeue=async(id:string)=>{
    const reason=(reasons[id]??"").trim();
    if(reason.length<12){setMessage("Provide a documented recovery reason (12+ characters).");return;}
    setBusy(id);setMessage("");
    try {
      await api.post(`/api/v1/admin/workflow/dead-letters/${encodeURIComponent(id)}/requeue`,{reason});
      setMessage("Event requeued. The worker will verify current permissions before processing.");
      await reload();
    } catch(e) {setMessage(e instanceof Error?e.message:"Requeue failed.");}
    finally {setBusy("");}
  };
  return <section className="space-y-4 rounded-2xl border border-mist-deep bg-paper p-6">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h2 className="font-display text-xl font-semibold text-charcoal">Workflow dead-letter recovery</h2>
      <Button size="sm" variant="outline" disabled={loading||!!busy} onClick={()=>void reload()}>{loading?"Loading…":"Refresh"}</Button>
    </div>
    <p className="text-sm text-slate">Jobs that exhaust five retries stop automatically and appear here. Investigate the underlying failure before manually requeuing. Requeue never bypasses hospital membership or workflow review gates.</p>
    {message&&<p role="status" className="rounded-lg bg-mist p-3 text-sm text-charcoal">{message}</p>}
    {!loading&&events.length===0&&<p className="text-sm text-slate">No dead-letter workflow events.</p>}
    {events.map(row=><div key={row.id} className="space-y-3 rounded-xl border border-mist-deep p-4">
      <div className="text-sm text-charcoal"><strong>Record:</strong> <span className="font-data">{row.record_id??"Unknown"}</span></div>
      <p className="text-xs text-slate">{row.attempts} attempts · {row.last_error??"No failure class recorded"} · {row.dead_lettered_at?new Date(row.dead_lettered_at).toLocaleString():"Time unknown"}</p>
      <label className="block space-y-1"><span className="text-sm font-medium text-charcoal">Recovery reason</span>
        <textarea value={reasons[row.id]??""} maxLength={500} rows={2} onChange={e=>setReasons(prev=>({...prev,[row.id]:e.target.value}))} className="w-full rounded-lg border border-mist-deep bg-paper p-3 text-sm" placeholder="Describe the root-cause fix and why retry is now safe"/>
      </label>
      <Button size="sm" disabled={!!busy||(reasons[row.id]??"").trim().length<12} onClick={()=>void requeue(row.id)}>{busy===row.id?"Requeuing…":"Requeue with audit"}</Button>
    </div>)}
  </section>;
}
