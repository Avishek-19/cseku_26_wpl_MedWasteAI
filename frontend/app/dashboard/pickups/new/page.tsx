import { Suspense } from "react";

import { PickupRequestForm } from "@/components/dashboard/pickups/pickup-request-form";

export default function NewPickupPage() {
  return (
    <Suspense fallback={<p className="text-[14px] text-slate">Loading…</p>}>
      <PickupRequestForm />
    </Suspense>
  );
}
