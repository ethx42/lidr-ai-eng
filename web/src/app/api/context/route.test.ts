// @vitest-environment node
import { afterEach, expect, it, vi } from "vitest";

afterEach(() => { vi.unstubAllEnvs(); vi.restoreAllMocks(); });

it("GET /api/context proxies the AI service context endpoint", async () => {
  vi.stubEnv("AI_SERVICE_URL", "http://ai-service:8000");
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(Response.json({ prompt_version: "v4" }));
  const { GET } = await import("./route");
  const res = await GET(new Request("http://web/api/context", { headers: { host: "localhost:3000" } }));
  expect(fetchMock.mock.calls[0][0]).toBe("http://ai-service:8000/api/v1/context");
  expect(await res.json()).toEqual({ prompt_version: "v4" });
});
