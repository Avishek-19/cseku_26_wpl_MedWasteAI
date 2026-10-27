import { Badge } from "@/components/ui/badge";
import {
PICKUP_PRIORITY_LABELS,
PICKUP_STATUS_LABELS,
type PickupPriority,
type PickupStatus,
} from "@/types/waste";

const STATUS_TONE: Record<PickupStatus, "default" | "emerald" | "amber" | "rust"> = {
  requested: "amber",
  assigned: "default",
  collected: "emerald",
  in_transit: "emerald",
  cancelled: "rust",
};

const PRIORITY_TONE: Record<PickupPriority, "default" | "amber" | "rust"> = {
  normal: "default",
  urgent: "amber",
  emergency: "rust",
};

export function PickupStatusBadge({ status }: { status: PickupStatus }) {
  return <Badge variant={STATUS_TONE[status]}>{PICKUP_STATUS_LABELS[status]}</Badge>;
}

export function PickupPriorityBadge({ priority }: { priority: PickupPriority }) {
  return <Badge variant={PRIORITY_TONE[priority]}>{PICKUP_PRIORITY_LABELS[priority]}</Badge>;
}
