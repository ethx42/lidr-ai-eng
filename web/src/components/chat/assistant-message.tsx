"use client";

import { CircleStop, Copy, ListChecks, RotateCcw, Square } from "lucide-react";
import { type Ref, useEffect, useEffectEvent, useRef } from "react";
import { EstimateView } from "@/components/estimate/estimate-view";
import { StatusSteps } from "@/components/estimate/status-steps";
import { Button } from "@/components/ui/button";
import { EstimateDocument, type ResultView } from "@/components/workspace/result-view-toggle";
import { copyText } from "@/lib/copy";
import { readEstimate, readText } from "@/lib/estimate/read";
import type { StreamState } from "@/lib/estimate/types";
import { AiDisclosure } from "./ai-disclosure";
import { ErrorCard } from "./error-card";

type Done = Extract<StreamState, { status: "done" }>;
type Props = {
  state: StreamState;
  onStop: () => void;
  // A conversation turn (S5-R3): a completed one never runs again (that would fork the history); a stopped or failed
  // one does, as "Retry", while it is the latest turn (absent otherwise).
  onRetry?: () => void;
  onEditTranscript: () => void;
  stopRef?: Ref<HTMLButtonElement>;
  view?: ResultView; // "document" shows a completed estimate as the server's markdown
  activeRequirement?: string;
  onRequirementFocus?: (id: string | null) => void;
  pinFor?: (id: string) => (() => void) | undefined;
  evidenceNote?: (id: string) => string | undefined; // where a quote comes from, when not from the transcript shown
};

// Plain text, so the questions paste cleanly into an email to the client.
const numbered = (items: string[]) => items.map((item, i) => `${i + 1}. ${item}`).join("\n");

const DoneActions = ({ state }: { state: Done }) => {
  const markdown = readText(state.result.estimation);
  const questions = readEstimate(state.result.breakdown).open_questions ?? [];
  return (
    <>
      {markdown && (
        <Button type="button" variant="outline" size="sm" onClick={() => void copyText(markdown, "Estimate copied as markdown")}>
          <Copy />
          Copy as markdown
        </Button>
      )}
      {questions.length > 0 && (
        <Button type="button" variant="ghost" size="sm" onClick={() => void copyText(numbered(questions), "Questions for the client copied")}>
          <ListChecks />
          Copy questions{" "}
          <span className="sr-only sm:not-sr-only">for the client</span>
        </Button>
      )}
    </>
  );
};

const isComposing = (event: KeyboardEvent) => event.isComposing || event.keyCode === 229; // Safari reports it only via 229

export const AssistantMessage = ({
  state,
  onStop,
  onRetry,
  onEditTranscript,
  stopRef,
  view = "structured",
  activeRequirement,
  onRequirementFocus,
  pinFor,
  evidenceNote,
}: Props) => {
  const rootRef = useRef<HTMLDivElement>(null);
  const previous = useRef(state.status);
  const focusWithin = useRef(false); // focus was last inside this message, or one of its actions was used
  const streaming = state.status === "streaming";
  const stop = useEffectEvent(onStop);
  const own = (action: () => void) => () => {
    focusWithin.current = true; // Safari does not focus a clicked button
    action();
  };

  useEffect(() => {
    if (!streaming) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented || isComposing(event)) return; // open layers handle Escape first
      stop();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [streaming]);

  // The focused control can disappear with a status change (Stop when the stream ends, Retry when it starts).
  // If focus was in this message and fell to the page, it moves to this message's first action, without scrolling.
  useEffect(() => {
    if (previous.current === state.status) return;
    previous.current = state.status;
    const lost = !document.activeElement || document.activeElement === document.body;
    if (lost && focusWithin.current) rootRef.current?.querySelector("button")?.focus({ preventScroll: true });
  }, [state.status]);

  const content =
    state.status === "done" ? state.result.breakdown : state.status === "idle" ? null : (state.partial ?? (streaming ? {} : null));

  return (
    <div
      ref={rootRef}
      // relatedTarget is null when focus falls to the page (a removed button, a click on blank space): that keeps the flag
      onFocus={() => (focusWithin.current = true)}
      onBlur={(event) => {
        if (event.relatedTarget) focusWithin.current = event.relatedTarget instanceof Node && event.currentTarget.contains(event.relatedTarget);
      }}
      className="flex min-w-0 flex-col gap-6"
    >
      {state.status === "error" && <ErrorCard error={state.error} onRetry={onRetry && own(onRetry)} onEditTranscript={onEditTranscript} />}
      {state.status !== "error" && (
        <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2">
          <div className="flex min-w-0 items-center">
            <StatusSteps state={state} />
            {/* Rendered from the stream's start, so "Stopped" is announced when it appears. */}
            <p role="status" className="flex items-center gap-1.5 text-xs font-medium empty:sr-only">
              {state.status === "cancelled" && (
                <>
                  <CircleStop className="size-3.5 text-muted-foreground" />
                  Stopped
                </>
              )}
            </p>
          </div>
          <div className="ml-auto flex flex-wrap items-center gap-2">
            {state.status === "streaming" && (
              <Button ref={stopRef} type="button" variant="outline" size="sm" onClick={own(onStop)} aria-keyshortcuts="Escape">
                <Square />
                Stop
                <kbd aria-hidden className="hidden font-sans text-xs text-muted-foreground sm:inline">
                  Esc
                </kbd>
              </Button>
            )}
            {state.status === "done" && <DoneActions state={state} />}
            {state.status === "cancelled" && onRetry && (
              <Button type="button" variant="ghost" size="sm" onClick={own(onRetry)}>
                <RotateCcw />
                Retry
              </Button>
            )}
          </div>
        </div>
      )}
      {content && (
        <>
          {view === "document" && state.status === "done" ? (
            <EstimateDocument markdown={readText(state.result.estimation) ?? ""} />
          ) : (
            <EstimateView
              data={content}
              grounding={state.status === "done" ? state.result.grounding : undefined}
              streaming={streaming}
              completed={state.status === "done"}
              activeRequirement={activeRequirement}
              onRequirementFocus={onRequirementFocus}
              pinFor={pinFor}
              evidenceNote={evidenceNote}
            />
          )}
          <AiDisclosure />
        </>
      )}
    </div>
  );
};
