import { Suspense } from "react";

import { WasteTable } from "@/components/dashboard/waste/waste-table";

export default function WastePage() {
  return (
    <Suspense fallback={<p className="text-[14px] text-slate">Loading…</p>}>
      <WasteTable />
    </Suspense>
  );
}
