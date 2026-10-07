import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { type ContextParams, usePromptContext } from "./use-prompt-context";

const PARAMS: ContextParams = { project_type: "web_saas", detail_level: "medium", output_format: "phases_table", prompt_version: "" };
const prompt = (system_prompt: string) => ({ prompt_version: "v1", system_prompt, references: [] });

describe("usePromptContext", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("fetches the context for the given choices, leaving out an empty prompt version", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => Response.json(prompt("Web SaaS prompt")));
    vi.stubGlobal("fetch", fetchMock);
    const { result, rerender } = renderHook((params: ContextParams) => usePromptContext(params), { initialProps: PARAMS });
    expect(result.current).toEqual({ context: undefined, loading: true });
    await waitFor(() => expect(result.current).toEqual({ context: prompt("Web SaaS prompt"), loading: false }));
    expect(fetchMock.mock.calls[0][0]).toBe("/api/context?project_type=web_saas&detail_level=medium&output_format=phases_table");

    rerender({ ...PARAMS, project_type: "mobile_app", prompt_version: "v2" });
    expect(fetchMock.mock.calls[1][0]).toBe("/api/context?project_type=mobile_app&detail_level=medium&output_format=phases_table&prompt_version=v2");
  });

  it("keeps the previous context, marked loading, until the next arrives; an aborted, superseded answer never lands", async () => {
    const pending: { url: string; signal?: AbortSignal | null; resolve: (res: Response) => void }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>((url, init) => new Promise((resolve) => pending.push({ url: String(url), signal: init?.signal, resolve }))),
    );
    const { result, rerender } = renderHook((params: ContextParams) => usePromptContext(params), { initialProps: PARAMS });
    pending[0].resolve(Response.json(prompt("Medium")));
    await waitFor(() => expect(result.current).toEqual({ context: prompt("Medium"), loading: false }));

    rerender({ ...PARAMS, detail_level: "summary" });
    rerender({ ...PARAMS, detail_level: "detailed" });
    expect(pending[1].signal?.aborted).toBe(true);
    expect(result.current).toEqual({ context: prompt("Medium"), loading: true });

    pending[2].resolve(Response.json(prompt("Detailed")));
    await waitFor(() => expect(result.current).toEqual({ context: prompt("Detailed"), loading: false }));
    pending[1].resolve(Response.json(prompt("Summary")));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(result.current.context).toEqual(prompt("Detailed"));
  });

  it("reports an error response or a network failure as no context (null)", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Response.json({ error: { code: "invalid_request" } }, { status: 422 })));
    const failed = renderHook(() => usePromptContext(PARAMS));
    await waitFor(() => expect(failed.result.current).toEqual({ context: null, loading: false }));

    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("Failed to fetch"))));
    const offline = renderHook(() => usePromptContext(PARAMS));
    await waitFor(() => expect(offline.result.current).toEqual({ context: null, loading: false }));
  });
});
