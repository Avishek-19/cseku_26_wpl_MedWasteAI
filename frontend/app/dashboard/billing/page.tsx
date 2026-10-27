"use client";

import { Button } from "@/components/ui/button";
import { activeOrganizationId,api } from "@/lib/api";
import { ArrowUpRight,CreditCard,ReceiptText,RefreshCw,ShieldCheck,Wallet } from "lucide-react";
import Link from "next/link";
import { useCallback,useEffect,useRef,useState } from "react";

type Org = { id: string; name: string; org_type: string };
type Invoice = { id: string; cycle_start: string; cycle_end: string; gross_bdt: string; credits_bdt: string; due_bdt: string; paid_bdt: string; state: string };
type Subscription = { id: string; state: string; price_bdt: string; period_start: string; period_end: string };
type Payment = { reference: string; amount_bdt: string; state: string; channel_label: string; provider_transaction_id: string | null; created_at: string; verified_at: string | null; mode: string };
type Config = { mode: string; enabled: boolean; channel_note: string };
type Checkout = Payment & { checkout_url: string | null };
type Earnings = { total_accrued_bdt: string; accrued_service_bdt: string; recycling_profit_share_bdt: string; accrued_on_paid_invoices_bdt: string; note: string };
type Eligibility = { free_jobs_left: number; can_accept_new_work: boolean };
const currency = (value: string | number) => new Intl.NumberFormat("en-BD", { style: "currency", currency: "BDT", maximumFractionDigits: 2 }).format(Number(value));
const date = (value: string) => new Date(value).toLocaleDateString("en-BD", { day: "numeric", month: "short", year: "numeric" });
const methods = [{ id: "bkash", label: "bKash" }, { id: "nagad", label: "Nagad" }, { id: "rocket", label: "Rocket" }, { id: "card", label: "Bank card" }];

