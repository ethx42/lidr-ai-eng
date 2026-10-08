"use client";

import { CircleAlert, MessageSquarePlus, RotateCcw } from "lucide-react";
import { useRef, useState } from "react";
import { flushSync } from "react-dom";
import { toast } from "sonner";
import { AppHeader } from "@/components/app-header";
import { EstimateForm, type EstimateFormHandle } from "@/components/form/estimate-form";
import { DEFAULT_PARAMS, type EstimateParams } from "@/components/form/estimate-form-schema";
import { InspectorSheet } from "@/components/inspector/inspector";
import { usePromptContext } from "@/components/inspector/use-prompt-context";
import { useServiceContext } from "@/components/service-context";
import { ContextMeter } from "@/components/session/context-meter";
import { Dropzone } from "@/components/session/dropzone";
import { MemoryPanel } from "@/components/session/memory-panel";
import { computeTotalsDelta, type Sums } from "@/components/session/totals-delta";
import { TurnCard, type TurnInput } from "@/components/session/turn-card";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty";
import { useEstimateStream } from "@/hooks/use-estimate-stream";
import { useSession } from "@/hooks/use-session";
import { readEstimate } from "@/lib/estimate/read";
import type { StreamState } from "@/lib/estimate/types";
import { finePointer, scrollBehavior } from "@/lib/focus";
import type { Sample } from "@/lib/samples";
import { limitOr, MAX_ATTACHMENT_BYTES, MAX_ATTACHMENTS } from "@/lib/session/attachments";

type Done = Extract<StreamState, { status: "done" }>;
// `settled`: how the turn ended, kept once a newer turn owns the stream; the latest turn shows the stream's live state.
type Turn = { id: number; input: TurnInput; attempt: number; settled?: StreamState };
// The turns this page sent in one session: a new session (New conversation, or an expired one replaced) starts empty.
type Thread = { sessionId: string | null; turns: Turn[] };

const BUSY = "This conversation is still answering the previous turn";
const UNSENT = "your unsent message";

const isObject = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);
const count = (value: unknown) => (Number.isInteger(value) && Number(value) >= 0 ? Number(value) : undefined);
const strings = (value: unknown) => (Array.isArray(value) ? value.filter((item) => typeof item === "string") : []);

// A completed turn's totals, when readable: the result is unchecked wire data.
const sumsOf = (state: StreamState): Sums | null => {
  if (state.status !== "done") return null;
  const { expected_hours, estimated_cost } = readEstimate(state.result.breakdown).totals ?? {};
  return expected_hours === undefined ? null : { expected_hours, estimated_cost };
};

// What the error card's edit puts back, for the form's "Replace your draft with …?".
const editing = (state: StreamState) =>
  state.status === "error" && state.error.code === "invalid_attachment" ? "the message with the rejected attachment" : "the transcript to shorten";

const toForm = ({ body, files }: TurnInput) => {
  const form = new FormData();
  form.set("transcript", body.transcription);
  form.set("project_type", body.project_type);
  form.set("detail_level", body.detail_level);
  form.set("output_format", body.output_format);
  for (const file of files) form.append("attachments", file, file.name);
  return form;
};

// `earlier`: turns the session already holds from before this page loaded (a reload keeps the session, not its answers).
const NoTurnYet = ({ earlier }: { earlier: number }) => (
  <Empty className="py-10">
    <EmptyHeader>
      {earlier > 0 ? (
        <>
          <EmptyTitle className="text-base font-semibold">This conversation continues</EmptyTitle>
          <EmptyDescription>
            {`${earlier} earlier ${earlier === 1 ? "turn is" : "turns are"} kept in its history, with the project memory; their answers are not shown again. Send the next turn, or start a new conversation.`}
          </EmptyDescription>
        </>
      ) : (
        <>
          <EmptyTitle className="text-base font-semibold">Start the conversation</EmptyTitle>
          <EmptyDescription>
            Paste the first meeting transcript and attach any documents. Each turn adds to the project memory, so later turns can refine the estimate.
          </EmptyDescription>
        </>
      )}
    </EmptyHeader>
  </Empty>
);

// No live region: the failure is shown where the memory would be, and Retry is the way on (spec §8, recoverable errors).
const SessionError = ({ onRetry }: { onRetry: () => void }) => (
  <Alert role={undefined} className="border-destructive/40 bg-danger-subtle">
    <CircleAlert className="text-destructive" />
    <AlertTitle className="text-foreground">The conversation could not be started.</AlertTitle>
    <AlertDescription className="flex flex-col items-start gap-2 text-foreground">
      <p>The AI service did not answer. Your draft stays in the composer.</p>
      <Button type="button" variant="outline" size="xs" onClick={onRetry}>
        <RotateCcw />
        Retry
      </Button>
    </AlertDescription>
  </Alert>
);

