import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRef } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ServiceContextProvider } from "@/components/service-context";
import type { components } from "@/lib/ai-service/schema";
import { breakdown, fullResponse } from "@/lib/estimate/fixtures";
import type { StreamState } from "@/lib/estimate/types";
import { InspectorPanel, InspectorSheet } from "./inspector";

type Done = Extract<StreamState, { status: "done" }>;

const reference = (size: string, project_name: string, meeting_summary: string) => ({ size, meeting_summary, estimation: { ...breakdown, project_name } });
const context = {
  prompt_version: "v4",
  system_prompt: 'You estimate software projects.\n<reference index="1" size="small">…</reference>',
  references: [
    reference("small", "Dental clinic website", "Owner: We want a new website with our services."),
    reference("medium", "Gym class booking", "Manager: Members book classes from their phones."),
    reference("large", "Freight marketplace", "CEO: Shippers post loads and carriers bid on them."),
  ],
  chain: ["openai:gpt-4o-mini", "anthropic:claude-haiku-4-5"],
  max_transcription_chars: 50_000,
};
const done: Done = { status: "done", result: fullResponse, requestId: "req-42" };
const withMetrics = (metrics: Partial<components["schemas"]["CallMetrics"]>, provider: Done["result"]["provider"] = "openai"): Done => ({
  ...done,
  result: { ...fullResponse, provider, metrics: { ...fullResponse.metrics, ...metrics } },
});

const serve = (respond: () => Promise<Response>) => vi.stubGlobal("fetch", vi.fn(respond));
const renderPanel = (call?: Done) => {
  const user = userEvent.setup();
  render(
    <ServiceContextProvider>
      <InspectorPanel call={call} />
    </ServiceContextProvider>,
  );
  return user;
};
const showLastCall = async (user: ReturnType<typeof userEvent.setup>) => user.click(screen.getByRole("tab", { name: "Last call" }));
const valueOf = (label: string) => {
  const value = screen.getByText(label, { selector: "dt" }).nextElementSibling;
  if (!(value instanceof HTMLElement)) throw new Error(`no value for ${label}`);
  return value;
};
const closest = (element: Element, selector: string) => {
  const found = element.closest(selector);
  if (!(found instanceof HTMLElement)) throw new Error(`no ${selector} around ${element.textContent}`);
  return found;
};

