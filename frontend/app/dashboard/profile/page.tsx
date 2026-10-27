"use client";

import { AccountInfoCard } from "@/components/dashboard/account-info-card";
import { HospitalProfileForm } from "@/components/dashboard/hospital-profile-form";
import { OrgProfileForm } from "@/components/dashboard/org-profile-form";
import { useAuth } from "@/hooks/use-auth";

export default function ProfilePage() {
  const { user } = useAuth();
  if (!user) return null;

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <h1 className="font-display text-2xl font-semibold text-charcoal">Profile</h1>
        <p className="mt-1.5 text-[14px] text-slate">
          Manage your account and organization details.
        </p>
      </div>

      <AccountInfoCard user={user} />

      {user.role === "hospital" && <HospitalProfileForm />}
      {user.role === "facility" && <OrgProfileForm />}
    </div>
  );
}
