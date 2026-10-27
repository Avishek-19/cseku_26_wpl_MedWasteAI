"use client";
import { useDeferredEffect } from "@/hooks/use-deferred-effect";

import { api } from "@/lib/api";
import { useCallback,useMemo,useState,type FormEvent } from "react";

type FacilityOrg = { id: string; name: string; org_type: string; status?: string };
type EligibleBatch = {
  id: string; waste_code: string; hospital_name: string; hospital_org_id: string;
  received_kg: string; category: string; processed_at: string;
};
type SaleLot = { id: string; waste_record_id: string; contribution_kg: string; hospital_org_id: string };
type Allocation = {
  hospital_org_id: string; contribution_kg: string;
  hospital_credit_bdt: string; facility_share_bdt: string; platform_share_bdt: string;
};
type AuditEvent = { action: string; actor_user_id: string | null; created_at: string };
type Sale = {
  id: string; facility_org_id: string; source_reference: string; buyer_invoice_ref: string;
  proceeds_bdt: string; approved_costs_bdt: string; sale_payment_verified: boolean;
  receipt_review: { bank_reference: string; submitted_by: string; received_on: string; received_bdt: string; evidence_note: string; state: string } | null;
  lots: SaleLot[]; allocations: Allocation[]; audit_history: AuditEvent[];
};
const control = "w-full rounded-xl border border-[#d6d1de] bg-white px-3 py-2.5 text-sm outline-none focus:border-[#553584]";
const action = "rounded-xl bg-[#372255] px-4 py-2.5 text-sm font-semibold text-white hover:bg-[#26153f] disabled:opacity-50";

