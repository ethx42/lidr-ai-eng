import { Badge } from "@/components/ui/badge";
import type { components } from "@/lib/ai-service/schema";
import { formatHours, formatUsd } from "@/lib/estimate/format";

type Totals = components["schemas"]["Totals"];
// What the comparison reads; a full `Totals` fits.
export type Sums = Pick<Totals, "expected_hours"> & Partial<Pick<Totals, "estimated_cost">>;
export type TotalsDelta = { expectedHours: number; costUsd?: number };

// Hours carry one decimal (PERT halves) and costs whole dollars; rounding drops float noise such as 0.30000000000000004.
const round = (value: number, digits: number) => Math.round(value * 10 ** digits) / 10 ** digits;
const isCost = (value: number | null | undefined): value is number => typeof value === "number";

// How this turn's totals moved from the previous completed turn's; null on the first one.
export const computeTotalsDelta = (prev: Sums | null, next: Sums): TotalsDelta | null => {
  if (!prev) return null;
  const expectedHours = round(next.expected_hours - prev.expected_hours, 1);
  return isCost(prev.estimated_cost) && isCost(next.estimated_cost) ? { expectedHours, costUsd: round(next.estimated_cost - prev.estimated_cost, 0) } : { expectedHours };
};

const signed = (value: number, format: (value: number) => string) => `${value < 0 ? "−" : "+"}${format(Math.abs(value))}`;

export const describeDelta = ({ expectedHours, costUsd }: TotalsDelta) =>
  expectedHours === 0
    ? "No change in hours vs previous turn"
    : `${[signed(expectedHours, formatHours), costUsd !== undefined && signed(costUsd, formatUsd)].filter(Boolean).join(", ")} vs previous turn`;

// "+30 h vs previous turn": what changed, at a glance, on the turn that changed it.
export const TotalsDeltaBadge = ({ delta }: { delta: TotalsDelta }) => (
  <Badge variant="outline" className="num text-muted-foreground">
    {describeDelta(delta)}
  </Badge>
);
