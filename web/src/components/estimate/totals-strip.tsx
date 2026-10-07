import { formatHours, formatRange, formatUsd } from "@/lib/estimate/format";
import type { EstimateModel } from "@/lib/estimate/read";
import { Pending } from "./estimate-skeleton";

type Item = { label: string; value?: string; detail?: string };

// Totals are computed server-side, so every value stays a skeleton until the final result carries them.
export const TotalsStrip = ({ totals = {} }: { totals?: EstimateModel["totals"] }) => {
  const { expected_hours: expected, optimistic_hours: lo, pessimistic_hours: hi, duration_weeks_min: weeksMin, duration_weeks_max: weeksMax } = totals;
  const { team_size: teamSize, hourly_rate: rate, estimated_cost: cost } = totals;
  const items: Item[] = [
    { label: "Expected", value: expected !== undefined ? formatHours(expected) : undefined },
    { label: "Range", value: lo !== undefined && hi !== undefined ? formatRange(lo, hi) : undefined },
    {
      label: "Duration",
      value: weeksMin !== undefined && weeksMax !== undefined ? formatRange(weeksMin, weeksMax, "weeks") : undefined,
      detail: typeof teamSize === "number" ? `Team of ${teamSize}` : undefined,
    },
    ...(typeof cost === "number" ? [{ label: "Cost", value: formatUsd(cost), detail: typeof rate === "number" ? `At ${formatUsd(rate)}/h` : undefined }] : []),
  ];
  return (
    <dl className="grid grid-cols-2 gap-x-6 gap-y-3 rounded-md border bg-card px-4 py-3 sm:auto-cols-fr sm:grid-flow-col sm:grid-cols-none">
      {items.map(({ label, value, detail }) => (
        <div key={label} className="flex min-w-0 flex-col">
          <dt className="text-xs text-muted-foreground">{label}</dt>
          <dd className="num text-xl font-semibold">{value ?? <Pending className="my-1 h-5 w-20" />}</dd>
          {detail && <dd className="text-xs text-muted-foreground">{detail}</dd>}
        </div>
      ))}
    </dl>
  );
};
