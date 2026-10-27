import { Badge } from "@/components/ui/badge";
import { RISK_LEVEL_LABELS,type RiskLevel } from "@/types/waste";

const TONE: Record<RiskLevel, "emerald" | "amber" | "rust"> = {
  low: "emerald",
  medium: "amber",
  high: "rust",
  critical: "rust",
};

export function RiskLevelBadge({ level }: { level: RiskLevel }) {
  return <Badge variant={TONE[level]}>{RISK_LEVEL_LABELS[level]} risk</Badge>;
}
