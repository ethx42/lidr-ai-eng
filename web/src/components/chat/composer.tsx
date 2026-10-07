"use client";

import { type FormEvent, type RefObject, useEffect, useId, useMemo, useRef } from "react";
import { DEFAULT_MAX_CHARS, useServiceContext } from "@/components/service-context";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import type { Draft } from "@/hooks/use-draft";
import { useHydrated } from "@/hooks/use-hydrated";
import type { Sample } from "@/lib/samples";
import { countChars, formatChars, formatCount } from "@/lib/transcript";
import { cn } from "@/lib/utils";
import { SampleMenu, sampleDraft } from "./sample-picker";

type Props = {
  inputRef: RefObject<HTMLTextAreaElement | null>;
  draft: Draft;
  onSend: () => void;
  samples: Sample[];
};

const isApple = () => /Mac|iPhone|iPad/.test(navigator.userAgent);

export const Composer = ({ inputRef, draft, onSend, samples }: Props) => {
  const id = useId();
  const keepRef = useRef<HTMLButtonElement>(null);
  const { value, pending } = draft;
  const limit = useServiceContext()?.max_transcription_chars ?? DEFAULT_MAX_CHARS;
  const length = useMemo(() => countChars(value), [value]);
  const empty = length === 0;
  const over = length > limit;
  const apple = useHydrated() && isApple(); // the server cannot know the platform
  const [inputId, counterId, emptyId, overId, overById, noteId, confirmId] = ["input", "counter", "empty", "over", "over-by", "note", "confirm"].map(
    (part) => `${id}-${part}`,
  );

  // A pending replacement takes focus on its safe choice; either answer returns focus to the transcript.
  useEffect(() => {
    if (pending) keepRef.current?.focus();
  }, [pending]);
  const answer = (replace: boolean) => {
    if (replace) draft.confirm();
    else draft.cancel();
    inputRef.current?.focus();
  };

  const submit = (event?: FormEvent) => {
    event?.preventDefault();
    if (!empty && !over) onSend();
  };

  return (
    <form aria-label="New estimate" onSubmit={submit} className="shrink-0 border-t bg-background">
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-2 px-4 pt-3 pb-4 sm:px-6">
        {pending && (
          <div
            role="group"
            aria-labelledby={confirmId}
            onKeyDown={(event) => {
              if (event.key !== "Escape") return;
              event.preventDefault(); // handled here: the stream's Esc-to-stop listener skips it
              answer(false);
            }}
            className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-md border bg-surface px-3 py-2"
          >
            <p id={confirmId} className="text-sm">{`Replace your draft with ${pending.what}?`}</p>
            <div className="ml-auto flex gap-2">
              <Button type="button" variant="secondary" size="sm" onClick={() => answer(true)}>
                Replace draft
              </Button>
              <Button ref={keepRef} type="button" variant="ghost" size="sm" onClick={() => answer(false)}>
                Keep my draft
              </Button>
            </div>
          </div>
        )}
        <label htmlFor={inputId} className="sr-only">
          Meeting transcript
        </label>
        <Textarea
          id={inputId}
          ref={inputRef}
          value={value}
          onChange={(event) => draft.setValue(event.target.value)}
          onKeyDown={(event) => {
            if (event.key !== "Enter" || !(event.metaKey || event.ctrlKey)) return;
            if (event.nativeEvent.isComposing || event.keyCode === 229) return; // IME composition (Safari reports it only via 229)
            event.preventDefault(); // Cmd/Ctrl+Enter sends; a plain Enter keeps inserting a newline
            submit();
          }}
          placeholder="Paste a meeting transcript"
          aria-invalid={over || undefined}
          aria-describedby={[counterId, over && overId, over && overById, noteId].filter(Boolean).join(" ")}
          className="max-h-40 min-h-20 resize-none bg-card sm:max-h-64"
        />
        <div className="flex items-center gap-3">
          <SampleMenu
            samples={samples}
            onPick={(sample) => draft.replace(sampleDraft(sample))}
            onPicked={() => (pending ? keepRef : inputRef).current?.focus()}
          />
          <span id={counterId} className={cn("num ml-auto text-xs", over ? "text-destructive" : length > limit * 0.9 ? "text-warning" : "text-muted-foreground")}>
            {`${formatCount(length)} / ${formatCount(limit)} `}
            <span className="sr-only">characters</span>
          </span>
          <Button
            type="submit"
            disabled={empty || over}
            aria-describedby={empty ? emptyId : over ? `${overId} ${overById}` : undefined}
            aria-keyshortcuts={apple ? "Meta+Enter" : "Control+Enter"}
          >
            Estimate
            {/* opacity-80 keeps 4.5:1 on the light primary (70 gave 4.1:1, flagged by axe in the e2e run) */}
            <kbd aria-hidden className="hidden font-sans text-xs opacity-80 sm:inline">
              {apple ? "⌘↵" : "Ctrl ↵"}
            </kbd>
          </Button>
        </div>
        {empty && (
          <p id={emptyId} className="text-xs text-muted-foreground">
            Paste or type a transcript to estimate.
          </p>
        )}
        {/* The status is always mounted and its text only changes when the limit is crossed, so it is announced
            once; the running count sits outside it. */}
        <p className={cn("text-xs text-destructive", !over && "sr-only")}>
          <span id={overId} role="status">
            {over ? "Shorten the transcript to send it." : ""}
          </span>{" "}
          {over && <span id={overById}>{`It is ${formatChars(length - limit)} over the limit.`}</span>}
        </p>
        <p id={noteId} className="text-xs text-muted-foreground">
          Each message is estimated on its own. Conversation memory arrives in a later version.
        </p>
      </div>
    </form>
  );
};
