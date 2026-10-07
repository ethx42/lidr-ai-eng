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
      const result = parse<Schemas["EstimateResponse"]>(data);
      if (result) update(() => ({ status: "done", result, requestId }));
      return Boolean(result);
    }
    case "error": {
      const error = parse<Schemas["ErrorEvent"]>(data);
      if (error) update((s) => ({ status: "error", error: { code: error.code, message: error.message, retryable: error.retryable, requestId: error.request_id }, partial: partialOf(s) }));
      return Boolean(error);
    }
    default:
      return false;
  }
};

const run = async (url: string, body: Schemas["EstimateRequest"], signal: AbortSignal, update: Update) => {
  const fail = (error: StreamError) => update((s) => ({ status: "error", error, partial: partialOf(s) }));
  try {
    const res = await fetch(url, { method: "POST", headers: { "content-type": "application/json", accept: "text/event-stream" }, body: JSON.stringify(body), signal });
    if (!res.ok) return fail(await fromErrorResponse(res));
    if (!res.body) return fail(streamInterrupted());
    const requestId = res.headers.get("x-request-id") ?? undefined;
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
    fail(streamInterrupted()); // e.g. the AI service shut down mid-stream
  } catch {
    fail(streamInterrupted()); // network drop or parser error; after an abort, `update` ignores it
  }
};

export const useEstimateStream = (endpoint = "/api/estimate/stream") => {
  const [state, setState] = useState<StreamState>({ status: "idle" });
  const controllerRef = useRef<AbortController | null>(null);

  useEffect(() => () => controllerRef.current?.abort(), []);

  const start = useCallback(
    (body: Schemas["EstimateRequest"], { refresh = false }: { refresh?: boolean } = {}) => {
      controllerRef.current?.abort();
      const controller = new AbortController();
      controllerRef.current = controller;
      setState({ status: "streaming", phase: "calling_llm", partial: null, startedAt: Date.now() });
      // a superseded or stopped request never writes state again
      const update: Update = (next) => {
        if (!controller.signal.aborted) setState(next);
      };
      void run(refresh ? `${endpoint}?refresh=true` : endpoint, body, controller.signal, update);
    },
    [endpoint],
  );

  const stop = useCallback(() => {
    controllerRef.current?.abort();
    setState((s) => (s.status === "streaming" ? { status: "cancelled", partial: s.partial } : s));
  }, []);

  return { state, start, stop };
};
