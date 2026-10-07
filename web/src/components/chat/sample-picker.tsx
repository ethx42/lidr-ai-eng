"use client";

import { ChevronDown, FileText } from "lucide-react";
import { useId, useRef } from "react";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import type { Replacement } from "@/hooks/use-draft";
import type { Sample } from "@/lib/samples";

type Props = { samples: Sample[]; onPick: (sample: Sample) => void };

export const sampleDraft = (sample: Sample): Replacement => ({ text: sample.text, what: `the “${sample.title}” sample` });

// Picking a sample only fills the composer; the user still reviews and sends it.
// `onPicked` returns whether it moved focus; when it did not, focus returns to the trigger.
export const SampleMenu = ({ samples, onPick, onPicked }: Props & { onPicked: () => boolean }) => {
  const picked = useRef(false);
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button type="button" variant="ghost" size="sm">
          <FileText />
          Samples
          <ChevronDown />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        side="top"
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

const SampleCard = ({ sample, onPick }: { sample: Sample; onPick: Props["onPick"] }) => {
  const descriptionId = useId();
  return (
    <button
      type="button"
      aria-describedby={descriptionId}
      onClick={() => onPick(sample)}
      className="flex h-full w-full flex-col items-start gap-1 rounded-md border bg-card px-4 py-3 text-left transition-colors hover:border-border-strong hover:bg-surface"
    >
      <span className="text-sm font-medium">{sample.title}</span>
      {/* its own description, not part of the name: the card is named by its title */}
      <span id={descriptionId} aria-hidden className="text-xs text-muted-foreground">
        {sample.description}
      </span>
    </button>
  );
};

export const SampleCards = ({ samples, onPick }: Props) => (
  <ul role="list" aria-label="Sample transcripts" className="grid gap-3 sm:grid-cols-3">
    {samples.map((sample) => (
      <li key={sample.id}>
        <SampleCard sample={sample} onPick={onPick} />
      </li>
    ))}
  </ul>
);
