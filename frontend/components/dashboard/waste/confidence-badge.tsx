import { Badge } from "@/components/ui/badge";
import type { ClassificationConfidence } from "@/types/waste";

const LABELS: Record<ClassificationConfidence, string> = {
  high: "High confidence",
  medium: "Medium confidence",
  low: "Low confidence",
};

const TONE: Record<ClassificationConfidence, "emerald" | "amber" | "rust"> = {
  high: "emerald",
  medium: "amber",
  low: "rust",
};

export function ConfidenceBadge({ confidence }: { confidence: ClassificationConfidence }) {
  return <Badge variant={TONE[confidence]}>{LABELS[confidence]}</Badge>;
}
