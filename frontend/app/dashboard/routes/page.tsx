"use client";

import { RoutePlanner } from "@/components/dashboard/route-planner";
import { useAuth } from "@/hooks/use-auth";

export default function RoutesPage() {
  const { user } = useAuth();
  if (!user) return null;
  if (user.role !== "collector" && user.role !== "admin") {
    return <div className="rounded-2xl border border-mist-deep bg-paper p-8 text-sm text-slate">Smart route planning is available to logistics operators only.</div>;
  }
  return <RoutePlanner />;
}
