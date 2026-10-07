// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const get = (url: string, headers: Record<string, string> = {}) => new Request(url, { headers: { host: "localhost:3000", ...headers } });

describe("GET /api/context", () => {
  beforeEach(() => vi.stubEnv("AI_SERVICE_URL", "http://ai-service:8000"));
  afterEach(() => { vi.unstubAllEnvs(); vi.restoreAllMocks(); });

  it("proxies the AI service context endpoint", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(Response.json({ prompt_version: "v4" }));
    const { GET } = await import("./route");
    const res = await GET(get("http://web/api/context"));
    expect(fetchMock.mock.calls[0][0]).toBe("http://ai-service:8000/api/v1/context");
    expect(await res.json()).toEqual({ prompt_version: "v4" });
  });

  it("forwards the three enums and the prompt version, re-encoded, and drops every other parameter", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(Response.json({}));
    const { GET } = await import("./route");
    await GET(get("http://web/api/context?project_type=mobile_app&detail_level=detailed&output_format=narrative&prompt_version=v2&refresh=true&foo=1"));
    const upstream = new URL(String(fetchMock.mock.calls[0][0]));
    expect(upstream.origin + upstream.pathname).toBe("http://ai-service:8000/api/v1/context");
    expect(Object.fromEntries(upstream.searchParams)).toEqual({ project_type: "mobile_app", detail_level: "detailed", output_format: "narrative", prompt_version: "v2" });

    await GET(get("http://web/api/context?project_type=web_saas%26prompt_version%3D..%2Fv1&prompt_version="));
    expect(Object.fromEntries(new URL(String(fetchMock.mock.calls[1][0])).searchParams)).toEqual({}); // not a project type: dropped, so nothing is smuggled
  });

  // Defence in depth: only values the AI service can accept leave the BFF; anything else is dropped, never forwarded.
  it.each([
    ["?prompt_version=../v1", {}],
    ["?prompt_version=v0", {}],
    ["?prompt_version=V2", {}],
    ["?prompt_version=v2%0A", {}],
    ["?prompt_version=v12", { prompt_version: "v12" }],
    ["?project_type=game&detail_level=Detailed&output_format=narrative%20", {}],
    ["?project_type=internal_tool&detail_level=summary&output_format=line_items", { project_type: "internal_tool", detail_level: "summary", output_format: "line_items" }],
    ["?project_type=data_pipeline&project_type=mobile_app", { project_type: "data_pipeline" }],
  ])("forwards only valid values from %s", async (query, expected) => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(Response.json({}));
    const { GET } = await import("./route");
    await GET(get(`http://web/api/context${query}`));
    expect(Object.fromEntries(new URL(String(fetchMock.mock.calls[0][0])).searchParams)).toEqual(expected);
  });

  it("passes the AI service's 422 for a version it does not have through", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(Response.json({ error: { code: "invalid_request" } }, { status: 422 }));
    const { GET } = await import("./route");
    const res = await GET(get("http://web/api/context?prompt_version=v9"));
    expect(res.status).toBe(422);
  });

  it("rejects a request for a foreign Host before calling upstream", async () => {
    vi.spyOn(console, "warn").mockImplementation(() => {});
    const fetchMock = vi.spyOn(globalThis, "fetch");
    const { GET } = await import("./route");
    const res = await GET(get("http://web/api/context?prompt_version=v2", { host: "rebind.attacker.example:3000" }));
    expect(res.status).toBe(403);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