export default function BillingPage() {
  const [org, setOrg] = useState<Org | null>(null);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [subscriptions, setSubscriptions] = useState<Subscription[]>([]);
  const [history, setHistory] = useState<Payment[]>([]);
  const [config, setConfig] = useState<Config | null>(null);
  const [earnings, setEarnings] = useState<Earnings | null>(null);
  const [eligibility, setEligibility] = useState<Eligibility | null>(null);
  const [channel, setChannel] = useState("bkash");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const keys = useRef<Record<string, string>>({});

  const load = useCallback(async () => {
    try {
      const [organizations, cfg] = await Promise.all([
        api.get<Org[]>("/api/v1/organizations/mine"), api.get<Config>("/api/v1/payments/config"),
      ]);
      setConfig(cfg);
      const selected = organizations.find(o => o.id === activeOrganizationId()) ?? organizations[0];
      setOrg(selected ?? null);
      if (!selected) return;
      const payments = await api.get<Payment[]>(`/api/v1/payments/history?org_id=${selected.id}`);
      setHistory(payments);
      if (selected.org_type === "HOSPITAL") {
        setInvoices(await api.get<Invoice[]>(`/api/v1/invoices?org_id=${selected.id}`));
      } else {
        const [subs, accrued, eligible] = await Promise.all([
          api.get<Subscription[]>(`/api/v1/organizations/${selected.id}/subscriptions`),
          api.get<Earnings>(`/api/v1/organizations/${selected.id}/earnings`),
          api.get<Eligibility>(`/api/v1/organizations/${selected.id}/eligibility`),
        ]);
        setSubscriptions(subs); setEarnings(accrued); setEligibility(eligible);
      }
    } catch (e) { setError(e instanceof Error ? e.message : "Could not load billing records"); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => {
    let cancelled = false;
    const initialize = async () => {
      await load();
      const reference = new URLSearchParams(window.location.search).get("payment_ref");
      if (!cancelled && reference && /^MW[A-Z0-9]{24}$/.test(reference)) {
        try {
          const payment = await api.post<Payment>(`/api/v1/payments/${reference}/refresh`);
          if (!cancelled) setMessage(payment.state === "succeeded" ? "Payment verified and recorded. Your billing balance has been updated." : `Payment status: ${payment.state.replaceAll("_", " ")}. Check the transaction history below.`);
          await load();
        } catch (e) { if (!cancelled) setError(e instanceof Error ? e.message : "Payment verification is temporarily unavailable"); }
      }
    };
    void initialize();
    return () => { cancelled = true; };
  }, [load]);

  async function pay(kind: "invoice" | "subscription", id: string) {
    setBusy(true); setError(""); setMessage("");
    const key = `${kind}:${id}:${channel}`;
    keys.current[key] ??= crypto.randomUUID();
    try {
      const checkout = await api.post<Checkout>("/api/v1/payments/checkout", {
        target_kind: kind, target_id: id, channel, idempotency_key: keys.current[key],
      });
      if (checkout.state === "succeeded") { setMessage("This payment is already verified."); await load(); return; }
      if (["failed", "cancelled", "expired"].includes(checkout.state)) { delete keys.current[key]; throw new Error("This checkout has ended. Select Pay again to create a new transaction."); }
      if (!checkout.checkout_url) throw new Error(`Payment ${checkout.reference} is awaiting verification. Refresh its status in payment history.`);
      const url = new URL(checkout.checkout_url);
      if (url.protocol !== "https:" || !url.hostname.endsWith(".sslcommerz.com")) throw new Error("The payment provider returned an invalid checkout address");
      window.location.assign(url.href);
    } catch (e) { setError(e instanceof Error ? e.message : "Unable to start payment"); await load(); }
    finally { setBusy(false); }
  }

  async function verify(reference: string) {
    setBusy(true); setError("");
    try {
      const payment = await api.post<Payment>(`/api/v1/payments/${reference}/refresh`);
      setMessage(`Payment ${reference}: ${payment.state.replaceAll("_", " ")}`);
      await load();
    } catch (e) { setError(e instanceof Error ? e.message : "Unable to verify payment"); }
    finally { setBusy(false); }
  }

  const totalDue = invoices.reduce((sum, inv) => sum + Math.max(0, Number(inv.due_bdt) - Number(inv.paid_bdt)), 0);
  const totalPaid = history.filter(p => p.state === "succeeded").reduce((sum, p) => sum + Number(p.amount_bdt), 0);
  const pending = history.filter(p => ["pending", "created", "review_required"].includes(p.state)).length;
  const isHospital = org?.org_type === "HOSPITAL";
  return <section className="mx-auto max-w-7xl space-y-6 pb-10">
    <header className="flex flex-wrap items-end justify-between gap-4">
      <div><p className="eyebrow">Finance workspace</p><h1 className="mt-2 font-display text-3xl font-semibold tracking-tight">Billing &amp; payments</h1><p className="mt-2 text-sm text-slate">{org?.name ?? "Your organization"} · Clear balances, traceable transactions.</p></div>
      <Button variant="outline" disabled={busy || loading} onClick={() => { setError(""); void load(); }}><RefreshCw size={15} />Refresh records</Button>
    </header>
    {error && <p role="alert" className="rounded-xl border border-signal-rust/25 bg-signal-rust-bg p-4 text-sm text-signal-rust">{error}</p>}
    {message && <p role="status" className="rounded-xl border border-forest/20 bg-mist p-4 text-sm text-forest">{message}</p>}
    {loading ? <div className="workspace-panel p-10 text-sm text-slate" role="status">Loading financial records…</div> : !org ? <div className="workspace-panel p-10"><Wallet className="text-forest"/><h2 className="mt-4 font-display text-xl">Set up your organization</h2><p className="mt-2 text-sm text-slate">Invoices and payments appear here after your organization is created.</p><Button asChild className="mt-5"><Link href="/dashboard/company">Organization setup<ArrowUpRight size={15}/></Link></Button></div> : <>
      <div className="grid gap-4 sm:grid-cols-3">
        {[{ label: isHospital ? "Outstanding balance" : "Accrued earnings", value: isHospital ? currency(totalDue) : currency(earnings?.total_accrued_bdt ?? 0), icon: Wallet },
          { label: "Verified payments", value: currency(totalPaid), icon: ShieldCheck },
          { label: "Awaiting verification", value: String(pending), icon: ReceiptText }].map(({ label, value, icon: Icon }) => <div key={label} className="workspace-panel p-5"><div className="flex items-center justify-between"><p className="text-xs font-medium text-slate">{label}</p><Icon size={17} className="text-forest"/></div><p className="mt-4 font-display text-3xl font-semibold tracking-tight">{value}</p></div>)}
      </div>
      <div className="workspace-panel overflow-hidden">
        <div className="border-b border-mist-deep px-6 py-5"><h2 className="font-display text-lg font-semibold">{isHospital ? "Service invoices" : "Operator subscription"}</h2><p className="mt-1 text-xs text-slate">{isHospital ? "Your agreed rates and verified service quantities." : `${eligibility?.free_jobs_left ?? 0} introductory jobs remaining · ${eligibility?.can_accept_new_work ? "Eligible for new assignments" : "Verification or subscription required"}`}</p></div>
        <div className="px-6 py-5">
          {config?.enabled ? <fieldset disabled={busy} className="mb-5"><legend className="mb-2 text-xs font-semibold text-slate">Preferred payment method</legend><div className="flex flex-wrap gap-2">{methods.map(m => <button type="button" aria-pressed={channel === m.id} onClick={() => setChannel(m.id)} key={m.id} className={`rounded-lg border px-4 py-2 text-sm font-medium transition ${channel === m.id ? "border-forest bg-forest text-white" : "border-mist-deep bg-white text-slate hover:border-forest"}`}>{m.label}</button>)}</div><p className="mt-2 text-xs text-slate">{config.channel_note}{config.mode === "sandbox" ? " Testing gateway: transactions do not transfer real funds." : ""}</p></fieldset> : <div className="mb-5 flex gap-3 rounded-xl bg-mist p-4 text-sm text-slate"><CreditCard size={18} className="shrink-0 text-forest"/><p>Online checkout is awaiting merchant configuration. Your invoices and payment records remain available.</p></div>}
          {(isHospital ? invoices : subscriptions).length === 0 ? <p className="py-7 text-center text-sm text-slate">No {isHospital ? "service invoices" : "subscription invoices"} have been issued yet.</p> : <div className="space-y-3">{isHospital ? invoices.map(inv => <div key={inv.id} className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-mist-deep p-4"><div><p className="text-sm font-semibold">{date(inv.cycle_start)} – {date(inv.cycle_end)}</p><p className="mt-1 text-xs text-slate">Charges {currency(inv.gross_bdt)} · Credits {currency(inv.credits_bdt)} · Paid {currency(inv.paid_bdt)}</p><p className="mt-2 text-[11px] font-semibold uppercase tracking-wide text-forest">{inv.state.replaceAll("_", " ")}</p></div><div className="flex items-center gap-4"><strong className="font-display text-xl">{currency(Math.max(0, Number(inv.due_bdt) - Number(inv.paid_bdt)))}</strong><Button disabled={busy || !config?.enabled || !["issued", "partially_paid"].includes(inv.state) || Number(inv.due_bdt) <= Number(inv.paid_bdt)} onClick={() => void pay("invoice", inv.id)}>Pay invoice<ArrowUpRight size={14}/></Button></div></div>) : subscriptions.map(sub => <div key={sub.id} className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-mist-deep p-4"><div><p className="text-sm font-semibold">{date(sub.period_start)} – {date(sub.period_end)}</p><p className="mt-1 text-xs capitalize text-slate">{sub.state}</p></div><div className="flex items-center gap-4"><strong>{currency(sub.price_bdt)}</strong><Button disabled={busy || !config?.enabled || sub.state !== "unpaid"} onClick={() => void pay("subscription", sub.id)}>Pay subscription</Button></div></div>)}</div>}
        </div>
      </div>
      {earnings && <div className="workspace-panel p-6"><h2 className="font-display text-lg font-semibold">Operator earnings</h2><div className="mt-4 grid gap-5 sm:grid-cols-3">{[["Service earnings", earnings.accrued_service_bdt], ["From settled invoices", earnings.accrued_on_paid_invoices_bdt], ["Recycling allocation", earnings.recycling_profit_share_bdt]].map(([label, value]) => <div key={label}><p className="text-xs text-slate">{label}</p><p className="mt-1 font-display text-xl font-semibold">{currency(value)}</p></div>)}</div><p className="mt-4 text-xs text-slate">{earnings.note}</p></div>}
      <div className="workspace-panel overflow-hidden"><div className="border-b border-mist-deep px-6 py-5"><h2 className="font-display text-lg font-semibold">Payment history</h2><p className="mt-1 text-xs text-slate">Every checkout reference and verified provider receipt is stored with your organization.</p></div><div className="overflow-x-auto">{history.length ? <table className="w-full min-w-[700px] text-left text-sm"><thead className="bg-mist/50 text-xs text-slate"><tr>{["Date / reference", "Method", "Amount", "Status", "Verification"].map(h => <th key={h} className="px-6 py-3 font-medium">{h}</th>)}</tr></thead><tbody>{history.map(p => <tr key={p.reference} className="border-t border-mist-deep"><td className="px-6 py-4"><p>{date(p.created_at)}</p><p className="mt-1 font-mono text-[10px] text-slate">{p.reference}</p>{p.provider_transaction_id && <p className="mt-1 text-[10px] text-slate">Receipt: {p.provider_transaction_id}</p>}</td><td className="px-6 py-4">{p.channel_label}</td><td className="px-6 py-4 font-semibold tabular-nums">{currency(p.amount_bdt)}</td><td className="px-6 py-4"><span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold capitalize ${p.state === "succeeded" ? "bg-mist text-forest" : "bg-amber-50 text-amber-800"}`}>{p.state.replaceAll("_", " ")}</span></td><td className="px-6 py-4">{p.state === "succeeded" ? <ShieldCheck size={17} className="text-forest" aria-label="Verified"/> : <Button size="sm" variant="outline" disabled={busy || !config?.enabled} onClick={() => void verify(p.reference)}>Check status</Button>}</td></tr>)}</tbody></table> : <p className="px-6 py-12 text-center text-sm text-slate">No payment transactions yet.</p>}</div></div>
      <p className="flex items-center gap-2 text-xs text-slate"><ShieldCheck size={14}/>Payments are verified by the provider. Enter payment credentials only on the secure hosted checkout.</p>
    </>}
  </section>;
}
