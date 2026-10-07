import { afterEach, describe, expect, it, vi } from "vitest";

describe("serverEnv", () => {
  afterEach(() => vi.unstubAllEnvs());
  it("returns the AI service URL without a trailing slash", async () => {
    vi.stubEnv("AI_SERVICE_URL", "http://ai-service:8000/");
    const { serverEnv } = await import("./env");
    expect(serverEnv().AI_SERVICE_URL).toBe("http://ai-service:8000");
  });
  it("accepts a Compose service name and localhost", async () => {
    vi.stubEnv("AI_SERVICE_URL", "http://localhost:8000");
    const { serverEnv } = await import("./env");
    expect(serverEnv().AI_SERVICE_URL).toBe("http://localhost:8000");
  });
  it.each(["ai-service:8000", "localhost:8000", "javascript:alert(1)"])("rejects %s (no http(s) scheme)", async (value) => {
    vi.stubEnv("AI_SERVICE_URL", value);
    const { serverEnv } = await import("./env");
    expect(() => serverEnv()).toThrow(/AI_SERVICE_URL/);
  });
  it("fails loudly when unset", async () => {
    vi.stubEnv("AI_SERVICE_URL", undefined);
    const { serverEnv } = await import("./env");
    expect(() => serverEnv()).toThrow(/AI_SERVICE_URL/);
  });
  it("fails loudly when missing", async () => {
    vi.stubEnv("AI_SERVICE_URL", "");
    const { serverEnv } = await import("./env");
    expect(() => serverEnv()).toThrow(/AI_SERVICE_URL/);
  });
  it("allows the published loopback hosts by default, and when ALLOWED_HOSTS is empty", async () => {
    vi.stubEnv("AI_SERVICE_URL", "http://ai-service:8000");
    const { serverEnv } = await import("./env");
    expect(serverEnv().ALLOWED_HOSTS).toEqual(["localhost:3000", "127.0.0.1:3000"]);
    vi.stubEnv("ALLOWED_HOSTS", "");
    expect(serverEnv().ALLOWED_HOSTS).toEqual(["localhost:3000", "127.0.0.1:3000"]);
  });
  it("reads ALLOWED_HOSTS as a comma-separated, case-insensitive list", async () => {
    vi.stubEnv("AI_SERVICE_URL", "http://ai-service:8000");
    vi.stubEnv("ALLOWED_HOSTS", " Estimator.Internal:8443, localhost:3000 ,");
    const { serverEnv } = await import("./env");
    expect(serverEnv().ALLOWED_HOSTS).toEqual(["estimator.internal:8443", "localhost:3000"]);
  });
  it("fails loudly when ALLOWED_HOSTS names no host", async () => {
    vi.stubEnv("AI_SERVICE_URL", "http://ai-service:8000");
    vi.stubEnv("ALLOWED_HOSTS", " , ");
    const { serverEnv } = await import("./env");
    expect(() => serverEnv()).toThrow(/ALLOWED_HOSTS/);
  });
});
