"use client";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { useEffect,useState } from "react";
type Row = { reference: string; organization_id: string; amount_bdt: string; state: string; mode: string; channel_label: string; provider_transaction_id: string | null; created_at: string };
export function PaymentAdmin() {
  const [rows, setRows] = useState<Row[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function load() {
    setBusy(true); setError("");
    try { setRows(await api.get<Row[]>("/api/v1/payments/admin/history")); }
    catch (e) { setError(e instanceof Error ? e.message : "Cannot load payment records"); }
    finally { setBusy(false); }
  }
  useEffect(() => { void api.get<Row[]>("/api/v1/payments/admin/history").then(setRows).catch((e: Error) => setError(e.message)); }, []);
  async function refresh(reference: string) {
    setBusy(true); setError("");
    try { await api.post(`/api/v1/payments/${reference}/refresh`); await load(); }
    catch (e) { setError(e instanceof Error ? e.message : "Verification unavailable"); }
    finally { setBusy(false); }
  }
  return <section className="workspace-panel overflow-hidden"><div className="flex flex-wrap items-center justify-between gap-3 border-b border-mist-deep px-6 py-5"><div><h2 className="font-display text-xl font-semibold">Payment operations</h2><p className="mt-1 text-xs text-slate">Durable checkout records and provider receipts across all organizations.</p></div><Button variant="outline" disabled={busy} onClick={() => void load()}>Refresh records</Button></div>{error && <p className="p-4 text-sm text-signal-rust" role="alert">{error}</p>}<div className="overflow-x-auto"><table className="w-full min-w-[700px] text-left text-xs"><thead className="bg-mist text-slate"><tr>{["Reference / receipt", "Date", "Channel", "Amount", "Status", "Action"].map(h => <th key={h} className="px-5 py-3">{h}</th>)}</tr></thead><tbody>{rows.map(row => <tr key={row.reference} className="border-t border-mist-deep"><td className="px-5 py-4 font-mono text-[10px]">{row.reference}<p className="mt-1 text-slate">{row.provider_transaction_id ?? "Awaiting receipt"}</p></td><td className="px-5 py-4">{new Date(row.created_at).toLocaleDateString()}</td><td className="px-5 py-4">{row.channel_label}</td><td className="px-5 py-4">৳{row.amount_bdt}</td><td className="px-5 py-4 capitalize">{row.state.replaceAll("_", " ")}</td><td className="px-5 py-4">{row.state !== "succeeded" && <Button size="sm" variant="outline" disabled={busy} onClick={() => void refresh(row.reference)}>Verify status</Button>}</td></tr>)}</tbody></table>{rows.length === 0 && <p className="p-8 text-center text-sm text-slate">No payment transactions recorded yet.</p>}</div></section>;
}