describe("Inspector, Context tab", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("shows the prompt version and the system prompt, read-only and scrollable, with a Copy button", async () => {
    serve(async () => Response.json(context));
    const user = renderPanel();
    expect(screen.getByRole("complementary", { name: "Inspector" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Context", selected: true })).toBeInTheDocument();

    const prompt = await screen.findByRole("region", { name: "System prompt" });
    expect(prompt.textContent).toBe(context.system_prompt);
    expect(prompt).toHaveAttribute("tabindex", "0"); // keyboard users can scroll it
    expect(prompt).not.toHaveAttribute("contenteditable");
    expect(valueOf("Prompt version")).toHaveTextContent("v4");

    await user.click(screen.getByRole("button", { name: "Copy system prompt" }));
    expect(await navigator.clipboard.readText()).toBe(context.system_prompt);
  });

  it("lists the three reference estimations with their size and meeting summary, each estimation collapsed", async () => {
    serve(async () => Response.json(context));
    renderPanel();
    const items = within(await screen.findByRole("list", { name: "Reference estimations" })).getAllByRole("listitem");
    expect(items).toHaveLength(3);
    expect(items.map((item) => within(item).getByRole("heading", { level: 4 }).textContent)).toEqual(["Dental clinic website", "Gym class booking", "Freight marketplace"]);
    expect(items.map((item) => item.querySelector('[data-slot="badge"]')?.textContent)).toEqual(["small", "medium", "large"]);
    expect(within(items[1]).getByText("Manager: Members book classes from their phones.")).toBeInTheDocument();

    const details = closest(within(items[0]).getByText("Estimation"), "details");
    expect(details).not.toHaveAttribute("open");
    expect(within(details).getByRole("region", { hidden: true, name: "Estimation for Dental clinic website" }).textContent).toBe(
      JSON.stringify(context.references[0].estimation, null, 2),
    );
  });

  it("gives each tab panel, a focusable scroll container, an inset focus ring", async () => {
    serve(async () => Response.json(context));
    const user = renderPanel();
    const inset = "focus-visible:-outline-offset-2!";
    expect(screen.getByRole("tabpanel", { name: "Context" })).toHaveAttribute("tabindex", "0");
    expect(screen.getByRole("tabpanel", { name: "Context" })).toHaveClass(inset);
    await showLastCall(user);
    expect(screen.getByRole("tabpanel", { name: "Last call" })).toHaveClass(inset);
  });

  it("shows skeletons while the context loads", () => {
    serve(() => new Promise<Response>(() => {}));
    renderPanel();
    const panel = screen.getByRole("tabpanel", { name: "Context" });
    expect(panel.querySelector('[aria-busy="true"]')).not.toBeNull();
    expect(panel.querySelectorAll('[data-slot="skeleton"]').length).toBeGreaterThan(0);
  });

  it("says so when the AI service cannot provide its context", async () => {
    serve(async () => Response.json({ error: { code: "upstream_unavailable" } }, { status: 503 }));
    renderPanel();
    expect(await screen.findByText("The prompt and references could not be loaded from the AI service. Reload the page to try again.")).toBeInTheDocument();
  });

  it("treats a context without a readable system prompt as unavailable", async () => {
    serve(async () => Response.json({ ...context, system_prompt: 42 }));
    renderPanel();
    expect(await screen.findByText(/could not be loaded from the AI service/)).toBeInTheDocument();
  });

  it("skips malformed references and shows n/a for an unreadable prompt version", async () => {
    const references = [null, { size: 3, meeting_summary: "Kept: a summary without size or estimation." }, "nope", { size: "small" }];
    serve(async () => Response.json({ ...context, prompt_version: null, references }));
    renderPanel();
    const items = within(await screen.findByRole("list", { name: "Reference estimations" })).getAllByRole("listitem");
    expect(items).toHaveLength(1);
    expect(items[0]).toHaveTextContent("Kept: a summary without size or estimation.");
    expect(within(items[0]).queryByText("Estimation")).not.toBeInTheDocument();
    expect(valueOf("Prompt version")).toHaveTextContent("n/a");
  });
});

describe("Inspector, Last call tab", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("invites the user to run an estimate until one completes", async () => {
    serve(async () => Response.json(context));
    const user = renderPanel();
    await showLastCall(user);
    expect(screen.getByRole("tabpanel", { name: "Last call" })).toHaveTextContent("Run an estimate to see its metrics.");
  });

  it("shows how the last call ran: provider, model, prompt version, tokens, timing, cost, cache and request ID", async () => {
    serve(async () => Response.json(context));
    const user = renderPanel(done);
    await showLastCall(user);
    const panel = screen.getByRole("tabpanel", { name: "Last call" });
    expect(panel).toHaveTextContent("Physiotherapy patient portal");
    const expected = {
      Provider: "OpenAI",
      Model: "gpt-4o-mini",
      "Prompt version": "v1",
      "Input tokens": "5,200",
      "Cached input tokens": "4,096",
      "Output tokens": "1,400",
      Latency: "4,200 ms",
      "Time to first token": "650 ms",
      Cost: "$0.0012",
      "Cache hit": "No",
      "Request ID": "req-42",
    };
    for (const [label, value] of Object.entries(expected)) expect(valueOf(label)).toHaveTextContent(value);
    expect(within(panel).queryByText("Fallback used")).not.toBeInTheDocument();

    await user.click(within(panel).getByRole("button", { name: "Copy request ID" }));
    expect(await navigator.clipboard.readText()).toBe("req-42");
  });

  it("flags a fallback and a cache hit, and shows n/a for an unknown cost and TTFT", async () => {
    serve(async () => Response.json(context));
    const user = renderPanel(withMetrics({ fallback_used: true, cache_hit: true, cost_usd: null, ttft_ms: null }, "anthropic"));
    await showLastCall(user);
    expect(valueOf("Provider")).toHaveTextContent(/^Anthropic\s*Fallback used$/); // provider first, in reading order
    expect(within(valueOf("Provider")).getByText("Fallback used")).toBeInTheDocument();
    expect(valueOf("Cache hit")).toHaveTextContent("Yes");
    expect(valueOf("Cost")).toHaveTextContent("n/a");
    expect(valueOf("Time to first token")).toHaveTextContent("n/a");
  });

  it("never throws on a malformed result, showing n/a for what it cannot read", async () => {
    serve(async () => Response.json(context));
    const result: Done["result"] = JSON.parse('{"provider": 3, "metrics": "fast", "usage": {"input_tokens": "many"}, "breakdown": null}');
    const user = renderPanel({ status: "done", result });
    await showLastCall(user);
    for (const label of ["Provider", "Model", "Prompt version", "Input tokens", "Latency", "Cost", "Cache hit", "Request ID"]) expect(valueOf(label)).toHaveTextContent("n/a");
    expect(screen.queryByRole("button", { name: "Copy request ID" })).not.toBeInTheDocument();
  });
});

// jsdom has no matchMedia: each sheet test sets the viewport, and `resize` fires the query's change listeners.
const viewport = (wide: boolean) => {
  const listeners = new Set<() => void>();
  const query = {
    matches: wide,
    addEventListener: (_type: string, listener: () => void) => listeners.add(listener),
    removeEventListener: (_type: string, listener: () => void) => listeners.delete(listener),
  };
  const matchMedia = vi.fn(() => query);
  vi.stubGlobal("matchMedia", matchMedia);
  const resize = (next: boolean) => {
    query.matches = next;
    for (const listener of listeners) listener();
  };
  return { matchMedia, listeners, resize };
};

// The sheet and the panel as `Chat` renders them; CSS shows one or the other, jsdom renders both.
const Workspace = () => {
  const panelRef = useRef<HTMLElement>(null);
  return (
    <ServiceContextProvider>
      <InspectorSheet call={done} panelRef={panelRef} />
      <InspectorPanel ref={panelRef} call={done} />
    </ServiceContextProvider>
  );
};

describe("Inspector sheet (below 1024 px)", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("opens from a header button as a dialog that traps focus, and returns focus to the button on close", async () => {
    serve(async () => Response.json(context));
    viewport(false);
    const user = userEvent.setup();
    render(<Workspace />);
    const trigger = screen.getByRole("button", { name: "Inspector" });
    expect(trigger).toHaveAttribute("aria-haspopup", "dialog");
    await user.click(trigger);

    const sheet = screen.getByRole("dialog", { name: "Inspector" });
    expect(sheet).toContainElement(document.activeElement as HTMLElement);
    await within(sheet).findByRole("region", { name: "System prompt" });
    for (let i = 0; i < 8; i++) {
      await user.tab();
      expect(sheet).toContainElement(document.activeElement as HTMLElement);
    }
    await user.tab({ shift: true });
    expect(sheet).toContainElement(document.activeElement as HTMLElement);

    await user.click(within(sheet).getByRole("tab", { name: "Last call" }));
    expect(within(sheet).getByRole("tabpanel", { name: "Last call" })).toHaveTextContent("req-42");

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("closes when the viewport widens to 1024 px and moves focus to the panel, not the hidden button", async () => {
    serve(async () => Response.json(context));
    const { matchMedia, listeners, resize } = viewport(false);
    const user = userEvent.setup();
    render(<Workspace />);
    expect(listeners.size).toBe(0); // listens only while the sheet is open
    await user.click(screen.getByRole("button", { name: "Inspector" }));
    expect(matchMedia).toHaveBeenCalledWith("(min-width: 1024px)");

    act(() => resize(false));
    expect(screen.getByRole("dialog", { name: "Inspector" })).toBeInTheDocument();

    act(() => resize(true));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() => expect(screen.getByRole("complementary", { name: "Inspector" })).toHaveFocus());
    expect(listeners.size).toBe(0);
  });
});
