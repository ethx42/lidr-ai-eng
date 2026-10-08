import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useSession } from "./use-session";

const created = (id: string) => new Response(JSON.stringify({ session_id: id }), { status: 201 });
const view = (id: string, history_turns = 0) =>
  new Response(
    JSON.stringify({ session_id: id, project_metadata: { project_name: null, assumed_team_size: null, mentioned_technologies: [], agreed_scope: null }, history_turns, max_turns: 6, prompt_version: "v3" }),
    { status: 200 },
  );
const urls = () => vi.mocked(fetch).mock.calls.map(([url, init]) => `${init?.method ?? "GET"} ${String(url)}`);

describe("useSession", () => {
  beforeEach(() => sessionStorage.clear());
  afterEach(() => vi.unstubAllGlobals());

  it("creates a session on load, persists it and loads its view", async () => {
    global.fetch = vi.fn().mockResolvedValueOnce(created("s1")).mockResolvedValueOnce(view("s1"));
    const { result } = renderHook(() => useSession());
    await waitFor(() => expect(result.current.view?.max_turns).toBe(6));
    expect(result.current.sessionId).toBe("s1");
    expect(sessionStorage.getItem("estimator.sessionId")).toBe("s1");
  });

  it("replaces an expired stored session", async () => {
    sessionStorage.setItem("estimator.sessionId", "old");
    global.fetch = vi.fn()
      .mockResolvedValueOnce(new Response("{}", { status: 404 }))
      .mockResolvedValueOnce(created("new"))
      .mockResolvedValueOnce(view("new"));
    const { result } = renderHook(() => useSession());
    await waitFor(() => expect(result.current.sessionId).toBe("new"));
  });

  it("keeps a stored session the AI service still knows", async () => {
    sessionStorage.setItem("estimator.sessionId", "kept");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(view("kept", 3)));
    const { result } = renderHook(() => useSession());
    await waitFor(() => expect(result.current.view?.history_turns).toBe(3));
    expect(result.current.sessionId).toBe("kept");
    expect(urls()).toEqual(["GET /api/sessions/kept"]);
  });

  it("starts a new session on reset, leaving the old one at once", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(created("s1")).mockResolvedValueOnce(view("s1", 2)));
    const { result } = renderHook(() => useSession());
    await waitFor(() => expect(result.current.view?.history_turns).toBe(2));

    let answer!: (res: Response) => void;
    vi.mocked(fetch).mockResolvedValueOnce(created("s2")).mockReturnValueOnce(new Promise((resolve) => (answer = resolve)));
    let reset!: Promise<void>;
    act(() => {
      reset = result.current.reset();
    });
    expect(result.current.sessionId).toBeNull(); // the old conversation is left at once
    expect(result.current.view).toBeNull();
    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalledTimes(4));
    await act(async () => {
      answer(view("s2"));
      await reset;
    });
    expect(result.current.view?.session_id).toBe("s2");
    expect(sessionStorage.getItem("estimator.sessionId")).toBe("s2");
    expect(urls()).toEqual(["POST /api/sessions", "GET /api/sessions/s1", "POST /api/sessions", "GET /api/sessions/s2"]);
  });

  it("reloads the view on refresh, and starts a new session if this one expired since", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(created("s1")).mockResolvedValueOnce(view("s1")));
    const { result } = renderHook(() => useSession());
    await waitFor(() => expect(result.current.view).not.toBeNull());

    vi.mocked(fetch).mockResolvedValueOnce(view("s1", 1));
    await act(() => result.current.refresh());
    expect(result.current.view?.history_turns).toBe(1);

    vi.mocked(fetch).mockResolvedValueOnce(new Response("{}", { status: 404 })).mockResolvedValueOnce(created("s9")).mockResolvedValueOnce(view("s9"));
    await act(() => result.current.refresh());
    expect(result.current.sessionId).toBe("s9");
    expect(result.current.view?.history_turns).toBe(0);
  });

  it("says when no session can be started, and tries again on refresh", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(Response.json({ error: { code: "sessions_full" } }, { status: 503 })));
    const { result } = renderHook(() => useSession());
    await waitFor(() => expect(result.current.failed).toBe(true));
    expect(result.current.sessionId).toBeNull();
    expect(result.current.view).toBeNull();

    vi.mocked(fetch).mockResolvedValueOnce(created("s1")).mockResolvedValueOnce(view("s1"));
    await act(() => result.current.refresh());
    expect(result.current.failed).toBe(false);
    expect(result.current.sessionId).toBe("s1");
  });

  it("treats an unreadable view as a failure, never as a session", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(created("s1")).mockResolvedValueOnce(Response.json({ session_id: "s1", max_turns: "six" })));
    const { result } = renderHook(() => useSession());
    await waitFor(() => expect(result.current.failed).toBe(true));
    expect(result.current.view).toBeNull();
  });

  it("lets only the latest load land: an earlier answer arriving late is ignored", async () => {
    let first!: (res: Response) => void;
    vi.stubGlobal("fetch", vi.fn().mockReturnValueOnce(new Promise((resolve) => (first = resolve))));
    const { result } = renderHook(() => useSession());
    vi.mocked(fetch).mockResolvedValueOnce(created("s2")).mockResolvedValueOnce(view("s2"));
    await act(() => result.current.reset());
    expect(result.current.sessionId).toBe("s2");
    await act(async () => first(created("s1")));
    expect(result.current.sessionId).toBe("s2");
    expect(sessionStorage.getItem("estimator.sessionId")).toBe("s2");
  });
});
