"use client";

import { DriverGpsPublisher } from "@/components/dashboard/driver-gps-publisher";
import { RoleLiveTracking } from "@/components/dashboard/role-live-tracking";
import { useAuth } from "@/hooks/use-auth";

export default function TrackingPage() {
  const { user } = useAuth();
  if (!user) return null;
  return <div className="space-y-4">{user.role === "collector" && <DriverGpsPublisher />}<RoleLiveTracking role={user.role} /></div>;
}
