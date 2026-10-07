"use client";

import { type Ref, useEffect, useRef } from "react";
import type { Turn } from "@/hooks/use-thread";
import type { Sample } from "@/lib/samples";
import { AssistantMessage } from "./assistant-message";
import { SampleCards } from "./sample-picker";
import { UserMessage } from "./user-message";

type Props = {
  turns: Turn[];
  samples: Sample[];
  noteId: string; // the composer's transcript field is described by the note too
  onPickSample: (sample: Sample) => void;
  onStop: () => void;
  onRegenerate: (turnId: string) => void;
  onEditTranscript: (transcription: string) => void;
  stopRef?: Ref<HTMLButtonElement>; // given to the last turn's Stop
};

// Shown once, in the empty state or above the thread (it used to sit in the composer, on every screen's fixed chrome).
const MemoryNote = ({ id }: { id: string }) => (
  <p id={id} className="text-xs text-muted-foreground">
    Each transcript is estimated on its own. Conversation memory arrives in a later version.
  </p>
);

const EmptyState = ({ samples, onPickSample, noteId }: Pick<Props, "samples" | "onPickSample" | "noteId">) => (
  <div className="flex flex-col gap-8 py-6 sm:py-16">
    <h2 className="max-w-2xl text-base font-semibold text-balance sm:text-xl">
      Paste a meeting transcript to get tasks with hour ranges, the quotes behind each requirement and the questions to ask the client.
    </h2>
    <div className="flex flex-col gap-3">
      <p className="text-sm text-muted-foreground">No transcript at hand? Start from a sample.</p>
      <SampleCards samples={samples} onPick={onPickSample} />
    </div>
    <MemoryNote id={noteId} />
  </div>
);

export const Thread = ({ turns, samples, noteId, onPickSample, onStop, onRegenerate, onEditTranscript, stopRef }: Props) => {
  const lastId = turns.at(-1)?.id;
  const lastRef = useRef<HTMLLIElement>(null);

  // A new turn (or a restored thread) starts in view; the estimate then fills in below it without auto-scrolling.
  useEffect(() => {
    lastRef.current?.scrollIntoView({ block: "start" });
  }, [lastId]);

  if (turns.length === 0) return <EmptyState samples={samples} onPickSample={onPickSample} noteId={noteId} />;
  return (
    <>
      <MemoryNote id={noteId} />
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
              stopRef={turn.id === lastId ? stopRef : undefined}
            />
          </li>
        ))}
      </ol>
    </>
  );
};
