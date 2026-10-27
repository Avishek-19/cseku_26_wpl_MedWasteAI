"use client";
import { NotificationBell } from "@/components/dashboard/notification-bell";
import { useAuth } from "@/hooks/use-auth";
import { activeOrganizationId,api,setActiveOrganizationId } from "@/lib/api";
import { ROLE_LABELS } from "@/types/auth";
import { LogOut,Menu,ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect,useState } from "react";
export function DashboardTopbar({ onMenuClick }: { onMenuClick?: () => void }) {
  const { user, logout } = useAuth(); const router=useRouter();
  const [organizations, setOrganizations] = useState<{id: string; name: string}[]>([]);
  const [chosenOrg, setChosenOrg] = useState('');
  useEffect(() => {
    if (!user || user.role === 'admin') return;
    let live = true;
    api.get<{id: string; name: string}[]>('/api/v1/organizations/mine')
      .then(orgs => {
        if (!live) return;
        setOrganizations(orgs);
        const previous = activeOrganizationId();
        const selected = orgs.find(o => o.id === previous)?.id ?? orgs[0]?.id ?? '';
        setChosenOrg(selected);
        if (previous !== selected) {
          setActiveOrganizationId(selected || null);
          if (selected) window.location.reload();
        }
      }).catch(() => {});
    return () => { live = false };
  }, [user]);
  const choose = (id: string) => {
    setChosenOrg(id); setActiveOrganizationId(id);
    // Existing feature pages fetch on mount: remount when switching company.
    window.location.reload();
  };
  if(!user) return null;
  return <header className="workspace-topbar sticky top-0 z-30 flex h-[72px] shrink-0 items-center justify-between border-b border-[#e2dfe7] bg-white/95 px-4 backdrop-blur lg:px-9">
    <div className="flex items-center gap-3"><button type="button" onClick={onMenuClick} className="rounded-xl border border-[#dbd7e0] p-2.5 text-[#2d1e42] hover:bg-[#eeebf3] lg:hidden" aria-label="Open navigation"><Menu size={20}/></button><Link href="/dashboard" className="font-display text-[17px] font-bold text-[#281d39] hidden sm:block lg:hidden">MedWaste <span className="text-[#4d3076]">AI</span></Link><div className="hidden lg:block"><p className="text-xs font-semibold uppercase tracking-[.16em] text-[#5e4b7a]">MedWaste AI / Workspace</p><p className="text-sm font-medium text-[#534b5e]">A clearer view of healthcare waste operations</p></div></div>
    <div className="flex min-w-0 items-center gap-2 sm:gap-3">{organizations.length > 0 && user.role !== 'admin' && <label className="flex min-w-0 items-center gap-2 text-xs font-semibold text-[#48395e]"><span className="sr-only">Active organization</span><select aria-label="Active organization" value={chosenOrg} onChange={e => choose(e.target.value)} className="max-w-[96px] sm:max-w-[190px] rounded-xl border border-[#dcd7e3] bg-[#f6f4f9] px-2.5 py-2 text-xs font-medium text-[#2f2045] outline-none focus:ring-2 focus:ring-[#4d2d7c]/30">{organizations.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}</select></label>}<span className="hidden items-center gap-1.5 rounded-full bg-[#ede9f2] px-3 py-1.5 text-[11px] font-semibold text-[#3f2d59] sm:inline-flex"><ShieldCheck size={14}/>{ROLE_LABELS[user.role]}</span><NotificationBell/><div className="hidden border-l border-[#dfdce4] pl-4 sm:block"><p className="max-w-[180px] truncate text-xs font-semibold text-[#261b36]">{user.full_name}</p><p className="max-w-[180px] truncate text-[11px] text-[#70677c]">{user.email}</p></div><span className="hidden sm:grid h-9 w-9 place-items-center rounded-full bg-[#352152] text-sm font-bold text-white" aria-hidden="true">{user.full_name?.charAt(0).toUpperCase()||"U"}</span><button aria-label="Sign out" type="button" onClick={async()=>{await logout();router.replace("/login")}} className="rounded-xl border border-[#e4e2e8] p-2.5 text-[#423653] hover:bg-[#f3f1f7]"><LogOut size={17}/></button></div>
  </header>;
}
