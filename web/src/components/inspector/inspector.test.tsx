import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { components } from "@/lib/ai-service/schema";
import { breakdown, fullResponse } from "@/lib/estimate/fixtures";
import type { StreamState } from "@/lib/estimate/types";
import { InspectorSheet } from "./inspector";
import { type ContextParams, usePromptContext } from "./use-prompt-context";

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
  available_versions: ["v4"],
};
const PARAMS = { project_type: "web_saas", detail_level: "medium", output_format: "phases_table", prompt_version: "" } as const;
const done: Done = { status: "done", result: fullResponse, requestId: "req-42" };
const withMetrics = (metrics: Partial<components["schemas"]["CallMetrics"]>, provider: Done["result"]["provider"] = "openai"): Done => ({
  ...done,
  result: { ...fullResponse, provider, metrics: { ...fullResponse.metrics, ...metrics } },
});

const serve = (respond: () => Promise<Response>) => vi.stubGlobal("fetch", vi.fn(respond));
// The inspector as the workspace renders it: a header button opens it as a sheet at every width, and its Context tab
// shows the prompt for the given choices.
const Panel = ({ call, params = PARAMS }: { call?: Done; params?: ContextParams }) => <InspectorSheet call={call} context={usePromptContext(params)} />;
const open = async (user: ReturnType<typeof userEvent.setup>) => {
  await user.click(screen.getByRole("button", { name: "Inspector" }));
  return screen.getByRole("dialog", { name: "Inspector" });
};
const renderPanel = async (call?: Done) => {
  const user = userEvent.setup();
  render(<Panel call={call} />);
  await open(user);
  return user;
};
const showLastCall = async (user: ReturnType<typeof userEvent.setup>) => user.click(screen.getByRole("tab", { name: "Last call" }));
const valueOf = (label: string) => {
  const value = screen.getByText(label, { selector: "dt" }).nextElementSibling;
  if (!(value instanceof HTMLElement)) throw new Error(`no value for ${label}`);
  return value;
};
// The inline context error, found by its text: it is no live region (spec §8 allows only polite status announcements).
const contextError = async (text: string) => closest(await screen.findByText(text), '[data-slot="alert"]');
const closest = (element: Element, selector: string) => {
  const found = element.closest(selector);
  if (!(found instanceof HTMLElement)) throw new Error(`no ${selector} around ${element.textContent}`);
  return found;
};

