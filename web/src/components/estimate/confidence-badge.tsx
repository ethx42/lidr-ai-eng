import { Badge } from "@/components/ui/badge";
import type { Level } from "@/lib/estimate/read";

const CONFIDENCE: Record<Level, { label: string; className: string }> = {
  low: { label: "Low confidence", className: "bg-warning-subtle text-warning" },
  medium: { label: "Medium confidence", className: "bg-info-subtle text-info" },
  high: { label: "High confidence", className: "bg-success-subtle text-success" },
};

export const ConfidenceBadge = ({ level }: { level: Level }) => (
  <Badge variant="secondary" className={CONFIDENCE[level].className}>
    {CONFIDENCE[level].label}
  </Badge>
);
