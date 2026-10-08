"use client";

import { ChevronRight, FileText } from "lucide-react";
import { type Ref, useId, useMemo, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { AssistantMessage } from "@/components/chat/assistant-message";
import { DETAIL_LEVEL_LABELS, OUTPUT_FORMAT_LABELS, PROJECT_TYPE_LABELS } from "@/components/form/estimate-form-schema";
import { Button } from "@/components/ui/button";
import { type ResultView, ResultViewToggle } from "@/components/workspace/result-view-toggle";
import { type Pin, TranscriptPane } from "@/components/workspace/transcript-pane";
import { useMediaQuery } from "@/hooks/use-media-query";
import type { components } from "@/lib/ai-service/schema";
import { readEstimate, readGrounding } from "@/lib/estimate/read";
import type { StreamState } from "@/lib/estimate/types";
import { type EvidenceQuote, evidenceFinder } from "@/lib/evidence";
import { formatBytes } from "@/lib/session/attachments";
import { countChars, formatChars } from "@/lib/transcript";
import { cn } from "@/lib/utils";
import { type TotalsDelta, TotalsDeltaBadge } from "./totals-delta";

// What one turn sent: the typed request and its attachments. A Retry sends the same again.
export type TurnInput = { body: components["schemas"]["EstimateRequest"]; files: File[] };

// Tailwind's `md`: from here hover and focus link a requirement to its quote; below it, Evidence pins the requirement.
export const WIDE = "(min-width: 48rem)";

// The quotes to mark: each complete quote while the estimate streams, then only those the server grounded. Evidence is
// a requirement's last field, so a snapshot can end inside the newest requirement's quote, and a cut-short quote marks
// wherever its first letters appear; that requirement waits until a later field (assumptions) starts or the result arrives.
export const quotesOf = (shown: StreamState): EvidenceQuote[] => {
  if (shown.status === "idle") return [];
  const done = shown.status === "done";
  const { requirements = [], assumptions } = readEstimate(done ? shown.result.breakdown : shown.partial);
  const { ungrounded } = readGrounding(done ? shown.result.grounding : undefined);
  const complete = done || assumptions ? requirements : requirements.slice(0, -1);
  return complete.flatMap(({ id, evidence }) => (id && evidence && !ungrounded.has(id) ? [{ id, evidence }] : []));
};

// The choices a turn was sent with, in words ("Web SaaS, medium detail, phases table").
const describe = ({ project_type, detail_level, output_format }: TurnInput["body"]) =>
  [PROJECT_TYPE_LABELS[project_type], `${DETAIL_LEVEL_LABELS[detail_level].toLowerCase()} detail`, OUTPUT_FORMAT_LABELS[output_format].toLowerCase()].join(", ");

type Props = {
  number: number;
  input: TurnInput;
  state: StreamState;
  attempt: number; // a Retry starts the next attempt at this turn
  delta: TotalsDelta | null; // the totals' change from the previous completed turn
  onStop: () => void;
  onRetry?: () => void; // only while this is the latest turn, stopped or failed (S5-R3)
  onEdit: () => void; // puts this turn back in the composer
  stopRef?: Ref<HTMLButtonElement>;
  ref?: Ref<HTMLLIElement>;
};

// One turn of the conversation: what was sent (choices, attachment chips, the transcript behind a disclosure) and the
// answer. Session 4's evidence link survives inside the card: hovering or focusing a requirement highlights its quote in
// this turn's transcript; below 768 px, Evidence opens the transcript at the quote and pins it. A grounded quote with no
// mark here came from an earlier message (grounding covers the conversation the model saw) or an attachment: its
// Evidence card says so instead.
export const TurnCard = ({ number, input, state, attempt, delta, onStop, onRetry, onEdit, stopRef, ref }: Props) => {
  const labelId = useId();
  const transcriptId = useId();
  const transcriptRef = useRef<HTMLDivElement>(null);
  const wide = useMediaQuery(WIDE, true);
  const [view, setView] = useState<ResultView>("structured");
  const [open, setOpen] = useState(false);
  // Hovered or focused; `pinned` (below 768 px) outlives both, until the next pin or attempt.
  const [activeRequirement, setActiveRequirement] = useState<string | null>(null);
  const [pinned, setPinned] = useState<Pin | null>(null);
  // A new attempt streams in structured and numbers its own requirements (React's "adjusting state when a prop changes").
  const [shownAttempt, setShownAttempt] = useState(attempt);
  if (shownAttempt !== attempt) {
    setShownAttempt(attempt);
    setView("structured");
    setActiveRequirement(null);
    setPinned(null);
  }
  const transcript = input.body.transcription;
  const quotes = useMemo(() => quotesOf(state), [state]);
  const find = useMemo(() => evidenceFinder(transcript), [transcript]);
  // Only a requirement whose quote is marked here can be pinned; any other keeps its hover card.
  const marked = useMemo(() => new Set(find(quotes).map(({ id }) => id)), [find, quotes]);
  const shownPin = wide ? null : pinned;
  const elsewhere = input.files.length > 0 ? "Quote from an attachment or an earlier message" : "Quote from an earlier message";
  const evidenceNote = state.status === "done" ? (id: string) => (marked.has(id) ? undefined : elsewhere) : undefined;

  // Focus moves into the transcript, which the scroll to the quote may have moved the Evidence button away from.
  const pin = (id: string) => {
    flushSync(() => {
      setOpen(true);
      setPinned({ id });
    });
    transcriptRef.current?.focus({ preventScroll: true });
  };

  return (
    <li ref={ref} aria-labelledby={labelId} className="scroll-mt-16 rounded-lg border bg-card">
      <div className="flex flex-col gap-2 rounded-t-lg border-b bg-surface px-4 py-3 sm:px-6">
        <p className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <span id={labelId} className="text-sm font-semibold">{`Turn ${number}`}</span>
          <span className="text-xs text-muted-foreground">{describe(input.body)}</span>
        </p>
        {input.files.length > 0 && (
          <ul role="list" aria-label="Attachments" className="flex flex-wrap gap-2">
            {input.files.map((file, i) => (
              <li key={i} className="flex h-6 max-w-full items-center gap-1.5 rounded-md border bg-card px-2 text-xs">
                <FileText aria-hidden className="size-3.5 shrink-0 text-muted-foreground" />
                <span title={file.name} className="min-w-0 truncate">
                  {file.name}
                </span>
                <span className="num shrink-0 text-muted-foreground">{formatBytes(file.size)}</span>
              </li>
            ))}
          </ul>
        )}
        <div>
          <Button type="button" variant="ghost" size="sm" aria-expanded={open} aria-controls={transcriptId} onClick={() => setOpen(!open)} className="-ml-2.5">
            <ChevronRight className={cn("transition-transform", open && "rotate-90")} />
            {"Transcript "}
            <span className="num font-normal text-muted-foreground">{formatChars(countChars(transcript))}</span>
          </Button>
          <div id={transcriptId} hidden={!open} className="mt-2 overflow-hidden rounded-md border bg-background">
            {open && (
              <TranscriptPane
                ref={transcriptRef}
                label={`Transcript of turn ${number}`}
                transcript={transcript}
                quotes={quotes}
                active={activeRequirement}
                pinned={shownPin}
                className="max-h-80"
              />
            )}
          </div>
        </div>
      </div>
      <div className="flex flex-col gap-4 px-4 py-6 sm:px-6">
        {state.status === "done" && (
          <div className="flex flex-wrap items-center gap-2">
            {delta && <TotalsDeltaBadge delta={delta} />}
            <div className="ml-auto">
              <ResultViewToggle value={view} onChange={setView} />
            </div>
          </div>
        )}
        <AssistantMessage
          state={state}
          onStop={onStop}
          onRetry={onRetry}
          onEditTranscript={onEdit}
          stopRef={stopRef}
          view={view}
          activeRequirement={activeRequirement ?? shownPin?.id}
          onRequirementFocus={setActiveRequirement}
          pinFor={wide ? undefined : (id) => (marked.has(id) ? () => pin(id) : undefined)}
          evidenceNote={evidenceNote}
        />
      </div>
    </li>
  );
};
