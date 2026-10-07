// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));

const post = (url: string, body: string, headers: Record<string, string> = {}) =>
  new Request(url, { method: "POST", body, headers: { host: "localhost:3000", ...headers } });

describe("POST /api/estimate/stream", () => {
  beforeEach(() => vi.stubEnv("AI_SERVICE_URL", "http://ai-service:8000"));
  afterEach(() => { vi.unstubAllEnvs(); vi.restoreAllMocks(); });

  it("pipes the upstream SSE body unbuffered and passes the abort signal", async () => {
    const upstreamBody = new ReadableStream({ start(c) { c.enqueue(new TextEncoder().encode("event: status\ndata: {}\n\n")); c.close(); } });
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(upstreamBody, { headers: { "content-type": "text/event-stream" } }));
    const { POST } = await import("./route");
    const req = post("http://web/api/estimate/stream", JSON.stringify({ transcription: "hi" }), { "content-type": "application/json" });
    const res = await POST(req);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://ai-service:8000/api/v1/estimate/stream");
    expect((init as RequestInit).signal).toBe(req.signal);
    expect(res.headers.get("content-type")).toMatch(/text\/event-stream/);
    expect(res.headers.get("cache-control")).toMatch(/no-transform/);
    expect(await res.text()).toContain("event: status");
  });

  it("passes upstream 422 JSON through with its status", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(Response.json({ error: { code: "invalid_request" } }, { status: 422 }));
    const { POST } = await import("./route");
    const res = await POST(post("http://web/api/estimate/stream", "{}"));
    expect(res.status).toBe(422);
    expect((await res.json()).error.code).toBe("invalid_request");
  });

  it("rejects oversized bodies before calling upstream", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    const { POST } = await import("./route");
    const res = await POST(post("http://web/api/estimate/stream", "x".repeat(2_000_001)));
    expect(res.status).toBe(413);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("maps an unreachable AI service to 503 with the project error shape", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("fetch failed"));
    const { POST } = await import("./route");
    const res = await POST(post("http://web/api/estimate/stream", "{}"));
    expect(res.status).toBe(503);
    expect((await res.json()).error.code).toBe("upstream_unavailable");
  });

  it("rejects a request for a foreign Host before calling upstream", async () => {
    vi.spyOn(console, "warn").mockImplementation(() => {});
    const fetchMock = vi.spyOn(globalThis, "fetch");
    const { POST } = await import("./route");
    const res = await POST(post("http://web/api/estimate/stream?refresh=true", "{}", { host: "rebind.attacker.example:3000" }));
    expect(res.status).toBe(403);
    expect((await res.json()).error.code).toBe("forbidden");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it.each([
    ["?refresh=true", "http://ai-service:8000/api/v1/estimate/stream?refresh=true"],
    ["?refresh=true&model=gpt-5&url=http://evil.example", "http://ai-service:8000/api/v1/estimate/stream?refresh=true"],
    ["?refresh=1", "http://ai-service:8000/api/v1/estimate/stream"],
    ["?model=gpt-5", "http://ai-service:8000/api/v1/estimate/stream"],
  ])("forwards only an allowlisted refresh=true from %s", async (query, expected) => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("", { headers: { "content-type": "text/event-stream" } }));
    const { POST } = await import("./route");
    await POST(post(`http://web/api/estimate/stream${query}`, "{}"));
    expect(fetchMock.mock.calls[0][0]).toBe(expected);
  });

  it.each([
    ["?prompt_version=v2&refresh=true", { prompt_version: "v2", refresh: "true" }],
    ["?refresh=true&prompt_version=v2&model=gpt-5", { prompt_version: "v2", refresh: "true" }],
    ["?prompt_version=v1%26refresh%3Dtrue%26model%3Dx", {}], // not a version: dropped, so nothing is smuggled
    ["?prompt_version=../v1&refresh=true", { refresh: "true" }],
    ["?prompt_version=v0", {}],
    ["?prompt_version=v12", { prompt_version: "v12" }],
    ["?prompt_version=", {}],
    ["?foo=1", {}],
    // the choices travel in the JSON body; as query parameters they are not forwarded at all
    ["?project_type=mobile_app&detail_level=detailed&output_format=narrative", {}],
  ])("forwards a valid prompt_version next to refresh from %s, rebuilt from allowlisted keys", async (query, expected) => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("", { headers: { "content-type": "text/event-stream" } }));
    const { POST } = await import("./route");
    await POST(post(`http://web/api/estimate/stream${query}`, "{}"));
    const upstream = new URL(String(fetchMock.mock.calls[0][0]));
    expect(upstream.pathname).toBe("/api/v1/estimate/stream");
    expect(Object.fromEntries(upstream.searchParams)).toEqual(expected);
  });

  it("checks the Host and the origin before forwarding a prompt version", async () => {
    vi.spyOn(console, "warn").mockImplementation(() => {});
    const fetchMock = vi.spyOn(globalThis, "fetch");
    const { POST } = await import("./route");
    const crossSite = await POST(post("http://web/api/estimate/stream?prompt_version=v2", "{}", { "sec-fetch-site": "cross-site", origin: "https://evil.example" }));
    const foreignHost = await POST(post("http://web/api/estimate/stream?prompt_version=v2", "{}", { host: "rebind.attacker.example:3000" }));
    expect([crossSite.status, foreignHost.status]).toEqual([403, 403]);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
