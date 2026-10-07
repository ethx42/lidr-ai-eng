"use client";

import { useMemo, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { AppHeader } from "@/components/app-header";
import { AssistantMessage, keptFor } from "@/components/chat/assistant-message";
import { EstimateForm, type EstimateFormHandle } from "@/components/form/estimate-form";
import {
  DEFAULT_PARAMS,
  DETAIL_LEVEL_LABELS,
  type EstimateParams,
  OUTPUT_FORMAT_LABELS,
  PROJECT_TYPE_LABELS,
} from "@/components/form/estimate-form-schema";
import { InspectorPanel, InspectorSheet } from "@/components/inspector/inspector";
import { usePromptContext } from "@/components/inspector/use-prompt-context";
import { useServiceContext } from "@/components/service-context";
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty";
import { useEstimateStream } from "@/hooks/use-estimate-stream";
import { useMediaQuery } from "@/hooks/use-media-query";
import type { components } from "@/lib/ai-service/schema";
import { toUserMessage } from "@/lib/errors";
import { readEstimate, readGrounding } from "@/lib/estimate/read";
import type { StreamState } from "@/lib/estimate/types";
import { type EvidenceQuote, evidenceFinder } from "@/lib/evidence";
import { finePointer, scrollBehavior } from "@/lib/focus";
import type { Sample } from "@/lib/samples";
import { type ResultView, ResultViewToggle } from "./result-view-toggle";
import { SHORT, type SplitTab, SplitView, WIDE } from "./split-view";
import { type Pin, TranscriptPane } from "./transcript-pane";

type Done = Extract<StreamState, { status: "done" }>;
// The one run the workspace shows (spec §6.5: a form, not a thread). `kept`: the completed estimate a Regenerate that
// is stopped or fails falls back to, so stopping never costs finished work.
type Run = { id: number; body: components["schemas"]["EstimateRequest"]; promptVersion: string; kept?: Done };

// The choices a run was made with, in words ("Web SaaS, medium detail, phases table, prompt v1").
const describe = ({ body, promptVersion }: Run) =>
  [
    PROJECT_TYPE_LABELS[body.project_type],
    `${DETAIL_LEVEL_LABELS[body.detail_level].toLowerCase()} detail`,
    OUTPUT_FORMAT_LABELS[body.output_format].toLowerCase(),
    promptVersion && `prompt ${promptVersion}`,
  ]
    .filter(Boolean)
    .join(", ");

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

// How a run ended, for the announcement made while its estimate is out of sight.
const endOf = (state: StreamState, kept?: Done) => {
  switch (state.status) {
    case "done":
      return "Estimate ready";
    case "cancelled":
      return kept ? "Stopped — kept the previous estimate" : "Stopped";
    case "error":
      return toUserMessage(state.error).title;
    default:
      return "";
  }
};

const NoRunYet = () => (
  <Empty className="flex-1 py-10">
    <EmptyHeader>
      <EmptyTitle className="text-base font-semibold">Your estimate appears here</EmptyTitle>
      <EmptyDescription>
        Tasks with hour ranges, the quotes behind each requirement highlighted in your transcript, and the questions to ask the client.
      </EmptyDescription>
    </EmptyHeader>
  </Empty>
);

// Owns the page: the typed form, the run it starts (stream, Stop, Regenerate, kept estimate), the transcript and
// estimate side by side, and the inspector, which shows the prompt for the form's current choices and the last call.
export const Workspace = ({ samples }: { samples: Sample[] }) => {
  const service = useServiceContext();
  const { state, start, stop, current } = useEstimateStream();
  const [run, setRun] = useState<Run | null>(null);
  // The last call that finished before the current stream started: the inspector's "Last call".
  const [finished, setFinished] = useState<Done>();
  const [params, setParams] = useState<EstimateParams>(DEFAULT_PARAMS);
  const [view, setView] = useState<ResultView>("structured");
  const [tab, setTab] = useState<SplitTab>("estimate");
  // The stream state when the estimate went out of sight (the Transcript tab below 768 px): only a later change is news.
  const [hiddenAt, setHiddenAt] = useState<StreamState | null>(null);
  // Hovered or focused; `pinned` (below 768 px) outlives both, until the next pin or run.
  const [activeRequirement, setActiveRequirement] = useState<string | null>(null);
  const [pinned, setPinned] = useState<Pin | null>(null);
  const formRef = useRef<EstimateFormHandle>(null);
  const transcriptRef = useRef<HTMLDivElement>(null);
  const inspectorRef = useRef<HTMLElement>(null);
  const stopRef = useRef<HTMLButtonElement>(null);
  const splitRef = useRef<HTMLDivElement>(null);
  const resultRef = useRef<HTMLDivElement>(null);
  const runs = useRef(0);
  const promptContext = usePromptContext(params);
  const wide = useMediaQuery(WIDE, true);

  const kept = run ? keptFor(state, run.kept) : undefined;
  const shown = kept ?? state;
  const quotes = useMemo(() => quotesOf(shown), [shown]);
  const transcript = run?.body.transcription ?? "";
  const find = useMemo(() => evidenceFinder(transcript), [transcript]);
  // The requirements whose quote is marked in the transcript: only they can be pinned; any other keeps its hover card.
  const marked = useMemo(() => new Set(find(quotes).map(({ id }) => id)), [find, quotes]);
  // Side by side, hover and focus link requirements to quotes; a pin made below 768 px waits until it is narrow again.
  const shownPin = wide ? null : pinned;
  // A stopped or failed stream never replaces the last finished call.
  const lastCall = state.status === "done" ? state : finished;
  // The estimate's own live regions are silent inside a hidden tab panel, so how the run ends is announced from here.
  const announcement = run && !wide && tab === "transcript" && state !== hiddenAt ? endOf(state, kept) : "";

  const showTab = (next: SplitTab) => {
    setTab(next);
    setHiddenAt(current());
  };

  // Below 768 px the transcript sits behind a tab, and reaching it ends the hover or focus that links a requirement to
  // its quote. So Evidence pins the requirement there and opens the transcript at its quote; focus moves to the
  // transcript, since the tab switch hides the button.
  const pin = (id: string) => {
    flushSync(() => {
      setPinned({ id });
      showTab("transcript");
    });
    transcriptRef.current?.focus({ preventScroll: true });
  };

  // `current()` rather than the rendered state: a result that arrived but is not rendered yet still counts as finished.
  const settleLast = () => {
    const latest = current();
    if (latest.status === "done") setFinished(latest);
    return latest;
  };

  // A new run starts in Structured, at the top, on the Estimate tab below 768 px; where the form and the result scroll
  // together (narrow or short viewports) the result is brought into view. flushSync renders it first, so a touch screen
  // can move focus from Estimate to the new Stop (never into the transcript, which would open the keyboard over the
  // result); a mouse keeps focus where it was.
  const submit = (body: Run["body"], { promptVersion }: { promptVersion: string }) => {
    settleLast();
    flushSync(() => {
      setRun({ id: ++runs.current, body, promptVersion });
      setView("structured");
      setTab("estimate");
      setActiveRequirement(null);
      setPinned(null);
      start(body, { promptVersion });
    });
    if (resultRef.current) resultRef.current.scrollTop = 0;
    if (!window.matchMedia(WIDE).matches || window.matchMedia(SHORT).matches) splitRef.current?.scrollIntoView({ block: "start", behavior: scrollBehavior() });
    if (!finePointer()) stopRef.current?.focus({ preventScroll: true });
  };

  // Same transcript, choices and prompt version as the run, whatever the form says now; skips the exact-match cache,
  // and streams in from the top.
  // Each view starts at its top: the document and the structured estimate do not share a layout.
  const showView = (next: ResultView) => {
    setView(next);
    if (resultRef.current) resultRef.current.scrollTop = 0;
  };

  const regenerate = () => {
    if (!run) return;
    const latest = settleLast();
    setRun({ ...run, kept: latest.status === "done" ? latest : run.kept });
    setView("structured");
    setPinned(null); // the new attempt numbers its own requirements
    if (resultRef.current) resultRef.current.scrollTop = 0;
    start(run.body, { refresh: true, promptVersion: run.promptVersion });
  };

  return (
    // Below 480 px tall, or 772 px side by side (`short`), nothing is fixed: the page scrolls as a whole and the split is
    // a viewport tall.
    // Below 768 px wide the form and the tabs scroll together in `main`.
    <div className="flex h-dvh min-h-0 flex-col short:h-auto short:min-h-dvh">
      <AppHeader actions={<InspectorSheet call={lastCall} context={promptContext} panelRef={inspectorRef} />} />
      <div className="flex min-h-0 flex-1">
        {/* `relative` contains sr-only descendants, so only the intended regions scroll, never the page. */}
        <main className="relative flex min-w-0 flex-1 flex-col overflow-hidden max-md:overflow-y-auto short:overflow-visible">
          <EstimateForm
            handle={formRef}
            onSubmit={submit}
            onParamsChange={setParams}
            versions={service?.available_versions ?? []}
            defaultVersion={service?.prompt_version ?? ""}
            maxChars={service?.max_transcription_chars}
            samples={samples}
            compact={run !== null}
          />
          {run ? (
            <SplitView
              ref={splitRef}
              tab={tab}
              onTabChange={showTab}
              className="min-h-0 flex-1 max-md:flex-none md:short:h-dvh md:short:flex-none"
              transcript={{
                label: "Transcript",
                description: describe(run),
                children: (
                  <TranscriptPane key={run.id} ref={transcriptRef} transcript={transcript} quotes={quotes} active={activeRequirement} pinned={shownPin} />
                ),
              }}
              estimate={{
                label: "Estimate",
                aside: shown.status === "done" && <ResultViewToggle value={view} onChange={showView} />,
                children: (
                  <div ref={resultRef} className="relative h-full overflow-y-auto px-4 py-6 sm:px-6">
                    <AssistantMessage
                      state={state}
                      kept={run.kept}
                      onStop={stop}
                      onRegenerate={regenerate}
                      onEditTranscript={() => formRef.current?.edit(run.body.transcription)}
                      stopRef={stopRef}
                      view={view}
                      activeRequirement={activeRequirement ?? shownPin?.id}
                      onRequirementFocus={setActiveRequirement}
                      pinFor={wide ? undefined : (id) => (marked.has(id) ? () => pin(id) : undefined)}
                    />
                  </div>
                ),
              }}
            />
          ) : (
            <NoRunYet />
          )}
          <p role="status" data-slot="run-status" className="sr-only">
            {announcement}
          </p>
        </main>
        <InspectorPanel ref={inspectorRef} call={lastCall} context={promptContext} />
      </div>
    </div>
  );
};
