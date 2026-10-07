"use client";

import { useId, useState } from "react";
import { Button } from "@/components/ui/button";
import { countChars, formatChars } from "@/lib/transcript";
import { cn } from "@/lib/utils";

// Roughly more than the three clamped lines at the column width.
const isLong = (text: string) => text.length > 280 || text.split("\n").length > 3;

export const UserMessage = ({ transcription }: { transcription: string }) => {
  const [expanded, setExpanded] = useState(false);
  const bodyId = useId();
  return (
    <div className="flex min-w-0 flex-col gap-2">
      <div className="flex items-center gap-3 text-xs">
        <p className="font-medium">Your transcript</p>
        <p className="num text-muted-foreground">{formatChars(countChars(transcription))}</p>
        {isLong(transcription) && (
          <Button type="button" variant="link" size="xs" className="ml-auto px-0" aria-expanded={expanded} aria-controls={bodyId} onClick={() => setExpanded(!expanded)}>
            {expanded ? "Show less" : "Show all"}
          </Button>
        )}
      </div>
      <p id={bodyId} className={cn("border-l-2 border-border-strong pl-3 text-sm whitespace-pre-wrap text-muted-foreground wrap-anywhere", !expanded && "line-clamp-3")}>
        {transcription}
      </p>
    </div>
  );
};
