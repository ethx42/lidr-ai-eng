"use client";

import { Info } from "lucide-react";
import { useId, useState } from "react";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

const EXPLANATION = "Older turns are dropped first. Project memory is kept separately and always sent.";

// How much of the conversation the next turn sends: the history window in turns (user + assistant pairs). The tooltip
// opens on hover and focus, and on a tap (Radix ignores touch); screen readers get the same text as the meter's
// description.
export const ContextMeter = ({ turns, max }: { turns?: number; max?: number }) => {
  const [open, setOpen] = useState(false);
  const labelId = useId();
  const descriptionId = useId();
  if (turns === undefined || max === undefined) return <Skeleton className="h-9 w-full" />;
  const share = max > 0 ? Math.min(turns / max, 1) : 0;
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-1">
        <p id={labelId} className="num text-xs font-medium">
          <span className="sr-only">History</span>
          <span aria-hidden>{`History ${turns} / ${max} turns`}</span>
        </p>
        <Tooltip open={open} onOpenChange={setOpen}>
          <TooltipTrigger asChild>
            <button
              type="button"
              aria-label="About the history window"
              onClick={(event) => {
                event.preventDefault(); // Radix closes on click; a tap opens it instead
                setOpen(true);
              }}
              className="inline-flex size-6 items-center justify-center rounded-sm text-muted-foreground hover:bg-muted hover:text-foreground"
            >
              <Info className="size-3.5" />
            </button>
          </TooltipTrigger>
          <TooltipContent side="bottom" className="max-w-64">
            {EXPLANATION}
          </TooltipContent>
        </Tooltip>
      </div>
      <div
        role="meter"
        aria-labelledby={labelId}
        aria-describedby={descriptionId}
        aria-valuemin={0}
        aria-valuemax={max}
        aria-valuenow={turns}
        aria-valuetext={`${turns} of ${max} turns`}
        className="h-1.5 overflow-hidden rounded-full bg-muted"
      >
        <div className="h-full rounded-full bg-primary transition-[width]" style={{ width: `${share * 100}%` }} />
      </div>
      <span id={descriptionId} className="sr-only">
        {EXPLANATION}
      </span>
    </div>
  );
};
