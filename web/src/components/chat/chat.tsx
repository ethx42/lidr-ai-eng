"use client";

import { useId, useRef } from "react";
import { AppHeader } from "@/components/app-header";
import { InspectorPanel, InspectorSheet } from "@/components/inspector/inspector";
import { Skeleton } from "@/components/ui/skeleton";
import { type Replacement, useDraft } from "@/hooks/use-draft";
import { useHydrated } from "@/hooks/use-hydrated";
import { useThread } from "@/hooks/use-thread";
import { focusForTyping } from "@/lib/focus";
import type { Sample } from "@/lib/samples";
import { Composer } from "./composer";
import { sampleDraft } from "./sample-picker";
import { Thread } from "./thread";

// Stands in for the thread until hydration; shaped like the empty state, which is what most loads show.
const ThreadSkeleton = () => (
  <div aria-hidden className="flex flex-col gap-8 py-6 sm:py-16">
    <div className="flex max-w-2xl flex-col gap-2">
      <Skeleton className="h-6 w-full" />
      <Skeleton className="h-6 w-2/3" />
    </div>
    <div className="grid gap-3 sm:grid-cols-3">
      {[0, 1, 2].map((i) => (
        <Skeleton key={i} className="h-20" />
      ))}
    </div>
  </div>
);

export const Chat = ({ samples }: { samples: Sample[] }) => {
  const { turns, lastCall, send, stop, regenerate } = useThread();
  const draft = useDraft();
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const inspectorRef = useRef<HTMLElement>(null);
  const noteId = useId();
  // The thread comes from sessionStorage, which the server render cannot see: show it once hydrated.
  const hydrated = useHydrated();
  const call = hydrated ? lastCall : undefined;

  // When the draft must be confirmed first, the composer moves focus to that question instead.
  const fillComposer = (next: Replacement) => {
    if (draft.replace(next)) focusForTyping(inputRef.current);
  };
  const submit = () => {
    send(draft.value);
    draft.clear();
    focusForTyping(inputRef.current); // keeps Esc (stop) and the next transcript one keystroke away
  };

  return (
    // Below 480 px tall (`short`) nothing is fixed: the whole page scrolls, so the thread never shrinks to nothing.
    <div className="flex h-dvh min-h-0 flex-col short:h-auto short:min-h-dvh">
      <AppHeader actions={<InspectorSheet call={call} panelRef={inspectorRef} />} />
      <div className="flex min-h-0 flex-1">
        <div className="flex min-w-0 flex-1 flex-col">
          {/* `relative` contains the sr-only (absolute) descendants, so only this region scrolls, never the page (except when short). */}
          <main aria-busy={!hydrated} className="relative min-h-0 flex-1 overflow-y-auto short:overflow-visible">
            <div className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-6">
              {hydrated ? (
                <Thread
                  turns={turns}
                  samples={samples}
                  noteId={noteId}
                  onPickSample={(sample) => fillComposer(sampleDraft(sample))}
                  onStop={stop}
                  onRegenerate={regenerate}
                  onEditTranscript={(text) => fillComposer({ text, what: "the transcript to shorten" })}
                />
              ) : (
                <ThreadSkeleton />
              )}
            </div>
          </main>
          <Composer inputRef={inputRef} draft={draft} onSend={submit} samples={samples} noteId={noteId} />
        </div>
        <InspectorPanel ref={inspectorRef} call={call} />
      </div>
    </div>
  );
};
