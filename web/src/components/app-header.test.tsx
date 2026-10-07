import { render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AppHeader } from "./app-header";
import { ServiceContextProvider } from "./service-context";

const renderWithChain = (chain: string[]) => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json({ prompt_version: "v1", available_versions: ["v1"], system_prompt: "", references: [], chain, max_transcription_chars: 50_000 })));
  render(
    <ServiceContextProvider>
      <AppHeader />
    </ServiceContextProvider>,
  );
};
const chip = async () => (await screen.findByText("Model:")).parentElement;

afterEach(() => vi.unstubAllGlobals());

it("shows the primary provider and model, then each fallback", async () => {
  renderWithChain(["openai:gpt-4o-mini", "anthropic:claude-haiku-4-5"]);
  expect((await chip())?.textContent).toBe("Model:OpenAI gpt-4o-minifalls back toAnthropic claude-haiku-4-5"); // separate elements, read apart
});

it("names a provider once when its model is the provider itself (replay)", async () => {
  renderWithChain(["replay:replay"]);
  expect((await chip())?.textContent).toBe("Model:Replay");
});
