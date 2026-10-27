"use client";

import { Suspense } from "react";

import { CollectorPickupsList } from "@/components/dashboard/pickups/collector-pickups-list";
import { HospitalPickupsList } from "@/components/dashboard/pickups/hospital-pickups-list";
import { useAuth } from "@/hooks/use-auth";

export default function PickupsPage() {
  const { user } = useAuth();
  if (!user) return null;

  if (user.role === "collector") {
    return <CollectorPickupsList />;
  }

  return (
    <Suspense fallback={<p className="text-[14px] text-slate">Loading…</p>}>
      <HospitalPickupsList />
    </Suspense>
  );
}
