"use client";

import { CollectorOverview } from "@/components/dashboard/collector-overview";
import { HospitalOverview } from "@/components/dashboard/hospital-overview";
import { OrgOverview } from "@/components/dashboard/org-overview";
import { AdminOverview } from "@/components/dashboard/admin-overview";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, activeOrganizationId } from "@/lib/api";
import { useAuth } from "@/hooks/use-auth";

export default function DashboardOverviewPage() {
  const { user } = useAuth();
  const router = useRouter();
  const [checked, setChecked] = useState(false);
  useEffect(() => {
    if (!user || user.role === "admin") return;
    let cancelled = false;
    async function checkMembership() {
      try {
        const orgs = await api.get<{ id: string }[]>("/api/v1/organizations/mine");
        const current = orgs.find(o => o.id === activeOrganizationId()) ?? orgs[0];
        if (current) {
          const members = await api.get<{ user_id: string; member_role: string }[]>(`/api/v1/organizations/${current.id}/members`);
          if (members.find(m => m.user_id === user?.id)?.member_role === "finance") {
            if (!cancelled) router.replace("/dashboard/billing");
            return;
          }
        }
      } finally { if (!cancelled) setChecked(true); }
    }
    void checkMembership().catch(() => {});
    return () => { cancelled = true; };
  }, [user, router]);
  if (!user) return null;
  if (user.role !== "admin" && !checked) return <p className="text-sm text-slate">Loading your workspace…</p>;

  if (user.role === "hospital") {
    return <HospitalOverview fullName={user.full_name} />;
  }

  if (user.role === "collector") {
    return <CollectorOverview fullName={user.full_name} />;
  }

  if (user.role === "facility") {
    return (
      <OrgOverview
        fullName={user.full_name}
        apiBase="facilities"
        orgLabel="facility"
        orgName="your facility"
      />
    );
  }


  return <AdminOverview name={user.full_name} />;
}
