import { formatHours } from "@/lib/estimate/format";

type Props = { optimistic: number; likely: number; pessimistic: number; max: number };

const percent = (hours: number, max: number) => `${max > 0 ? Math.min(100, Math.max(0, (hours / max) * 100)) : 0}%`;

// Optimistic to pessimistic as a band and the likely value as a tick, on a scale shared by every row (`max`).
export const RangeBar = ({ optimistic, likely, pessimistic, max }: Props) => {
  const [lo, hi] = [Math.min(optimistic, pessimistic), Math.max(optimistic, pessimistic)];
  return (
    <div
      role="img"
      aria-label={`Optimistic ${formatHours(optimistic)}, likely ${formatHours(likely)}, pessimistic ${formatHours(pessimistic)}`}
      className="relative h-2 w-full rounded-full bg-muted"
    >
      <div className="absolute inset-y-0 rounded-full bg-chart-3" style={{ left: percent(lo, max), width: percent(hi - lo, max) }} />
      <div className="absolute -inset-y-0.5 w-0.5 -translate-x-1/2 rounded-full bg-primary" style={{ left: percent(likely, max) }} />
    </div>
  );
};
