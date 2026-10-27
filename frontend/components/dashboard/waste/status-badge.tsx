import { Badge } from "@/components/ui/badge";
import { WASTE_STATUS_LABELS,type WasteStatus } from "@/types/waste";

const TONE: Record<WasteStatus, "default" | "emerald" | "amber" | "rust"> = {
  reported: "default",
  classified: "default",
  risk_assessed: "amber",
  segregated: "default",
  pickup_requested: "amber",
  pickup_assigned: "amber",
  collected: "default",
  in_transit: "default",
  destination_received: "default",
  processing: "default",
  recycled: "emerald",
  treated: "emerald",
  disposed: "emerald",
  verified: "emerald",
  completed: "emerald",
};

export function WasteStatusBadge({ status }: { status: WasteStatus }) {
  return <Badge variant={TONE[status]}>{WASTE_STATUS_LABELS[status]}</Badge>;
}
