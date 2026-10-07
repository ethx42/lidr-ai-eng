import { ArrowRightLeft, Check, Circle, CircleDot } from "lucide-react";
import { formatProvider } from "@/lib/estimate/format";
import { readCallStatus, readText } from "@/lib/estimate/read";
import type { StreamState } from "@/lib/estimate/types";
import { cn } from "@/lib/utils";

type Step = { label: string; state: "done" | "current" | "pending" };

const STEPS = ["Contacting the model", "Drafting the estimate", "Checking the estimate"];
const CACHED = ["Reusing an earlier estimate"];

const stepsAt = (labels: string[], current: number): Step[] =>
  labels.map((label, i) => ({ label, state: i < current ? "done" : i === current ? "current" : "pending" }));

const progress = (state: StreamState): { steps: Step[]; switchedTo?: string } | null => {
  switch (state.status) {
    case "streaming":
      if (state.phase === "cache_hit") return { steps: stepsAt(CACHED, 0) };
      return { steps: stepsAt(STEPS, state.phase === "validating" ? 2 : state.partial ? 1 : 0), switchedTo: readText(state.switchedTo) };
    case "done": {
      const { cacheHit, fallbackProvider } = readCallStatus(state.result);
      return { steps: stepsAt(cacheHit ? CACHED : STEPS, Infinity), switchedTo: fallbackProvider };
    }
    default:
      return null; // idle has no progress; error and cancelled are reported by the message that owns the stream
  }
};

const ICONS = { done: Check, current: CircleDot, pending: Circle };

export const StatusSteps = ({ state }: { state: StreamState }) => {
  const shown = progress(state);
  if (!shown) return null;
  const current = shown.steps.find((step) => step.state === "current");
  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-xs">
      <ol role="list" aria-label="Progress" className="flex flex-wrap items-center gap-x-4 gap-y-1">
        {shown.steps.map(({ label, state: step }) => {
          const Icon = ICONS[step];
          return (
            <li
              key={label}
              aria-current={step === "current" ? "step" : undefined}
              className={cn("flex items-center gap-1", step === "current" ? "font-medium text-foreground" : "text-muted-foreground")}
            >
              <Icon className={cn("size-3.5 shrink-0", step === "current" && "text-primary", step === "pending" && "opacity-60")} />
              {label}
              {step === "done" && <span className="sr-only">, done</span>}
            </li>
          );
        })}
      </ol>
      {/* Announces step changes and the fallback, never streamed content. */}
      <p role="status" aria-live="polite" className="flex items-center gap-1 text-info">
        {current && <span className="sr-only">{current.label}</span>}
        {shown.switchedTo && (
          <>
            <ArrowRightLeft className="size-3.5 shrink-0" />
            <span>{`Switched to ${formatProvider(shown.switchedTo)}`}</span>
          </>
        )}
      </p>
    </div>
  );
};
