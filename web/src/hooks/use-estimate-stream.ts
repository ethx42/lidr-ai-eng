import { EventSourceParserStream } from "eventsource-parser/stream";
import { useCallback, useEffect, useRef, useState } from "react";
import type { components } from "@/lib/ai-service/schema";
import { fromErrorResponse, streamInterrupted } from "@/lib/errors";
import type { StreamError, StreamState } from "@/lib/estimate/types";

type Schemas = components["schemas"];
type Streaming = Extract<StreamState, { status: "streaming" }>;
type Update = (next: (state: StreamState) => StreamState) => void;

const MAX_EVENT_CHARS = 1_000_000;

const parse = <T>(data: string): T | undefined => {
  try {
    return JSON.parse(data);
  } catch {
    return undefined; // malformed frame: ignored
  }
};
const isObject = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);
const partialOf = (state: StreamState) => (state.status === "streaming" ? state.partial : null);
const patch = (update: Update, fields: Partial<Omit<Streaming, "status">>) => update((s) => (s.status === "streaming" ? { ...s, ...fields } : s));

// One state update per SSE frame; returns true once the terminal event (`result` or `error`) is applied.
// A terminal frame whose payload is not an object is ignored like any malformed frame.
const apply = (event: string | undefined, data: string, update: Update, requestId?: string) => {
  switch (event) {
    case "status": {
      const status = parse<Schemas["StatusEvent"]>(data);
      if (status) patch(update, { phase: status.phase, ...(status.phase === "fallback" && status.provider && { switchedTo: status.provider }) });
      return false;
    }
    case "partial": {
      const breakdown = parse<Schemas["PartialEvent"]>(data)?.breakdown;
      if (isObject(breakdown)) patch(update, { partial: breakdown });
      return false;
    }
    case "result": {
      const result = parse<Schemas["EstimateResponse"]>(data); // unchecked beyond this: the view reads it through guards
      if (!isObject(result)) return false;
      update(() => ({ status: "done", result, requestId }));
      return true;
    }
    case "error": {
      const error = parse<unknown>(data);
      if (!isObject(error) || typeof error.code !== "string") return false;
      const next: StreamError = {
        code: error.code,
        message: typeof error.message === "string" ? error.message : "",
        retryable: error.retryable === true,
        requestId: typeof error.request_id === "string" ? error.request_id : requestId,
      };
      update((s) => ({ status: "error", error: next, partial: partialOf(s) }));
      return true;
    }
    default:
      return false;
  }
};

// After an abort, `update` ignores every failure below.
const run = async (url: string, body: Schemas["EstimateRequest"], signal: AbortSignal, update: Update) => {
  const fail = (error: StreamError) => update((s) => ({ status: "error", error, partial: partialOf(s) }));
  const res = await fetch(url, { method: "POST", headers: { "content-type": "application/json", accept: "text/event-stream" }, body: JSON.stringify(body), signal }).catch(
    () => null,
  );
  if (!res) return fail(streamInterrupted()); // network failure
  if (!res.ok) return fail(await fromErrorResponse(res));
  const requestId = res.headers.get("x-request-id") ?? undefined;
  if (!res.body) return fail(streamInterrupted(requestId));
  try {
    // getReader() rather than `for await`: Safari < 27 and Next's TS lib lack ReadableStream async iteration
    const reader = res.body
      .pipeThrough(new TextDecoderStream())
      .pipeThrough(new EventSourceParserStream({ onError: "terminate", maxBufferSize: MAX_EVENT_CHARS }))
      .getReader();
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      if (apply(value.event, value.data, update, requestId)) return;
    }
    fail(streamInterrupted(requestId)); // e.g. the AI service shut down mid-stream
  } catch {
    fail(streamInterrupted(requestId)); // network drop or parser error
  }
};

const IDLE: StreamState = { status: "idle" };

export const useEstimateStream = (endpoint = "/api/estimate/stream") => {
  const [state, setState] = useState<StreamState>(IDLE);
  const latest = useRef<StreamState>(IDLE);
  const controllerRef = useRef<AbortController | null>(null);

  // Every transition goes through here, so `current()` sees it before React renders it.
  const commit = useCallback((next: (state: StreamState) => StreamState) => {
    latest.current = next(latest.current);
    setState(latest.current);
  }, []);
  const current = useCallback(() => latest.current, []);

  const start = useCallback(
    (body: Schemas["EstimateRequest"], { refresh = false }: { refresh?: boolean } = {}) => {
      controllerRef.current?.abort();
      const controller = new AbortController();
      controllerRef.current = controller;
      const startedAt = Date.now();
      commit(() => ({ status: "streaming", phase: "calling_llm", partial: null, startedAt }));
      // a superseded or stopped request never writes state again
      const update: Update = (next) => {
        if (!controller.signal.aborted) commit(next);
      };
      void run(refresh ? `${endpoint}?refresh=true` : endpoint, body, controller.signal, update);
    },
    [endpoint, commit],
  );

  const stop = useCallback(() => {
    controllerRef.current?.abort();
    commit((s) => (s.status === "streaming" ? { status: "cancelled", partial: s.partial } : s));
  }, [commit]);

  // Unmount stops like the Stop button, so the state settles: Fast Refresh runs this cleanup but keeps the state, and a
  // bare abort would leave it "streaming" with nothing left to end it.
  useEffect(() => stop, [stop]);

  return { state, start, stop, current };
};
