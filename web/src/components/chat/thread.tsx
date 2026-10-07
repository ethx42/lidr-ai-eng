"use client";

import { useEffect, useRef } from "react";
import type { Turn } from "@/hooks/use-thread";
import type { Sample } from "@/lib/samples";
import { AssistantMessage } from "./assistant-message";
import { SampleCards } from "./sample-picker";
import { UserMessage } from "./user-message";

type Props = {
  turns: Turn[];
  samples: Sample[];
  onPickSample: (sample: Sample) => void;
  onStop: () => void;
  onRegenerate: (turnId: string) => void;
  onEditTranscript: (transcription: string) => void;
};

const EmptyState = ({ samples, onPickSample }: Pick<Props, "samples" | "onPickSample">) => (
  <div className="flex flex-col gap-8 py-6 sm:py-16">
    <h2 className="max-w-2xl text-base font-semibold text-balance sm:text-xl">
      Paste a meeting transcript to get tasks with hour ranges, the quotes behind each requirement and the questions to ask the client.
    </h2>
    <div className="flex flex-col gap-3">
      <p className="text-sm text-muted-foreground">No transcript at hand? Start from a sample.</p>
      <SampleCards samples={samples} onPick={onPickSample} />
    </div>
  </div>
);

export const Thread = ({ turns, samples, onPickSample, onStop, onRegenerate, onEditTranscript }: Props) => {
  const lastId = turns.at(-1)?.id;
  const lastRef = useRef<HTMLLIElement>(null);

  // A new turn (or a restored thread) starts in view; the estimate then fills in below it without auto-scrolling.
  useEffect(() => {
    lastRef.current?.scrollIntoView({ block: "start" });
  }, [lastId]);

  if (turns.length === 0) return <EmptyState samples={samples} onPickSample={onPickSample} />;
  return (
    <ol role="list" aria-label="Estimates" className="flex flex-col divide-y">
      {turns.map((turn) => (
        <li key={turn.id} ref={turn.id === lastId ? lastRef : undefined} className="flex scroll-mt-6 flex-col gap-6 py-10 first:pt-2">
          <UserMessage transcription={turn.transcription} />
          <AssistantMessage
            state={turn.state}
            kept={turn.kept}
            onStop={onStop}
            onRegenerate={() => onRegenerate(turn.id)}
            onEditTranscript={() => onEditTranscript(turn.transcription)}
          />
        </li>
      ))}
    </ol>
  );
};