/** Audited accounting: every selected batch is revalidated by the API before posting. */
export function RecyclingFinanceAdmin({ organizations }: { organizations: FacilityOrg[] }) {
  const facilities = useMemo(() => organizations.filter(org => org.org_type === "TREATMENT_FACILITY" && org.status === "verified"), [organizations]);
  const [facilityId, setFacilityId] = useState("");
  const [batches, setBatches] = useState<EligibleBatch[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [sales, setSales] = useState<Sale[]>([]);
  const [reference, setReference] = useState("");
  const [clearance, setClearance] = useState("");
  const [buyerInvoice, setBuyerInvoice] = useState("");
  const [proceeds, setProceeds] = useState("");
  const [costs, setCosts] = useState("");
  const [receiptRefs, setReceiptRefs] = useState<Record<string, string>>({});
  const [evidenceNotes, setEvidenceNotes] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  useDeferredEffect(() => {
    if (!facilities.some(f => f.id === facilityId)) setFacilityId(facilities[0]?.id ?? "");
  }, [facilityId, facilities]); // organizations is refreshed by parent after mutations

  const refresh = useCallback(async (id: string) => {
    setLoading(true);
    try {
      const [salesData, candidateData] = await Promise.all([
        api.get<Sale[]>("/api/v1/admin/recycling/sales"),
        id ? api.get<EligibleBatch[]>(`/api/v1/admin/recycling/eligible-batches?facility_org_id=${encodeURIComponent(id)}`) : Promise.resolve([]),
      ]);
      setSales(salesData);
      setBatches(candidateData);
      setSelected(old => old.filter(batchId => candidateData.some(batch => batch.id === batchId)));
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load recycling data");
    } finally { setLoading(false); }
  }, []);

  useDeferredEffect(() => { void refresh(facilityId); }, [facilityId, refresh]);

  const createSale = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!facilityId || selected.length === 0) return;
    setBusy(true); setError(""); setMessage("");
    try {
      await api.post("/api/v1/admin/recycling/sales", {
        facility_org_id: facilityId, source_reference: reference.trim(),
        clearance_reference: clearance.trim(), buyer_invoice_ref: buyerInvoice.trim(),
        proceeds_bdt: proceeds, approved_costs_bdt: costs, waste_record_ids: selected,
      });
      setSelected([]); setReference(""); setClearance(""); setBuyerInvoice("");
      setProceeds(""); setCosts("");
      setMessage("Recycling sale created. An Admin must separately attest the receipt before credits are posted.");
      await refresh(facilityId);
    } catch (err) { setError(err instanceof Error ? err.message : "Could not create sale"); }
    finally { setBusy(false); }
  };

  const confirmReceipt = async (saleId: string) => {
    const bankRef = sales.find(s => s.id === saleId)?.receipt_review?.bank_reference ?? receiptRefs[saleId]?.trim() ?? "";
    if (bankRef.length < 8) { setError("A receipt reference of at least 8 characters is required."); return; }
    setBusy(true); setError(""); setMessage("");
    try {
      await api.post(`/api/v1/admin/recycling/sales/${saleId}/confirm-receipt`, { bank_receipt_reference: bankRef });
      setMessage("Receipt independently approved and recycling credits allocated.");
      setReceiptRefs(prev => ({ ...prev, [saleId]: "" }));
      await refresh(facilityId);
    } catch (err) { setError(err instanceof Error ? err.message : "Receipt confirmation failed"); }
    finally { setBusy(false); }
  };

  async function submitEvidence(sale: Sale) {
    setBusy(true); setError(""); setMessage("");
    try {
      await api.post(`/api/v1/admin/recycling/sales/${sale.id}/receipt-evidence`, {
        bank_reference: receiptRefs[sale.id]?.trim(), received_bdt: sale.proceeds_bdt,
        received_on: new Date().toISOString().slice(0, 10), evidence_note: evidenceNotes[sale.id]?.trim(),
      });
      setMessage("Bank evidence saved. A different administrator can now approve the receipt.");
      await refresh(facilityId);
    } catch (e) { setError(e instanceof Error ? e.message : "Could not submit receipt evidence"); }
    finally { setBusy(false); }
  }

  return <section className="rounded-2xl border border-[#e1dee6] bg-white p-5 shadow-sm md:p-7" aria-label="Recycling sale accounting">
    <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
      <div><h2 className="text-xl font-semibold">5. Verified recycling sales & profit allocation</h2>
        <p className="mt-1 text-sm text-[#726a7d]">Select facility-verified, processed waste batches. Distribution uses received input kg, not claimed recovered-output kg.</p></div>
      <button type="button" className={action} disabled={busy || loading} onClick={() => void refresh(facilityId)}>Refresh records</button>
    </div>
    <p className="mb-4 rounded-xl bg-mist p-4 text-sm text-slate">Record bank evidence, then have a second administrator independently verify the receipt before profit allocation.</p>
    {error && <p role="alert" className="mb-3 rounded-lg bg-red-50 p-3 text-sm text-red-800">{error}</p>}
    {message && <p role="status" className="mb-3 rounded-lg bg-green-50 p-3 text-sm text-green-900">{message}</p>}
    <form className="space-y-4" onSubmit={e => void createSale(e)}>
      <label className="block text-sm font-semibold">Verified treatment facility
        <select aria-label="Recycling facility" required value={facilityId} onChange={e => { setFacilityId(e.target.value); setSelected([]); }} className={`${control} mt-1`}>
          {facilities.length === 0 && <option value="">No verified facility</option>}
          {facilities.map(org => <option key={org.id} value={org.id}>{org.name}</option>)}
        </select>
      </label>
      <div className="rounded-xl border border-[#e1dee6] p-3">
        <p className="font-semibold text-sm">Eligible verified batches ({selected.length} selected)</p>
        {loading ? <p className="text-sm">Loading...</p> : batches.length === 0 ?
          <p className="mt-2 text-sm text-[#726a7d]">No unallocated completed recycling batches for this facility.</p> :
          <div className="mt-2 max-h-60 space-y-2 overflow-y-auto">{batches.map(batch => <label key={batch.id} className="flex items-start gap-3 rounded-lg bg-[#f7f6f9] p-2 text-sm">
            <input type="checkbox" className="mt-1" checked={selected.includes(batch.id)} onChange={e => setSelected(prev => e.target.checked ? [...prev, batch.id] : prev.filter(id => id !== batch.id))} />
            <span><strong>{batch.waste_code}</strong> — {batch.hospital_name}<span className="block text-xs text-[#726a7d]">{batch.category} · {batch.received_kg} kg received · {batch.processed_at.slice(0,10)}</span></span>
          </label>)}</div>}
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        <label className="text-xs font-semibold">Source / lot reference<input required minLength={4} maxLength={120} value={reference} onChange={e => setReference(e.target.value)} className={`${control} mt-1`} /></label>
        <label className="text-xs font-semibold">Clearance reference<input required minLength={4} maxLength={120} value={clearance} onChange={e => setClearance(e.target.value)} className={`${control} mt-1`} /></label>
        <label className="text-xs font-semibold">Buyer invoice reference<input required minLength={4} maxLength={120} value={buyerInvoice} onChange={e => setBuyerInvoice(e.target.value)} className={`${control} mt-1`} /></label>
        <label className="text-xs font-semibold">Gross proceeds (BDT)<input type="number" required min="0" step="0.01" value={proceeds} onChange={e => setProceeds(e.target.value)} className={`${control} mt-1`} /></label>
        <label className="text-xs font-semibold">Approved costs (BDT)<input type="number" required min="0" step="0.01" value={costs} onChange={e => setCosts(e.target.value)} className={`${control} mt-1`} /></label>
      </div>
      <button className={action} disabled={busy || !facilityId || !selected.length || loading}>Create verified-batch sale</button>
    </form>
    <div className="mt-7 space-y-3"><h3 className="text-lg font-semibold">Sales, receipts & allocation history</h3>
      {sales.length === 0 && <p className="text-sm text-[#726a7d]">No recycling sales yet.</p>}
      {sales.map(sale => <article key={sale.id} className="rounded-xl border border-[#e1dee6] p-4 text-sm">
        <div className="flex flex-wrap justify-between gap-2"><div><p className="font-semibold">{sale.source_reference} — {organizations.find(o => o.id === sale.facility_org_id)?.name ?? sale.facility_org_id}</p>
          <p className="text-xs text-[#726a7d]">Buyer invoice {sale.buyer_invoice_ref} · {sale.lots.length} verified lots · ৳{sale.proceeds_bdt} gross / ৳{sale.approved_costs_bdt} costs</p></div>
          <span className="font-semibold">{sale.sale_payment_verified ? "Receipt attested / allocated" : "Pending receipt"}</span></div>
        {sale.lots.length > 0 && <p className="mt-2 text-xs text-[#726a7d]">Lot IDs: {sale.lots.map(l => l.waste_record_id.slice(0,8)).join(", ")}</p>}
        {!sale.sale_payment_verified && (sale.receipt_review ? <div className="mt-4 rounded-xl bg-mist p-4"><p className="text-xs text-slate">Receipt {sale.receipt_review.bank_reference} · submitted {sale.receipt_review.received_on}. A different administrator must review the bank evidence.</p><p className="mt-2 text-xs text-slate">Received: ৳{sale.receipt_review.received_bdt}</p><p className="mt-2 whitespace-pre-wrap rounded-lg border border-mist-deep bg-white p-3 text-sm">{sale.receipt_review.evidence_note}</p><button type="button" className={`${action} mt-3`} disabled={busy} onClick={() => void confirmReceipt(sale.id)}>Independently approve & allocate</button></div> : <div className="mt-4 space-y-3"><label className="block text-xs font-semibold">Bank receipt reference<input className={`${control} mt-1`} minLength={8} maxLength={120} value={receiptRefs[sale.id] ?? ""} onChange={e => setReceiptRefs(prev => ({ ...prev, [sale.id]: e.target.value }))} /></label><label className="block text-xs font-semibold">Bank reconciliation evidence<textarea className={`${control} mt-1`} minLength={20} maxLength={2000} placeholder="Statement date, bank account, receipt amount and how the credit was reconciled." value={evidenceNotes[sale.id] ?? ""} onChange={e => setEvidenceNotes(prev => ({ ...prev, [sale.id]: e.target.value }))}/></label><button type="button" className={action} disabled={busy || (receiptRefs[sale.id]?.trim().length ?? 0) < 8 || (evidenceNotes[sale.id]?.trim().length ?? 0) < 20} onClick={() => void submitEvidence(sale)}>Submit bank evidence</button></div>)}
        {sale.audit_history.length > 0 && <div className="mt-3 text-xs text-[#726a7d]"><p className="font-semibold">Audited activity</p>
          <ul className="mt-1 space-y-1">{sale.audit_history.map((entry, index) => <li key={`${entry.action}-${index}`}>{entry.created_at.slice(0,19).replace("T", " ")} — {entry.action}</li>)}</ul></div>}
        {sale.allocations.length > 0 && <div className="mt-3 overflow-x-auto"><table className="w-full min-w-[450px] text-left text-xs"><thead><tr><th className="py-1">Hospital organization</th><th>Input kg</th><th>Hospital 60%</th><th>Facility 30%</th><th>Platform 10%</th></tr></thead>
          <tbody>{sale.allocations.map(a => <tr key={a.hospital_org_id} className="border-t border-[#e7e4ec]"><td className="py-2">{organizations.find(o => o.id === a.hospital_org_id)?.name ?? a.hospital_org_id}</td><td>{a.contribution_kg}</td><td>৳{a.hospital_credit_bdt}</td><td>৳{a.facility_share_bdt}</td><td>৳{a.platform_share_bdt}</td></tr>)}</tbody></table></div>}
      </article>)}
    </div>
  </section>;
}
