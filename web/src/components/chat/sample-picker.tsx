"use client";

import { ChevronDown, FileText } from "lucide-react";
import { type Ref, useRef } from "react";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import type { Replacement } from "@/hooks/use-draft";
import type { Sample } from "@/lib/samples";

type Props = { samples: Sample[]; onPick: (sample: Sample) => void };

export const sampleDraft = (sample: Sample): Replacement => ({ text: sample.text, what: `the “${sample.title}” sample` });

// Picking a sample only fills the transcript; the user still reviews it and runs the estimate.
// `onPicked` returns whether it moved focus; when it did not, focus returns to the trigger.
export const SampleMenu = ({ samples, onPick, onPicked, triggerRef }: Props & { onPicked: () => boolean; triggerRef?: Ref<HTMLButtonElement> }) => {
  const picked = useRef(false);
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button ref={triggerRef} type="button" variant="ghost" size="sm">
          <FileText />
          Load sample
          <ChevronDown />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="end"
        className="w-72"
        onCloseAutoFocus={(event) => {
          if (!picked.current) return; // dismissed: focus returns to the trigger
          picked.current = false;
          if (onPicked()) event.preventDefault();
        }}
      >
        {samples.map((sample) => (
          <DropdownMenuItem
            key={sample.id}
            className="flex-col items-start gap-0.5 py-1.5"
            onSelect={() => {
              picked.current = true;
              onPick(sample);
            }}
          >
            <span className="font-medium">{sample.title}</span>
            <span className="text-xs text-muted-foreground">{sample.description}</span>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
};
