import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fullResponse } from "@/lib/estimate/fixtures";
import { useThread } from "./use-thread";

const KEY = "estimator.thread.v1";
const encoder = new TextEncoder();
const frame = (event: string, data: unknown) => encoder.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);

// One SSE body per request, fed by the test; aborting the request errors it, as a real fetch body does.
const sseBody = (signal?: AbortSignal | null) => {
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({ start: (c) => { controller = c; } });
  signal?.addEventListener("abort", () => controller.error(new DOMException("aborted", "AbortError")));
  return { body, push: (chunk: Uint8Array) => controller.enqueue(chunk) };
};

const doneTurn = (id: string) => ({ id, transcription: `Transcript ${id}`, state: { status: "done", result: fullResponse, requestId: `req-${id}` } });
const stored = () => JSON.parse(sessionStorage.getItem(KEY) ?? "null");

describe("useThread", () => {
  let fetchMock: ReturnType<typeof vi.fn<typeof fetch>>;
  let streams: ReturnType<typeof sseBody>[];

  beforeEach(() => {
    sessionStorage.clear();
    streams = [];
    fetchMock = vi.fn<typeof fetch>((_url, init) => {
      const stream = sseBody(init?.signal);
      streams.push(stream);
      return Promise.resolve(new Response(stream.body, { headers: { "content-type": "text/event-stream", "x-request-id": "req-1" } }));
    });
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  const complete = async (result: { current: ReturnType<typeof useThread> }, stream: number) => {
    streams[stream].push(frame("result", fullResponse));
    await waitFor(() => expect(result.current.turns.at(-1)?.state.status).toBe("done"));
  };

  it("starts empty, then streams each sent transcript as its own turn", async () => {
    const { result } = renderHook(useThread);
    expect(result.current.turns).toEqual([]);

    act(() => result.current.send("We need a booking portal."));
    expect(result.current.turns).toEqual([{ id: expect.any(String), transcription: "We need a booking portal.", state: expect.objectContaining({ status: "streaming" }) }]);
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({ transcription: "We need a booking portal." });

    streams[0].push(frame("partial", { seq: 1, breakdown: { project_name: "Booking" } }));
    await waitFor(() => expect(result.current.turns[0].state).toMatchObject({ status: "streaming", partial: { project_name: "Booking" } }));
    await complete(result, 0);
    expect(result.current.turns[0].state).toEqual({ status: "done", result: fullResponse, requestId: "req-1" });
  });

  it("ignores a blank transcript", () => {
    const { result } = renderHook(useThread);
    act(() => result.current.send("  \n "));
    expect(result.current.turns).toEqual([]);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("stops the streaming turn on request, keeping its partial content", async () => {
    const { result } = renderHook(useThread);
    act(() => result.current.send("First"));
    streams[0].push(frame("partial", { seq: 1, breakdown: { project_name: "First" } }));
    await waitFor(() => expect(result.current.turns[0].state).toMatchObject({ partial: { project_name: "First" } }));

    act(() => result.current.stop());
    expect(result.current.turns[0].state).toEqual({ status: "cancelled", partial: { project_name: "First" } });
    expect(fetchMock.mock.calls[0][1]?.signal?.aborted).toBe(true);
  });

  it("stops the previous turn when a new one is sent while it streams", async () => {
    const { result } = renderHook(useThread);
    act(() => result.current.send("First"));
    streams[0].push(frame("partial", { seq: 1, breakdown: { project_name: "First" } }));
    await waitFor(() => expect(result.current.turns[0].state).toMatchObject({ partial: { project_name: "First" } }));

    act(() => result.current.send("Second"));
    expect(fetchMock.mock.calls[0][1]?.signal?.aborted).toBe(true);
    expect(result.current.turns.map((turn) => [turn.transcription, turn.state.status])).toEqual([
      ["First", "cancelled"],
      ["Second", "streaming"],
    ]);
    expect(result.current.turns[0].state).toEqual({ status: "cancelled", partial: { project_name: "First" } });

    await complete(result, 1);
    expect(result.current.turns.map((turn) => turn.state.status)).toEqual(["cancelled", "done"]);
  });

  it("regenerates a turn in place, skipping the cache, and keeps the other turns settled", async () => {
    const { result } = renderHook(useThread);
    act(() => result.current.send("First"));
    await complete(result, 0);
    act(() => result.current.send("Second"));
    await complete(result, 1);

    const first = result.current.turns[0].id;
    act(() => result.current.regenerate(first));
    expect(fetchMock.mock.calls[2][0]).toBe("/api/estimate/stream?refresh=true");
    expect(JSON.parse(String(fetchMock.mock.calls[2][1]?.body))).toEqual({ transcription: "First" });
    expect(result.current.turns.map((turn) => [turn.id === first, turn.state.status])).toEqual([
      [true, "streaming"],
      [false, "done"],
    ]);

    streams[2].push(frame("result", { ...fullResponse, model: "gpt-4o" }));
    await waitFor(() => expect(result.current.turns[0].state).toMatchObject({ status: "done", result: { model: "gpt-4o" } }));
    expect(result.current.turns[1].state).toMatchObject({ status: "done", result: { model: "gpt-4o-mini" } });
  });

  it("keeps the previous estimate when a regenerate is stopped, and after a reload", async () => {
    const first = renderHook(useThread);
    act(() => first.result.current.send("First"));
    await complete(first.result, 0);
    const previous = first.result.current.turns[0].state;

    act(() => first.result.current.regenerate(first.result.current.turns[0].id));
    streams[1].push(frame("partial", { seq: 1, breakdown: { project_name: "Fresh" } }));
    await waitFor(() => expect(first.result.current.turns[0].state).toMatchObject({ partial: { project_name: "Fresh" } }));
    expect(first.result.current.turns[0].kept).toBeUndefined(); // the new attempt is what streams

    act(() => first.result.current.stop());
    expect(first.result.current.turns[0]).toMatchObject({ state: { status: "cancelled", partial: { project_name: "Fresh" } }, kept: previous });
    expect(stored()).toEqual([{ id: first.result.current.turns[0].id, transcription: "First", state: previous }]);
    first.unmount();

    expect(renderHook(useThread).result.current.turns).toEqual([{ id: expect.any(String), transcription: "First", state: previous }]);
  });

  it("keeps the previous estimate when a regenerate fails, and after a reload", async () => {
    const first = renderHook(useThread);
    act(() => first.result.current.send("First"));
    await complete(first.result, 0);
    const previous = first.result.current.turns[0].state;

    act(() => first.result.current.regenerate(first.result.current.turns[0].id));
    streams[1].push(frame("error", { code: "upstream_unavailable", message: "down", retryable: true, request_id: "req-9" }));
    await waitFor(() => expect(first.result.current.turns[0].state.status).toBe("error"));
    expect(first.result.current.turns[0].kept).toEqual(previous);
    first.unmount();

    expect(renderHook(useThread).result.current.turns.map((turn) => turn.state)).toEqual([previous]);
  });

  it("keeps the original estimate through repeated stopped regenerates and a send that interrupts one", async () => {
    const { result } = renderHook(useThread);
    act(() => result.current.send("First"));
    await complete(result, 0);
    const previous = result.current.turns[0].state;
    const id = result.current.turns[0].id;

    act(() => result.current.regenerate(id));
    act(() => result.current.stop());
    act(() => result.current.regenerate(id));
    act(() => result.current.send("Second")); // interrupts the second regenerate
    expect(result.current.turns[0]).toMatchObject({ state: { status: "cancelled" }, kept: previous });
    expect(result.current.turns[1].state.status).toBe("streaming");
  });

  it("settles the previous turn with its latest state, even one React has not rendered yet", async () => {
    const { result } = renderHook(useThread);
    act(() => result.current.send("First"));
    await act(async () => {
      streams[0].push(frame("result", fullResponse));
      await new Promise((resolve) => setTimeout(resolve, 0)); // the stream applies `result`; act holds the render
      result.current.send("Second"); // the last render still says "streaming"
    });
    expect(result.current.turns[0].state).toEqual({ status: "done", result: fullResponse, requestId: "req-1" });
  });

  it("restores completed turns after a reload, and only those", async () => {
    const first = renderHook(useThread);
    act(() => first.result.current.send("Done one"));
    await complete(first.result, 0);
    act(() => first.result.current.send("Stopped one"));
    act(() => first.result.current.stop());
    first.unmount();

    const { result } = renderHook(useThread);
    expect(result.current.turns).toEqual([{ id: first.result.current.turns[0].id, transcription: "Done one", state: { status: "done", result: fullResponse, requestId: "req-1" } }]);
  });

  it("keeps at most the 20 latest completed turns in session storage", async () => {
    sessionStorage.setItem(KEY, JSON.stringify(Array.from({ length: 20 }, (_, i) => doneTurn(`t${i}`))));
    const { result } = renderHook(useThread);
    expect(result.current.turns).toHaveLength(20);

    act(() => result.current.send("Newest"));
    await complete(result, 0);
    const kept: { id: string; transcription: string }[] = stored();
    expect(kept).toHaveLength(20);
    expect(kept[0].id).toBe("t1");
    expect(kept.at(-1)?.transcription).toBe("Newest");
  });

  it("drops the oldest turns when storage is full, and clears it when nothing fits", async () => {
    const setItem = Storage.prototype.setItem;
    let quota = Infinity;
    const spy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(function (this: Storage, key: string, value: string) {
      if (value.length > quota) throw new DOMException("full", "QuotaExceededError");
      setItem.call(this, key, value);
    });
    const { result } = renderHook(useThread);
    for (const [i, text] of ["One", "Two", "Three"].entries()) {
      act(() => result.current.send(text));
      await complete(result, i);
    }
    expect(stored()).toHaveLength(3);

    const two = JSON.stringify(stored().slice(-2)).length;
    quota = two;
    act(() => result.current.regenerate(result.current.turns[2].id));
    act(() => result.current.stop()); // settles, so the thread is written again
    expect(stored().map((turn: { transcription: string }) => turn.transcription)).toEqual(["Two", "Three"]);

    quota = 0;
    act(() => result.current.send("Four"));
    act(() => result.current.stop());
    expect(sessionStorage.getItem(KEY)).toBeNull();
    spy.mockRestore();
  });

  it("ignores corrupted storage", () => {
    sessionStorage.setItem(KEY, "{not json");
    expect(renderHook(useThread).result.current.turns).toEqual([]);

    sessionStorage.setItem(KEY, JSON.stringify({ turns: [doneTurn("a")] }));
    expect(renderHook(useThread).result.current.turns).toEqual([]);
  });

  it("drops malformed and unfinished turns from storage and keeps the valid ones", () => {
    const malformed = [
      null,
      "turn",
      { id: 1, transcription: "x", state: { status: "done", result: fullResponse } },
      { id: "b", state: { status: "done", result: fullResponse } },
      { id: "c", transcription: "x", state: { status: "streaming", partial: null } },
      { id: "d", transcription: "x", state: { status: "done", result: "not an object" } },
    ];
    sessionStorage.setItem(KEY, JSON.stringify([...malformed, doneTurn("ok")]));
    expect(renderHook(useThread).result.current.turns).toEqual([doneTurn("ok")]);
  });

  describe("lastCall (what the inspector shows): the last call that finished", () => {
    const regenerating = async (result: { current: ReturnType<typeof useThread> }, turnId: string) => {
      act(() => result.current.regenerate(turnId));
      streams[0].push(frame("partial", { seq: 1, breakdown: { project_name: "Fresh" } }));
      await waitFor(() => expect(result.current.turns.find(({ id }) => id === turnId)?.state).toMatchObject({ status: "streaming", partial: { project_name: "Fresh" } }));
    };

    it("is the latest completed estimate; a turn that is still streaming does not count", async () => {
      const { result } = renderHook(useThread);
      expect(result.current.lastCall).toBeUndefined();
      act(() => result.current.send("First"));
      expect(result.current.lastCall).toBeUndefined();
      await complete(result, 0);
      expect(result.current.lastCall).toEqual(result.current.turns[0].state);

      act(() => result.current.send("Second"));
      expect(result.current.lastCall).toEqual(result.current.turns[0].state);
      streams[1].push(frame("result", { ...fullResponse, model: "gpt-4o" }));
      await waitFor(() => expect(result.current.lastCall?.result.model).toBe("gpt-4o"));
    });

    it("stays on the only turn's estimate while that turn regenerates", async () => {
      sessionStorage.setItem(KEY, JSON.stringify([doneTurn("a")]));
      const { result } = renderHook(useThread);
      await regenerating(result, "a");
      expect(result.current.lastCall?.requestId).toBe("req-a");
      streams[0].push(frame("result", { ...fullResponse, model: "gpt-4o" }));
      await waitFor(() => expect(result.current.lastCall).toMatchObject({ result: { model: "gpt-4o" }, requestId: "req-1" }));
    });

    it("stays on the latest turn's estimate while it regenerates, never jumping to an older turn", async () => {
      sessionStorage.setItem(KEY, JSON.stringify([doneTurn("a"), doneTurn("b")]));
      const { result } = renderHook(useThread);
      await regenerating(result, "b");
      expect(result.current.lastCall?.requestId).toBe("req-b");
    });

    it("is the latest stored estimate after a reload, then a regenerated older turn, kept while the next turn streams", async () => {
      sessionStorage.setItem(KEY, JSON.stringify([doneTurn("a"), doneTurn("b")]));
      const { result } = renderHook(useThread);
      expect(result.current.lastCall?.requestId).toBe("req-b");

      await regenerating(result, "a");
      expect(result.current.lastCall?.requestId).toBe("req-b");
      streams[0].push(frame("result", { ...fullResponse, model: "gpt-4o" }));
      await waitFor(() => expect(result.current.lastCall).toMatchObject({ result: { model: "gpt-4o" }, requestId: "req-1" }));

      act(() => result.current.send("Third"));
      expect(result.current.turns.at(-1)?.state.status).toBe("streaming");
      expect(result.current.lastCall).toMatchObject({ result: { model: "gpt-4o" }, requestId: "req-1" }); // a′, not b
    });

    it("keeps the last finished call when a regenerate is stopped", () => {
      sessionStorage.setItem(KEY, JSON.stringify([doneTurn("a"), doneTurn("b")]));
      const { result } = renderHook(useThread);
      act(() => result.current.regenerate("b"));
      act(() => result.current.stop());
      expect(result.current.lastCall?.requestId).toBe("req-b"); // the estimate b kept
      act(() => result.current.regenerate("a"));
      act(() => result.current.stop());
      expect(result.current.lastCall?.requestId).toBe("req-b"); // a's kept estimate is older than b's
    });
  });
});
