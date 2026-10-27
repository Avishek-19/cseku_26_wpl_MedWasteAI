"use client";

import { BrandMark } from "@/components/layout/brand-mark";
import { useAuth } from "@/hooks/use-auth";
import { activeOrganizationId,api } from "@/lib/api";
import type { UserRole } from "@/types/auth";
import { ArrowUpRight,BadgeCheck,Building2,CalendarDays,ClipboardCheck,History,LayoutDashboard,MapPin,PackageSearch,Route,Settings2,Shield,Truck,UserRound,Wallet,X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect,useState } from "react";

type Item = { href: string; label: string; icon: typeof LayoutDashboard };
const BASE: Item[] = [{ href: "/dashboard", label: "Overview", icon: LayoutDashboard }];
const PER_ROLE: Record<UserRole, Item[]> = {
  hospital: [{ href: "/dashboard/waste", label: "Waste records", icon: PackageSearch }, { href: "/dashboard/pickups", label: "Pickup requests", icon: CalendarDays }, { href: "/dashboard/tracking", label: "Live tracking", icon: MapPin }, { href: "/dashboard/billing", label: "Invoices & credits", icon: Wallet }],
  collector: [{ href: "/dashboard/pickups", label: "Assigned pickups", icon: ClipboardCheck }, { href: "/dashboard/routes", label: "Route planning", icon: Route }, { href: "/dashboard/vehicles", label: "Vehicle fleet", icon: Truck }, { href: "/dashboard/tracking", label: "Live tracking", icon: MapPin }, { href: "/dashboard/handover", label: "Handover", icon: ClipboardCheck }, { href: "/dashboard/transfers", label: "Transfer history", icon: History }, { href: "/dashboard/billing", label: "Finance", icon: Wallet }],
  facility: [{ href: "/dashboard/incoming", label: "Incoming waste", icon: ClipboardCheck }, { href: "/dashboard/tracking", label: "Live tracking", icon: MapPin }, { href: "/dashboard/billing", label: "Finance", icon: Wallet }],
  admin: [{ href: "/dashboard/admin", label: "Control center", icon: Shield }, { href: "/dashboard/governance", label: "Organization approvals", icon: BadgeCheck }, { href: "/dashboard/finance-admin", label: "Contracts & rates", icon: Wallet }, { href: "/dashboard/tracking", label: "Live operations", icon: MapPin },],
};

export function DashboardSidebar({ mobile = false, onNavigate }: { mobile?: boolean; onNavigate?: () => void }) {
  const pathname = usePathname();
  const { user } = useAuth();
  const role = (user?.role ?? "hospital") as UserRole;
  const [memberRole, setMemberRole] = useState<string | null>(null);
  useEffect(() => {
    if (!user || role === 'admin') return;
    const companyId = activeOrganizationId();
    if (!companyId) return; // Legacy standalone profile UI stays available.
    let active = true;
    api.get<{user_id:string;member_role:string}[]>(`/api/v1/organizations/${companyId}/members`)
      .then(members => { if (active) setMemberRole(members.find(m => m.user_id === user.id)?.member_role ?? null); })
      .catch(() => { if (active) setMemberRole(null); });
    return () => { active = false; };
  }, [user, role]);
  const allItems: Item[] = [...BASE, ...(PER_ROLE[role] || []), ...(role !== "admin" ? [{ href: "/dashboard/company", label: "My organization", icon: Building2 }] : []), ...(role !== "admin" ? [{ href: "/dashboard/profile", label: "Organization profile", icon: UserRound }] : []), { href: "/dashboard/settings", label: "Account settings", icon: Settings2 }];
  // UI mirrors server permissions; backend remains the authority.
  const roleNav: Record<string, string[]> = {
    finance: ['/dashboard','/dashboard/billing','/dashboard/settings'],
    worker: ['/dashboard','/dashboard/waste','/dashboard/pickups','/dashboard/incoming','/dashboard/tracking','/dashboard/settings'],
    driver: ['/dashboard','/dashboard/routes','/dashboard/pickups','/dashboard/handover','/dashboard/tracking','/dashboard/transfers','/dashboard/settings'],
    dispatcher: ['/dashboard','/dashboard/routes','/dashboard/pickups','/dashboard/vehicles','/dashboard/tracking','/dashboard/transfers','/dashboard/settings','/dashboard/company'],
  };
  const allowed = memberRole ? roleNav[memberRole] : null;
  const items = allowed ? allItems.filter(item => allowed.includes(item.href)) : allItems;
  return <aside aria-label="Workspace navigation" className={`workspace-sidebar ${mobile ? "workspace-sidebar-mobile" : ""} ${mobile ? "flex h-full w-[min(85vw,290px)]" : "hidden lg:flex w-[270px]"} shrink-0 flex-col bg-[#211632] text-white`}>
    <div className="flex items-center justify-between border-b border-white/10 px-5 py-6">
      <Link href="/dashboard" onClick={onNavigate} className="flex items-center gap-3">
        <BrandMark className="size-11 shrink-0"/>
        <span><strong className="block font-display text-[17px] tracking-tight">MedWaste <span className="text-[#a180d0]">AI</span></strong><span className="block text-[10px] uppercase tracking-[.2em] text-[#bcadd2]">Operations platform</span></span>
      </Link>
      {mobile && <button onClick={onNavigate} aria-label="Close navigation" className="rounded-lg p-2 hover:bg-white/10"><X size={20}/></button>}
    </div>
    <p className="px-6 pb-3 pt-7 text-[10px] font-semibold uppercase tracking-[.2em] text-[#b0a2c4]">Workspace</p>
    <nav className="flex-1 space-y-1 overflow-y-auto px-3 pb-5">
      {items.map(item=>{const exact = item.href === "/dashboard";const active=exact ? pathname===item.href : pathname === item.href || pathname.startsWith(item.href+"/");return <Link key={item.href} href={item.href} onClick={onNavigate} aria-current={active?"page":undefined} className={`workspace-nav-link group flex items-center gap-3 rounded-xl px-3.5 py-3 text-[13px] font-medium transition-colors ${active?"bg-[#4d366d] text-white shadow-sm":"text-[#d9d3e2] hover:bg-white/10 hover:text-white"}`}><item.icon size={18} strokeWidth={1.8}/><span className="flex-1">{item.label}</span>{active && <span className="h-1.5 w-1.5 rounded-full bg-[#c6aee9]"/>}</Link>})}
    </nav>
    <div className="m-4 rounded-2xl border border-[#69528b]/60 bg-[#332349] p-4"><p className="text-xs font-semibold text-[#cfbcea]">Verified workflows first</p><p className="mt-1.5 text-xs leading-5 text-[#dcd5e5]">Chain-of-custody records, safer dispatch and verified billing and payment records.</p>{role !== "admin" ? <Link href="/dashboard/company" onClick={onNavigate} className="mt-3 flex items-center gap-1 text-xs font-semibold text-[#d5c3ee]">Organization setup <ArrowUpRight size={13}/></Link> : <Link href="/dashboard/governance" onClick={onNavigate} className="mt-3 flex items-center gap-1 text-xs font-semibold text-[#d5c3ee]">Review organizations <ArrowUpRight size={13}/></Link>}</div>
  </aside>;
}
