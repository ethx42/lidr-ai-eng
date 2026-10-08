import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { StreamState } from "@/lib/estimate/types";
import { useEstimateStream } from "./use-estimate-stream";

const encoder = new TextEncoder();
const frame = (event: string, data: unknown) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;

// An SSE body the test feeds chunk by chunk; aborting the request errors it, as a real fetch body does.
const sseBody = () => {
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({ start: (c) => { controller = c; } });
  return {
    body,
    push: (...chunks: string[]) => chunks.forEach((chunk) => controller.enqueue(encoder.encode(chunk))),
    close: () => controller.close(),
    abort: (reason: unknown) => controller.error(reason),
  };
};

const request = { transcription: "We need a booking portal.", project_type: "web_saas", detail_level: "medium", output_format: "phases_table" } as const;
const breakdown1 = { project_name: "Bo" };
const breakdown2 = { project_name: "Booking portal", tasks: [{ id: "T1", name: "Back" }] };
const response = { estimation: "# Booking portal", provider: "openai", model: "gpt-4o-mini", breakdown: breakdown2 };

describe("useEstimateStream", () => {
  let fetchMock: ReturnType<typeof vi.fn<typeof fetch>>;
  let stream: ReturnType<typeof sseBody>;

  beforeEach(() => {
    fetchMock = vi.fn<typeof fetch>((_url, init) => {
      const body = (stream = sseBody()); // one body per request; `stream` is the latest
      init?.signal?.addEventListener("abort", () => body.abort(new DOMException("aborted", "AbortError")));
      return Promise.resolve(new Response(body.body, { headers: { "content-type": "text/event-stream", "x-request-id": "req-1" } }));
    });
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => vi.unstubAllGlobals());

  const renderStream = () => {
    const states: StreamState[] = [];
    const hook = renderHook(() => {
      const value = useEstimateStream();
      states.push(value.state);
      return value;
    });
    return { ...hook, states };
  };
  const signalOf = (call = 0) => fetchMock.mock.calls[call][1]?.signal;

  it("starts idle", () => {
    expect(renderStream().result.current.state).toEqual({ status: "idle" });
  });

  it("posts the body as JSON and appends refresh=true only when asked", () => {
    const { result } = renderStream();
    act(() => result.current.start(request));
    act(() => result.current.start(request, { refresh: true }));
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/estimate/stream");
    expect(init?.method).toBe("POST");
    expect(new Headers(init?.headers).get("content-type")).toBe("application/json");
    expect(JSON.parse(String(init?.body))).toEqual(request);
    expect(fetchMock.mock.calls[1][0]).toBe("/api/estimate/stream?refresh=true");
    expect(signalOf(0)?.aborted).toBe(true); // a new start supersedes the previous request
  });

  it("appends the chosen prompt version, encoded, and omits an empty one", () => {
    const { result } = renderStream();
    act(() => result.current.start(request, { promptVersion: "v2" }));
    act(() => result.current.start(request, { promptVersion: "v2", refresh: true }));
    act(() => result.current.start(request, { promptVersion: "" }));
    act(() => result.current.start(request, { promptVersion: "v1&refresh=true" }));
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "/api/estimate/stream?prompt_version=v2",
      "/api/estimate/stream?prompt_version=v2&refresh=true",
      "/api/estimate/stream",
      "/api/estimate/stream?prompt_version=v1%26refresh%3Dtrue",
    ]);
  });

  it("posts a FormData body as it is, without a content-type header (the browser writes the boundary), to the given URL", () => {
    const { result } = renderStream();
    const form = new FormData();
    form.set("transcript", "We need a booking portal.");
    form.append("attachments", new File(["%PDF-1.7"], "spec.pdf", { type: "application/pdf" }));
    act(() => result.current.start(form, { url: "/api/sessions/s1/estimate/stream" }));
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/sessions/s1/estimate/stream");
    expect(init?.method).toBe("POST");
    expect(init?.body).toBe(form);
    const headers = new Headers(init?.headers);
    expect(headers.has("content-type")).toBe(false);
    expect(headers.get("accept")).toBe("text/event-stream");
  });

  it("calls onEnd once with how the stream ended, but not when it was stopped or superseded", async () => {
    const { result } = renderStream();
    const ends: StreamState[] = [];
    act(() => result.current.start(request, { onEnd: (end) => ends.push(end) }));
    stream.push(frame("result", response));
    stream.close();
    await waitFor(() => expect(ends).toEqual([{ status: "done", result: response, requestId: "req-1" }]));

    act(() => result.current.start(request, { onEnd: (end) => ends.push(end) }));
    stream.push(frame("error", { code: "session_busy", message: "busy", retryable: true, request_id: "req-2" }));
    await waitFor(() => expect(ends).toHaveLength(2));
    expect(ends[1]).toMatchObject({ status: "error", error: { code: "session_busy" } });

    fetchMock.mockResolvedValueOnce(Response.json({ error: { code: "session_not_found", message: "gone" } }, { status: 404 }));
    act(() => result.current.start(request, { onEnd: (end) => ends.push(end) }));
    await waitFor(() => expect(ends).toHaveLength(3));
    expect(ends[2]).toMatchObject({ status: "error", error: { code: "session_not_found" } });

    act(() => result.current.start(request, { onEnd: (end) => ends.push(end) }));
    act(() => result.current.start(request, { onEnd: (end) => ends.push(end) })); // supersedes the first
    act(() => result.current.stop());
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(ends).toHaveLength(3);
  });

  it("streams status and partials split across chunks, then ends done with the response request id", async () => {
    const { result, states } = renderStream();
    act(() => result.current.start(request));
    expect(result.current.state).toMatchObject({ status: "streaming", partial: null, startedAt: expect.any(Number) });

    stream.push(frame("status", { phase: "calling_llm", provider: "openai", model: "gpt-4o-mini" }), "event: par", `tial\ndata: ${JSON.stringify({ seq: 1, breakdown: breakdown1 })}\n\n`);
    await waitFor(() => expect(result.current.state).toMatchObject({ status: "streaming", phase: "calling_llm", partial: breakdown1 }));

    stream.push(frame("partial", { seq: 2, breakdown: breakdown2 }).slice(0, 20), frame("partial", { seq: 2, breakdown: breakdown2 }).slice(20));
    await waitFor(() => expect(result.current.state).toMatchObject({ status: "streaming", partial: breakdown2 }));

    stream.push(frame("status", { phase: "validating", provider: null, model: null }));
    await waitFor(() => expect(result.current.state).toMatchObject({ status: "streaming", phase: "validating", partial: breakdown2 }));

    stream.push(frame("result", response));
    stream.close();
    await waitFor(() => expect(result.current.state).toEqual({ status: "done", result: response, requestId: "req-1" }));
    expect(states.filter((s) => s.status === "streaming").map((s) => s.partial)).toEqual(expect.arrayContaining([null, breakdown1, breakdown2]));
  });

  it("ignores malformed frames and keeps streaming", async () => {
    const { result } = renderStream();
    act(() => result.current.start(request));
    stream.push(
      frame("partial", { seq: 1, breakdown: breakdown1 }),
      "event: partial\ndata: {\"seq\": 2, \"breakd\n\n",
      frame("partial", { seq: 3, breakdown: "not an object" }),
      frame("partial", { seq: 4 }),
      frame("status", { phase: "validating", provider: null, model: null }), // sentinel: frames are applied in order
    );
    await waitFor(() => expect(result.current.state).toMatchObject({ phase: "validating" }));
    expect(result.current.state).toMatchObject({ status: "streaming", partial: breakdown1 });
    stream.push(frame("result", response));
    stream.close();
    await waitFor(() => expect(result.current.state.status).toBe("done"));
  });

  it("ends in error on an error event and keeps the last partial", async () => {
    const { result } = renderStream();
    act(() => result.current.start(request));
    stream.push(frame("partial", { seq: 1, breakdown: breakdown1 }));
    stream.push(frame("error", { code: "upstream_unavailable", message: "Provider down.", retryable: true, request_id: "req-9" }));
    stream.close();
    await waitFor(() =>
      expect(result.current.state).toEqual({
        status: "error",
        error: { code: "upstream_unavailable", message: "Provider down.", retryable: true, requestId: "req-9" },
        partial: breakdown1,
      }),
    );
  });

  it("stop() aborts the request and ends cancelled with the last partial", async () => {
    const { result } = renderStream();
    act(() => result.current.start(request));
    stream.push(frame("partial", { seq: 1, breakdown: breakdown1 }));
    await waitFor(() => expect(result.current.state).toMatchObject({ partial: breakdown1 }));

    act(() => result.current.stop());
    expect(signalOf()?.aborted).toBe(true);
    expect(result.current.state).toEqual({ status: "cancelled", partial: breakdown1 });
    await new Promise((resolve) => setTimeout(resolve, 20)); // the aborted read settles without overriding the state
    expect(result.current.state).toEqual({ status: "cancelled", partial: breakdown1 });
  });

  it("ignores terminal frames whose payload is not an error or result object", async () => {
    const { result } = renderStream();
    act(() => result.current.start(request));
    stream.push(
      frame("result", 5),
      frame("result", []),
      frame("result", null),
      frame("error", "Provider down."),
      frame("error", { message: "no code" }),
      frame("status", { phase: "validating", provider: null, model: null }), // sentinel: frames are applied in order
    );
    await waitFor(() => expect(result.current.state).toMatchObject({ phase: "validating" }));
    expect(result.current.state.status).toBe("streaming");
    stream.push(frame("result", response));
    stream.close();
    await waitFor(() => expect(result.current.state).toEqual({ status: "done", result: response, requestId: "req-1" }));
  });

  it("skips SSE comments (keep-alive pings) and joins multi-line data", async () => {
    const { result } = renderStream();
    act(() => result.current.start(request));
    stream.push(": keep-alive\n\n", `event: partial\ndata: {"seq": 1,\ndata: "breakdown": ${JSON.stringify(breakdown1)}}\n\n`, ": ping\n\n");
    await waitFor(() => expect(result.current.state).toMatchObject({ status: "streaming", partial: breakdown1 }));
    stream.push(frame("result", response));
    stream.close();
    await waitFor(() => expect(result.current.state.status).toBe("done"));
  });

  it("keeps the response's request id when the stream breaks or an error frame has none", async () => {
    const { result } = renderStream();
    act(() => result.current.start(request));
    stream.close();
    await waitFor(() => expect(result.current.state).toMatchObject({ status: "error", error: { code: "stream_interrupted", requestId: "req-1" } }));

    act(() => result.current.start(request));
    stream.push(frame("error", { code: "internal_error", message: "Unexpected.", retryable: false }));
    await waitFor(() => expect(result.current.state).toMatchObject({ status: "error", error: { code: "internal_error", requestId: "req-1" } }));
  });

  it("maps HTTP 422 JSON to invalid_request with the body's details, without parsing SSE", async () => {
    const details = [{ loc: ["body", "transcription"], msg: "String should have at most 50000 characters", type: "string_too_long" }];
    fetchMock.mockResolvedValueOnce(Response.json({ error: { code: "invalid_request", message: "Invalid request.", details }, request_id: "req-422" }, { status: 422 }));
    const { result } = renderStream();
    act(() => result.current.start(request));
    await waitFor(() =>
      expect(result.current.state).toEqual({
        status: "error",
        error: { code: "invalid_request", message: "Invalid request.", retryable: false, requestId: "req-422", details },
        partial: null,
      }),
    );
  });

  it.each([
    [413, "payload_too_large", false],
    [503, "upstream_unavailable", true],
    [429, "upstream_rate_limited", true],
  ])("maps HTTP %i %s JSON with retryable=%s", async (status, code, retryable) => {
    fetchMock.mockResolvedValueOnce(Response.json({ error: { code, message: "m" }, request_id: "r" }, { status }));
    const { result } = renderStream();
    act(() => result.current.start(request));
    await waitFor(() => expect(result.current.state).toMatchObject({ status: "error", error: { code, retryable } }));
  });

  it("maps a non-JSON error response by status", async () => {
    fetchMock.mockResolvedValueOnce(new Response("Bad Gateway", { status: 503, headers: { "x-request-id": "req-h" } }));
    const { result } = renderStream();
    act(() => result.current.start(request));
    await waitFor(() => expect(result.current.state).toMatchObject({ status: "error", error: { code: "upstream_unavailable", retryable: true, requestId: "req-h" } }));
  });

  it("ends in a retryable stream_interrupted error when the stream closes without a terminal event", async () => {
    const { result } = renderStream();
    act(() => result.current.start(request));
    stream.push(frame("partial", { seq: 1, breakdown: breakdown1 }));
    stream.close();
    await waitFor(() => expect(result.current.state).toMatchObject({ status: "error", error: { code: "stream_interrupted", retryable: true }, partial: breakdown1 }));
  });

  it("ends in stream_interrupted when a 200 response has an empty body", async () => {
    fetchMock.mockResolvedValueOnce(new Response("", { headers: { "content-type": "text/event-stream" } }));
    const { result } = renderStream();
    act(() => result.current.start(request));
    await waitFor(() => expect(result.current.state).toMatchObject({ status: "error", error: { code: "stream_interrupted", retryable: true } }));
  });

  it("ends in stream_interrupted, with the request id, when a 200 response has no body at all", async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { headers: { "content-type": "text/event-stream", "x-request-id": "req-nb" } }));
    const { result } = renderStream();
    act(() => result.current.start(request));
    await waitFor(() => expect(result.current.state).toMatchObject({ status: "error", error: { code: "stream_interrupted", retryable: true, requestId: "req-nb" } }));
  });

  it("ends in stream_interrupted when the request fails", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    const { result } = renderStream();
    act(() => result.current.start(request));
    await waitFor(() => expect(result.current.state).toMatchObject({ status: "error", error: { code: "stream_interrupted", retryable: true }, partial: null }));
  });

  it("reports the fallback provider as switchedTo and keeps it for later phases", async () => {
    const { result } = renderStream();
    act(() => result.current.start(request));
    stream.push(frame("status", { phase: "fallback", provider: "anthropic", model: "claude-haiku-4-5" }));
    await waitFor(() => expect(result.current.state).toMatchObject({ status: "streaming", phase: "fallback", switchedTo: "anthropic" }));
    stream.push(frame("status", { phase: "validating", provider: null, model: null }));
    await waitFor(() => expect(result.current.state).toMatchObject({ status: "streaming", phase: "validating", switchedTo: "anthropic" }));
  });

  it("current() returns the latest state, including an update React has not rendered yet", async () => {
    const { result } = renderStream();
    expect(result.current.current()).toEqual({ status: "idle" });
    act(() => result.current.start(request));
    expect(result.current.current()).toMatchObject({ status: "streaming" });
    await act(async () => {
      stream.push(frame("result", response));
      await new Promise((resolve) => setTimeout(resolve, 0));
      expect(result.current.state.status).toBe("streaming"); // not rendered yet
      expect(result.current.current()).toEqual({ status: "done", result: response, requestId: "req-1" });
    });
    act(() => result.current.stop());
    expect(result.current.current()).toEqual(result.current.state); // stop() after done changes nothing
  });

  it("aborts an in-flight request on unmount and settles it as cancelled", () => {
    const { result, unmount } = renderStream();
    act(() => result.current.start(request));
    const { current } = result.current;
    unmount();
    expect(signalOf()?.aborted).toBe(true);
    // Fast Refresh runs this cleanup but keeps the state: it must not stay "streaming" with nothing left to end it
    expect(current()).toEqual({ status: "cancelled", partial: null });
  });
});
