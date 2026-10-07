// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { proxyJson, proxySse } from "./proxy";

const STREAM = "/api/v1/estimate/stream";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

const post = (body: string, headers: HeadersInit = {}, url = "http://web/api/estimate/stream") =>
  new Request(url, { method: "POST", body, headers: { "content-type": "application/json", ...headers } });

const sse = (headers: HeadersInit = {}) =>
  new Response("event: status\ndata: {}\n\n", { headers: { "content-type": "text/event-stream", ...headers } });

const mockFetch = (response: Response = sse()) => vi.spyOn(globalThis, "fetch").mockResolvedValue(response);

const upstreamInit = (fetchMock: ReturnType<typeof mockFetch>) => fetchMock.mock.calls[0][1] ?? {};

describe("proxySse", () => {
  beforeEach(() => vi.stubEnv("AI_SERVICE_URL", "http://ai-service:8000"));
  afterEach(() => { vi.unstubAllEnvs(); vi.restoreAllMocks(); });

  it("targets AI_SERVICE_URL plus the fixed path, whatever the incoming URL", async () => {
    const fetchMock = mockFetch();
    await proxySse(post("{}", {}, "http://evil.example/api/estimate/stream?target=http://169.254.169.254"), STREAM);
    expect(fetchMock.mock.calls[0][0]).toBe("http://ai-service:8000/api/v1/estimate/stream");
  });

  it("forwards the body bytes and only the allowlisted headers", async () => {
    const fetchMock = mockFetch();
    const body = JSON.stringify({ transcription: "Client: we need a booking app" });
    await proxySse(
      post(body, { accept: "text/event-stream", "x-request-id": "req-1", cookie: "session=s", authorization: "Bearer t", "x-forwarded-for": "10.0.0.1", origin: "http://evil.example" }),
      STREAM,
    );
    const init = upstreamInit(fetchMock);
    const headers = new Headers(init.headers);
    expect(init.method).toBe("POST");
    expect([...headers.keys()].sort()).toEqual(["accept", "content-type", "x-request-id"]);
    expect(headers.get("x-request-id")).toBe("req-1");
    expect(await new Response(init.body).text()).toBe(body);
  });

  it.each([
    ["absent", {}],
    ["unsafe", { "x-request-id": "not safe!" }],
  ])("generates a request id when the incoming one is %s", async (_, headers) => {
    const fetchMock = mockFetch();
    await proxySse(post("{}", headers), STREAM);
    expect(new Headers(upstreamInit(fetchMock).headers).get("x-request-id")).toMatch(UUID);
  });

  it("answers with fresh SSE headers and never copies upstream encoding or hop-by-hop headers", async () => {
    mockFetch(sse({ "content-encoding": "gzip", "content-length": "24", "transfer-encoding": "chunked", connection: "keep-alive", "set-cookie": "a=b", "x-request-id": "req-up" }));
    const res = await proxySse(post("{}"), STREAM);
    expect(res.status).toBe(200);
    expect(res.headers.get("content-type")).toBe("text/event-stream; charset=utf-8");
    expect(res.headers.get("cache-control")).toBe("no-cache, no-transform");
    expect(res.headers.get("x-accel-buffering")).toBe("no");
    expect(res.headers.get("x-request-id")).toBe("req-up");
    for (const name of ["content-encoding", "content-length", "transfer-encoding", "connection", "set-cookie"]) expect(res.headers.get(name)).toBeNull();
  });

  it("rejects a declared content-length over the limit without reading the body", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    const req = post("{}", { "content-length": "2000001", "x-request-id": "req-2" });
    const res = await proxySse(req, STREAM);
    expect(res.status).toBe(413);
    expect(req.bodyUsed).toBe(false);
    expect(fetchMock).not.toHaveBeenCalled();
    expect(await res.json()).toEqual({ error: { code: "payload_too_large", message: expect.stringContaining("2000000") }, request_id: "req-2" });
  });

  it("enforces a custom limit on the actual bytes, accepting a body exactly at it", async () => {
    const fetchMock = mockFetch();
    expect((await proxySse(post("é".repeat(5)), STREAM, { maxBodyBytes: 10 })).status).toBe(200);
    expect((await proxySse(post("é".repeat(5) + "x"), STREAM, { maxBodyBytes: 10 })).status).toBe(413);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("returns a bare 499 when the client left before upstream answered", async () => {
    const errorLog = vi.spyOn(console, "error").mockImplementation(() => {});
    const controller = new AbortController();
    const req = new Request("http://web/api/estimate/stream", { method: "POST", body: "{}", signal: controller.signal });
    vi.spyOn(globalThis, "fetch").mockImplementation(async () => {
      controller.abort(new Error("ResponseAborted"));
      throw new Error("ResponseAborted");
    });
    const res = await proxySse(req, STREAM);
    expect(res.status).toBe(499);
    expect(await res.text()).toBe("");
    expect(errorLog).not.toHaveBeenCalled();
  });

  it("logs an unreachable upstream without the request body", async () => {
    const errorLog = vi.spyOn(console, "error").mockImplementation(() => {});
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("fetch failed", { cause: new Error("connect ECONNREFUSED") }));
    const res = await proxySse(post(JSON.stringify({ transcription: "secret client roadmap" }), { "x-request-id": "req-3" }), STREAM);
    expect(res.status).toBe(503);
    expect(res.headers.get("x-request-id")).toBe("req-3");
    expect(await res.json()).toEqual({ error: { code: "upstream_unavailable", message: expect.any(String) }, request_id: "req-3" });
    const logged = JSON.stringify(errorLog.mock.calls);
    expect(logged).toContain("upstream_unavailable");
    expect(logged).toContain("req-3");
    expect(logged).not.toContain("secret client roadmap");
  });

  it("does not disguise unexpected failures as an unreachable upstream", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new RangeError("bug"));
    await expect(proxySse(post("{}"), STREAM)).rejects.toThrow("bug");
  });
});

describe("proxyJson", () => {
  beforeEach(() => vi.stubEnv("AI_SERVICE_URL", "http://ai-service:8000"));
  afterEach(() => { vi.unstubAllEnvs(); vi.restoreAllMocks(); });

  it("GETs the fixed upstream path and passes the JSON through with fresh headers", async () => {
    const fetchMock = mockFetch(Response.json({ prompt_version: "v4" }, { headers: { "x-request-id": "req-up", "set-cookie": "a=b" } }));
    const req = new Request("http://web/api/context?path=/admin", { headers: { cookie: "session=s" } });
    const res = await proxyJson(req, "/api/v1/context");
    const [url, init = {}] = fetchMock.mock.calls[0];
    expect(url).toBe("http://ai-service:8000/api/v1/context");
    expect(init.method).toBe("GET");
    expect(init.body).toBeUndefined();
    expect(init.signal).toBe(req.signal);
    expect(new Headers(init.headers).get("cookie")).toBeNull();
    expect(res.status).toBe(200);
    expect(res.headers.get("content-type")).toBe("application/json");
    expect(res.headers.get("x-request-id")).toBe("req-up");
    expect(res.headers.get("set-cookie")).toBeNull();
    expect(await res.json()).toEqual({ prompt_version: "v4" });
  });

  it("maps an unreachable AI service to 503", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("fetch failed"));
    const res = await proxyJson(new Request("http://web/api/context"), "/api/v1/context");
    expect(res.status).toBe(503);
    expect((await res.json()).error.code).toBe("upstream_unavailable");
  });
});
