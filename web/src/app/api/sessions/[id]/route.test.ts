// @vitest-environment node
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { GET } from "./route";

const SID = "0b6f3c1e-4d2a-4f8b-9c3e-2a1d5e6f7a8b";
const get = (id: string, headers: Record<string, string> = {}) =>
  GET(new Request(`http://web/api/sessions/${encodeURIComponent(id)}`, { headers: { host: "localhost:3000", ...headers } }), { params: Promise.resolve({ id }) });

beforeEach(() => vi.stubEnv("AI_SERVICE_URL", "http://ai-service:8000"));
afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

it("GETs the session's view from the fixed upstream path and passes it through", async () => {
  const view = { session_id: SID, history_turns: 2, max_turns: 6, prompt_version: "v3", project_metadata: {} };
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(Response.json(view));
  const res = await get(SID, { cookie: "a=b" });
  const [url, init] = fetchMock.mock.calls[0];
  expect(url).toBe(`http://ai-service:8000/sessions/${SID}`);
  expect(init?.method).toBe("GET");
  expect(new Headers(init?.headers).get("cookie")).toBeNull();
  expect(res.status).toBe(200);
  expect(await res.json()).toEqual(view);
});

it.each(["../x", "x", `${SID}/estimate`, `${SID}?a=b`, SID.toUpperCase(), `${SID} `, ""])(
  "answers 404 session_not_found for %j, which is not a session id, before calling upstream",
  async (id) => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    const res = await get(id);
    expect(res.status).toBe(404);
    expect((await res.json()).error.code).toBe("session_not_found");
    expect(fetchMock).not.toHaveBeenCalled();
  },
);

it("passes an expired session's 404 through", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(Response.json({ error: { code: "session_not_found", message: "gone" } }, { status: 404 }));
  expect((await get(SID)).status).toBe(404);
});

it("checks the Host before the id", async () => {
  vi.spyOn(console, "warn").mockImplementation(() => {});
  const fetchMock = vi.spyOn(globalThis, "fetch");
  expect((await get(SID, { host: "rebind.attacker.example:3000" })).status).toBe(403);
  expect((await get("../x", { host: "rebind.attacker.example:3000" })).status).toBe(403);
  expect(fetchMock).not.toHaveBeenCalled();
});
