// @vitest-environment node
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { POST } from "./route";

const post = (headers: Record<string, string> = {}, body?: string) =>
  new Request("http://web/api/sessions", { method: "POST", body, headers: { host: "localhost:3000", ...headers } });

beforeEach(() => vi.stubEnv("AI_SERVICE_URL", "http://ai-service:8000"));
afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

it("POSTs to the fixed upstream path without a body and passes the 201 JSON through", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(Response.json({ session_id: "s1" }, { status: 201, headers: { "x-request-id": "req-up" } }));
  const req = post({ cookie: "a=b", "content-type": "application/json" }, JSON.stringify({ session_id: "chosen-by-client" }));
  const res = await POST(req);
  const [url, init] = fetchMock.mock.calls[0];
  expect(url).toBe("http://ai-service:8000/sessions");
  expect(init?.method).toBe("POST");
  expect(init?.body).toBeUndefined(); // nothing the client sends reaches the service
  expect([...new Headers(init?.headers).keys()].sort()).toEqual(["accept", "x-request-id"]);
  expect(init?.redirect).toBe("error");
  expect(res.status).toBe(201);
  expect(res.headers.get("content-type")).toBe("application/json");
  expect(res.headers.get("x-request-id")).toBe("req-up");
  expect(await res.json()).toEqual({ session_id: "s1" });
});

it("passes sessions_full through", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(Response.json({ error: { code: "sessions_full", message: "full" } }, { status: 503 }));
  const res = await POST(post());
  expect(res.status).toBe(503);
  expect((await res.json()).error.code).toBe("sessions_full");
});

it("refuses a cross-site POST", async () => {
  vi.spyOn(console, "warn").mockImplementation(() => {});
  const fetchMock = vi.spyOn(globalThis, "fetch");
  expect((await POST(post({ "sec-fetch-site": "cross-site", origin: "https://evil.example" }))).status).toBe(403);
  expect(fetchMock).not.toHaveBeenCalled();
});
