import { render, screen, waitFor } from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ServiceContextProvider, useServiceContext } from "./service-context";

const context = { prompt_version: "v1", available_versions: ["v1", "v2"], system_prompt: "", references: [], chain: ["replay:gpt-4o-mini"], max_transcription_chars: 1200 };

const Probe = () => {
  const value = useServiceContext();
  return <p>{value === undefined ? "loading" : value === null ? "unavailable" : value.max_transcription_chars}</p>;
};

describe("ServiceContextProvider", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("is loading, then provides the context", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Response.json(context)));
    render(<ServiceContextProvider><Probe /></ServiceContextProvider>);
    expect(screen.getByText("loading")).toBeInTheDocument();
    expect(await screen.findByText("1200")).toBeInTheDocument();
  });

  it("is unavailable when the response is an error or malformed", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Response.json({ ...context, max_transcription_chars: "many" })));
    render(<ServiceContextProvider><Probe /></ServiceContextProvider>);
    expect(await screen.findByText("unavailable")).toBeInTheDocument();
  });

  // The form's prompt-version choice relies on both.
  it.each([
    ["no available versions", { available_versions: undefined }],
    ["a version that is not a string", { available_versions: ["v1", 2] }],
    ["no default prompt version", { prompt_version: null }],
  ])("is unavailable with %s", async (_, change) => {
    vi.stubGlobal("fetch", vi.fn(async () => Response.json({ ...context, ...change })));
    render(<ServiceContextProvider><Probe /></ServiceContextProvider>);
    expect(await screen.findByText("unavailable")).toBeInTheDocument();
  });

  it("ignores its own aborted request, so StrictMode's second mount wins", async () => {
    let calls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>((_url, init) =>
        calls++ === 0
          ? new Promise((_resolve, reject) => init?.signal?.addEventListener("abort", () => setTimeout(() => reject(new DOMException("aborted", "AbortError")), 10)))
          : Promise.resolve(Response.json(context)),
      ),
    );
    render(<StrictMode><ServiceContextProvider><Probe /></ServiceContextProvider></StrictMode>);
    expect(await screen.findByText("1200")).toBeInTheDocument();
    await new Promise((resolve) => setTimeout(resolve, 30)); // the aborted request has rejected by now
    await waitFor(() => expect(screen.getByText("1200")).toBeInTheDocument());
  });
});
