// @vitest-environment node
import { afterEach, expect, it, vi } from "vitest";

afterEach(() => vi.restoreAllMocks());

it("GET /api/health answers ok without calling the AI service", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch");
  const { GET } = await import("./route");
  const res = GET();
  expect(res.status).toBe(200);
  expect(await res.json()).toEqual({ status: "ok" });
  expect(fetchMock).not.toHaveBeenCalled();
});