describe("Inspector, Context tab", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("shows the prompt version and the system prompt, read-only and scrollable, with a Copy button", async () => {
    serve(async () => Response.json(context));
    const user = await renderPanel();
    expect(screen.getByRole("dialog", { name: "Inspector" })).toBeInTheDocument();
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
    await renderPanel();
    const items = within(await screen.findByRole("list", { name: "Reference estimations" })).getAllByRole("listitem");
    expect(items).toHaveLength(3);
    expect(items.map((item) => within(item).getByRole("heading", { level: 4 }).textContent)).toEqual(["Dental clinic website", "Gym class booking", "Freight marketplace"]);
    expect(items.map((item) => item.querySelector('[data-slot="badge"]')?.textContent)).toEqual(["small", "medium", "large"]);
    // secondary to the estimate in the main column: smaller and muted, never the Summary's size and colour
    expect(within(items[1]).getByText("Manager: Members book classes from their phones.")).toHaveClass("text-xs", "text-muted-foreground");

    const details = closest(within(items[0]).getByText("Estimation"), "details");
    expect(details).not.toHaveAttribute("open");
    expect(within(details).getByRole("region", { hidden: true, name: "Estimation for Dental clinic website" }).textContent).toBe(
      JSON.stringify(context.references[0].estimation, null, 2),
    );
  });

  it("gives each tab panel, a focusable scroll container, an inset focus ring", async () => {
    serve(async () => Response.json(context));
    const user = await renderPanel();
    const inset = "focus-visible:-outline-offset-2!";
    expect(screen.getByRole("tabpanel", { name: "Context" })).toHaveAttribute("tabindex", "0");
    expect(screen.getByRole("tabpanel", { name: "Context" })).toHaveClass(inset);
    await showLastCall(user);
    expect(screen.getByRole("tabpanel", { name: "Last call" })).toHaveClass(inset);
  });

  // Dimmed to 60 %, muted text fell to 2.6:1 (WCAG 1.4.3 asks 4.5:1).
  it("keeps the shown prompt, busy but at full contrast, while the prompt for new choices loads, saying it is updating", async () => {
    render(<InspectorSheet context={{ context, loading: true, failed: false, retry: () => {} }} />);
    await open(userEvent.setup());
    const busy = screen.getByRole("region", { name: "System prompt" }).closest('[aria-busy="true"]');
    if (!(busy instanceof HTMLElement)) throw new Error("the shown prompt is not marked busy");
    const dimmed = [busy, ...busy.querySelectorAll("*")].filter((element) => [...element.classList].some((name) => name.startsWith("opacity-")));
    expect(dimmed).toEqual([]);
    expect(valueOf("Prompt version")).toHaveTextContent("Updating…");
    expect(valueOf("Prompt version")).not.toHaveTextContent("v4"); // the version for the new choices is not known yet
  });

  it("shows skeletons while the context loads", async () => {
    serve(() => new Promise<Response>(() => {}));
    await renderPanel();
    const panel = screen.getByRole("tabpanel", { name: "Context" });
    expect(panel.querySelector('[aria-busy="true"]')).not.toBeNull();
    expect(panel.querySelectorAll('[data-slot="skeleton"]').length).toBeGreaterThan(0);
  });

  // Never "reload the page": the estimate on screen lives only in React state.
  it("says so when the AI service cannot provide its context, and offers to try again", async () => {
    const answers = [Response.json({ error: { code: "upstream_unavailable" } }, { status: 503 }), Response.json(context)];
    serve(async () => answers.shift() ?? Response.error());
    const user = await renderPanel();
    const error = await contextError("The prompt and references could not be loaded from the AI service.");
    expect(error).not.toHaveAttribute("role");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByRole("tabpanel", { name: "Context" })).not.toHaveTextContent(/reload/i);

    await user.click(within(error).getByRole("button", { name: "Retry" }));
    expect(screen.getByRole("tabpanel", { name: "Context" })).toHaveFocus(); // the button is gone; focus stays in the panel
    expect(await screen.findByRole("region", { name: "System prompt" })).toHaveTextContent("You estimate software projects.");
    expect(screen.queryByText(/could not be loaded/)).not.toBeInTheDocument();
  });

  it("keeps the last good prompt when the prompt for new choices fails to load, with an inline error and Retry", async () => {
    const answers = [Response.json(context), Response.json({ error: { code: "upstream_unavailable" } }, { status: 503 }), Response.json({ ...context, prompt_version: "v5" })];
    serve(async () => answers.shift() ?? Response.error());
    const user = userEvent.setup();
    const { rerender } = render(<Panel />);
    await open(user);
    await screen.findByRole("region", { name: "System prompt" });

    rerender(<Panel params={{ ...PARAMS, detail_level: "detailed" }} />);
    const error = await contextError("Could not load the prompt for these choices.");
    expect(error).toHaveTextContent("The prompt below is for your previous choices.");
    // not assertive: with the AI service down, each choice (arrow presses included) would interrupt from the inspector
    expect(error).not.toHaveAttribute("role");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByRole("region", { name: "System prompt" }).textContent).toBe(context.system_prompt); // the last good one
    expect(screen.getByRole("tabpanel", { name: "Context" })).not.toHaveTextContent(/reload/i);

    await user.click(within(error).getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(valueOf("Prompt version")).toHaveTextContent("v5"));
    expect(screen.queryByText("Could not load the prompt for these choices.")).not.toBeInTheDocument();
  });

  it("treats a context without a readable system prompt as unavailable, and shows a retry as busy until it answers", async () => {
    const unreadable = () => Response.json({ ...context, system_prompt: 42 });
    let answer!: (res: Response) => void;
    const answers = [Promise.resolve(unreadable()), new Promise<Response>((resolve) => (answer = resolve))];
    serve(() => answers.shift() ?? Promise.resolve(Response.error()));
    const user = await renderPanel();
    const error = await contextError("The prompt and references could not be loaded from the AI service.");
    expect(error).not.toHaveAttribute("aria-busy", "true");

    await user.click(within(error).getByRole("button", { name: "Retry" }));
    expect(error).toHaveAttribute("aria-busy", "true");
    // still focusable (it does not drop focus), but announced as unavailable while it does nothing
    const updating = within(error).getByRole("button", { name: "Updating…" });
    expect(updating).toHaveAttribute("aria-disabled", "true");
    expect(updating).not.toBeDisabled();
    await act(async () => answer(unreadable()));
    expect(error).toHaveAttribute("aria-busy", "false");
    expect(within(error).getByRole("button", { name: "Retry" })).not.toHaveAttribute("aria-disabled", "true");
  });

  it("skips malformed references and shows n/a for an unreadable prompt version", async () => {
    const references = [null, { size: 3, meeting_summary: "Kept: a summary without size or estimation." }, "nope", { size: "small" }];
    serve(async () => Response.json({ ...context, prompt_version: null, references }));
    await renderPanel();
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
    const user = await renderPanel();
    await showLastCall(user);
    expect(screen.getByRole("tabpanel", { name: "Last call" })).toHaveTextContent("Run an estimate to see its metrics.");
  });

  it("shows how the last call ran: provider, model, prompt version, tokens, timing, cost, cache and request ID", async () => {
    serve(async () => Response.json(context));
    const user = await renderPanel(done);
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

  // A UUID next to its label and Copy did not fit the 352 px panel, and break-all split it mid-value.
  it("stacks the request ID under its label, full width and never broken mid-value when it fits", async () => {
    serve(async () => Response.json(context));
    const user = await renderPanel(done);
    await showLastCall(user);
    const label = screen.getByText("Request ID", { selector: "dt" });
    expect(closest(label, "div")).toHaveClass("flex-col");
    const code = within(valueOf("Request ID")).getByText("req-42");
    expect(code).not.toHaveClass("break-all");
    expect(code).toHaveClass("wrap-anywhere"); // only a value wider than the panel wraps
  });

  it("flags a fallback and a cache hit, and shows n/a for an unknown cost and TTFT", async () => {
    serve(async () => Response.json(context));
    const user = await renderPanel(withMetrics({ fallback_used: true, cache_hit: true, cost_usd: null, ttft_ms: null }, "anthropic"));
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
    const user = await renderPanel({ status: "done", result });
    await showLastCall(user);
    for (const label of ["Provider", "Model", "Prompt version", "Input tokens", "Latency", "Cost", "Cache hit", "Request ID"]) expect(valueOf(label)).toHaveTextContent("n/a");
    expect(screen.queryByRole("button", { name: "Copy request ID" })).not.toBeInTheDocument();
  });
});

describe("Inspector sheet", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("opens from a header button as a dialog that traps focus, and returns focus to the button on close", async () => {
    serve(async () => Response.json(context));
    const user = userEvent.setup();
    render(<Panel call={done} />);
    const trigger = screen.getByRole("button", { name: "Inspector" });
    expect(trigger).toHaveAttribute("aria-haspopup", "dialog");
    expect(trigger).not.toHaveClass("lg:hidden"); // the sheet is the inspector at every width: the right column holds the memory
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
});