// The session workspace (spec §7.3): the conversation's turns with the composer below them, the project memory and the
// history meter beside them (above them below 1024 px), and the inspector in a sheet from the header. Each turn is one
// multipart request to the session; only the latest turn streams, and only a stopped or failed latest turn can be
// retried (S5-R3). The page scrolls as a whole under a sticky header.
export const Workspace = ({ samples }: { samples: Sample[] }) => {
  const service = useServiceContext();
  const session = useSession();
  const { sessionId, view, failed } = session;
  const { state, start, stop, current } = useEstimateStream();
  const [thread, setThread] = useState<Thread>({ sessionId: null, turns: [] });
  if (thread.sessionId !== sessionId) setThread({ sessionId, turns: [] }); // a new session starts an empty thread
  const turns = thread.sessionId === sessionId ? thread.turns : [];
  const [files, setFiles] = useState<File[]>([]);
  const [params, setParams] = useState<EstimateParams>(DEFAULT_PARAMS);
  const [confirming, setConfirming] = useState(false);
  const formRef = useRef<EstimateFormHandle>(null);
  const stopRef = useRef<HTMLButtonElement>(null);
  const latestRef = useRef<HTMLLIElement>(null);
  const newConversationRef = useRef<HTMLButtonElement>(null);
  const startedOver = useRef(false); // how the confirmation closed: Start new, or Cancel / Esc
  const ids = useRef(0);
  // The prompt sessions send: the composer's choices on the session's version (v3, S5-R4), asked for only once the
  // session is known, so the service default's prompt is never fetched first.
  const promptContext = usePromptContext(view && { ...params, prompt_version: view.prompt_version });

  const latest = turns.at(-1);
  const shown = turns.map((turn) => turn.settled ?? state);
  const sums = shown.map(sumsOf);
  const lastDone = shown.findLast((turnState): turnState is Done => turnState.status === "done");
  const answer: unknown = lastDone?.result;
  const result = isObject(answer) ? answer : {};
  // The memory and the meter follow the latest completed turn's answer, else the session's view.
  const metadata = lastDone ? result.project_metadata : view?.project_metadata;
  const history = (lastDone ? count(result.history_turns) : undefined) ?? view?.history_turns;
  const noSession = failed && !view;
  // The view is loaded with the session and not after each turn, so its count is the turns held before this page's.
  const earlier = view?.history_turns ?? 0;
  // `current()` rather than the rendered state: a result that arrived but is not rendered yet already ended the turn.
  const answering = () => Boolean(latest && !latest.settled && current().status === "streaming");

  // `what` completes the form's "Replace your draft with …?" when the composer holds a different draft.
  const restore = (input: TurnInput, what: string) => {
    setFiles(input.files);
    formRef.current?.edit(input.body.transcription, what);
  };

  // How a turn's stream ended. A turn the session refused never happened: 409 (another turn holds the session) takes it
  // out of the thread, and 404 (the session expired or was evicted) starts a new conversation; either way its message
  // goes back to the composer. A result is the session's new state: the memory and the meter read it.
  const ended = (turnId: number, input: TurnInput, end: StreamState) => {
    if (end.status !== "error") return;
    if (end.error.code === "session_busy") {
      setThread((current) => ({ ...current, turns: current.turns.filter((turn) => turn.id !== turnId) }));
      restore(input, UNSENT);
      toast(BUSY);
    }
    if (end.error.code === "session_not_found") {
      restore(input, UNSENT);
      toast("This conversation expired, so a new one was started. Your message is back in the composer.");
      void session.reset();
    }
  };

  const send = (id: number, input: TurnInput) => {
    if (!sessionId) return;
    start(toForm(input), { url: `/api/sessions/${sessionId}/estimate/stream`, onEnd: (end) => ended(id, input, end) });
  };

  // A new turn goes to the thread with the composer's files; the composer empties for the next one. flushSync renders
  // the turn first, so it can be brought into view and, on a touch screen, focus can move from Estimate to its Stop
  // (never into the composer, which would open the keyboard over the answer); a mouse keeps focus where it was.
  const submit = (body: TurnInput["body"]) => {
    if (!sessionId) {
      if (!failed) return void toast("The conversation is still starting. Try again in a moment.");
      toast.error("No conversation yet: the AI service could not start one. Try again in a moment.");
      return void session.refresh();
    }
    if (answering()) return void toast(BUSY);
    const previous = current();
    const input = { body, files };
    const id = ++ids.current;
    flushSync(() => {
      setThread((current) => ({ ...current, turns: [...current.turns.map((turn) => (turn.settled ? turn : { ...turn, settled: previous })), { id, input, attempt: 0 }] }));
      setFiles([]);
      send(id, input);
    });
    formRef.current?.clear();
    latestRef.current?.scrollIntoView({ block: "start", behavior: scrollBehavior() });
    if (!finePointer()) stopRef.current?.focus({ preventScroll: true });
  };

  // A new attempt at the latest turn, with its own transcript, choices and files, whatever the composer says now.
  const retry = (turn: Turn) => {
    setThread((current) => ({ ...current, turns: current.turns.map((other) => (other.id === turn.id ? { ...other, attempt: other.attempt + 1 } : other)) }));
    send(turn.id, turn.input);
  };

  const startOver = () => {
    stop();
    void session.reset().then(() => toast("Started a new conversation."));
  };
  // Managed focus after a new conversation starts: with a mouse the transcript, for the new conversation's first turn;
  // on a touch screen New conversation itself, since focusing the transcript would open the keyboard over the page.
  const focusAfterStart = () => {
    if (!formRef.current?.focus()) newConversationRef.current?.focus();
  };
  const newConversation = () => {
    if (answering()) {
      startedOver.current = false;
      return setConfirming(true);
    }
    startOver();
    focusAfterStart();
  };

  return (
    <div className="flex min-h-dvh flex-col">
      <div className="sticky top-0 z-40 bg-background">
        <AppHeader
          actions={
            <>
              <Button ref={newConversationRef} type="button" variant="secondary" onClick={newConversation}>
                <MessageSquarePlus />
                <span className="sr-only sm:not-sr-only">New conversation</span>
              </Button>
              <InspectorSheet call={lastDone} context={promptContext} />
            </>
          }
        />
      </div>
      <div className="flex flex-1 flex-col lg:flex-row">
        {/* First in reading order (what the next turn is sent with); beside the conversation from 1024 px. */}
        <aside
          aria-label="Project memory"
          className="flex flex-col gap-6 border-b bg-surface px-4 py-6 sm:px-6 lg:sticky lg:top-12 lg:order-last lg:h-[calc(100dvh-3rem)] lg:w-80 lg:shrink-0 lg:overflow-y-auto lg:border-b-0 lg:border-l xl:w-96"
        >
          {noSession && <SessionError onRetry={() => void session.refresh()} />}
          <MemoryPanel metadata={noSession ? null : metadata} changed={lastDone ? strings(result.metadata_changes) : []} />
          {!noSession && <ContextMeter turns={history} max={view?.max_turns} />}
        </aside>
        {/* `relative` contains sr-only descendants, so they never extend the page's scroll. */}
        <main className="relative flex min-w-0 flex-1 flex-col">
          <div className="flex-1 px-4 py-6 sm:px-6">
            {turns.length === 0 ? (
              <NoTurnYet earlier={earlier} />
            ) : (
              <ol aria-label="Conversation" className="flex flex-col gap-6">
                {turns.map((turn, i) => {
                  const isLatest = turn === latest;
                  const turnState = shown[i];
                  const own = sums[i];
                  return (
                    <TurnCard
                      key={turn.id}
                      ref={isLatest ? latestRef : undefined}
                      number={earlier + i + 1}
                      input={turn.input}
                      state={turnState}
                      attempt={turn.attempt}
                      delta={own && computeTotalsDelta(sums.slice(0, i).findLast((earlier) => earlier !== null) ?? null, own)}
                      onStop={stop}
                      onRetry={isLatest && (turnState.status === "cancelled" || turnState.status === "error") ? () => retry(turn) : undefined}
                      onEdit={() => restore(turn.input, editing(turnState))}
                      stopRef={isLatest ? stopRef : undefined}
                    />
                  );
                })}
              </ol>
            )}
          </div>
          <div className="border-t bg-background">
            <EstimateForm
              handle={formRef}
              onSubmit={submit}
              onParamsChange={setParams}
              maxChars={service?.max_transcription_chars}
              transcriptLabel="Transcript for this turn"
              attachments={
                <Dropzone
                  maxFiles={limitOr(service?.max_attachments, MAX_ATTACHMENTS)}
                  maxBytes={limitOr(service?.max_attachment_bytes, MAX_ATTACHMENT_BYTES)}
                  files={files}
                  onChange={setFiles}
                />
              }
              samples={samples}
              compact={turns.length > 0}
            />
          </div>
        </main>
      </div>
      <AlertDialog open={confirming} onOpenChange={setConfirming}>
        {/* Opened from state, so Radix has no trigger to give focus back to (it would fall to the page): Cancel returns
            it to New conversation, and Start new moves it as above. */}
        <AlertDialogContent
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            if (startedOver.current) focusAfterStart();
            else newConversationRef.current?.focus();
          }}
        >
          <AlertDialogHeader>
            <AlertDialogTitle>Start a new conversation?</AlertDialogTitle>
            <AlertDialogDescription>The answer in progress stops, and the new conversation starts without this one&apos;s history and memory.</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                startedOver.current = true;
                startOver();
              }}
            >
              Start new
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
};

