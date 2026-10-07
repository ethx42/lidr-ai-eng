import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ServiceContextProvider } from "@/components/service-context";
import { fullResponse } from "@/lib/estimate/fixtures";
import type { PartialBreakdown, StreamState } from "@/lib/estimate/types";
import type { Sample } from "@/lib/samples";
import { stubPointer } from "@/test/pointer";
import { Workspace, quotesOf } from "./workspace";

const SAMPLES: Sample[] = [
  { id: "clinic-portal", title: "Clinic portal", description: "Patient portal, medium scope", text: "Sofía: We have three physiotherapy clinics." },
];
// Holds the fixture's R1 and R2 quotes; R3's is not in it (the fixture's grounding report flags R3).
const TRANSCRIPT = [
  "Sofía: We want a web portal where patients log in, see their upcoming appointments, and download invoices as PDF.",
  "Sofía: Yes, patients should be able to book a new session with their physiotherapist, and cancel up to 24 hours before.",
].join("\n");
const context = {
  prompt_version: "v1",
  available_versions: ["v1", "v2"],
  system_prompt: "You estimate software projects.",
  references: [],
  chain: ["replay:gpt-4o-mini"],
  max_transcription_chars: 50_000,
};
const tooLong = { error: { code: "invalid_request", message: "Transcription exceeds 50000 characters.", details: [{ type: "string_too_long" }] }, request_id: "req-422" };
const DEFAULTS = { project_type: "web_saas", detail_level: "medium", output_format: "phases_table" };

const encoder = new TextEncoder();
const frame = (event: string, data: unknown) => encoder.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
// One SSE body per request, fed by the test; aborting the request errors it, as a real fetch body does.
const sseBody = (signal?: AbortSignal | null) => {
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({ start: (c) => { controller = c; } });
  signal?.addEventListener("abort", () => controller.error(new DOMException("aborted", "AbortError")));
  return { body, push: (chunk: Uint8Array) => controller.enqueue(chunk) };
};

describe("Workspace", () => {
  let streams: ReturnType<typeof sseBody>[];
  let respond: ((init?: RequestInit) => Response) | undefined;
  let serviceContext: Promise<Response> | undefined;

  beforeEach(() => {
    streams = [];
    respond = undefined;
    serviceContext = undefined;
    stubPointer("fine");
    vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} }); // not in jsdom
    // jsdom lays everything out at 0×0 on the origin, where user-event also points, so react-resizable-panels' document
    // pointerdown would take every click for a grab of the split's handle (focusing it, preventing the default). The
    // split sits far from the pointer here, as its handle does in a browser.
    const rect = Element.prototype.getBoundingClientRect;
    vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (this: Element) {
      return this.matches("[data-group], [data-panel], [data-separator]") ? new DOMRect(10_000, 10_000, 100, 100) : rect.call(this);
    });
    Object.defineProperty(HTMLElement.prototype, "scrollTo", { value: vi.fn(), configurable: true });
    Object.defineProperty(Element.prototype, "scrollIntoView", { value: vi.fn(), configurable: true });
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async (url, init) => {
        const path = String(url);
        if (path === "/api/context") return serviceContext ?? Response.json(context);
        if (path.startsWith("/api/context")) return Response.json(context);
        if (respond) return respond(init);
        const stream = sseBody(init?.signal);
        streams.push(stream);
        return new Response(stream.body, { headers: { "content-type": "text/event-stream", "x-request-id": `req-${streams.length}` } });
      }),
    );
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    Reflect.deleteProperty(HTMLElement.prototype, "scrollTo");
    Reflect.deleteProperty(Element.prototype, "scrollIntoView");
  });

  const setup = () => {
    const user = userEvent.setup();
    render(
      <ServiceContextProvider>
        <Workspace samples={SAMPLES} />
      </ServiceContextProvider>,
    );
    return { user, input: screen.getByRole("textbox", { name: "Transcript" }), estimate: screen.getByRole("button", { name: "Estimate" }) };
  };
  const estimateCalls = () => vi.mocked(fetch).mock.calls.filter(([url]) => String(url).startsWith("/api/estimate"));
  const sent = (call: number) => ({ url: String(estimateCalls()[call][0]), body: JSON.parse(String(estimateCalls()[call][1]?.body)) });
  const loaded = () => screen.findByText("Model:"); // the header shows the service context
  const run = async (user: ReturnType<typeof userEvent.setup>, input: HTMLElement, text = TRANSCRIPT) => {
    await loaded();
    const before = estimateCalls().length;
    await user.type(input, text);
    await user.click(screen.getByRole("button", { name: "Estimate" }));
    await waitFor(() => expect(estimateCalls()).toHaveLength(before + 1));
  };
  const finish = async (stream: number, result: unknown = fullResponse) => {
    streams[stream].push(frame("result", result));
    await screen.findByRole("button", { name: "Copy as markdown" });
  };
  const inspector = () => screen.getByRole("complementary", { name: "Inspector" });
  const lastCall = async (user: ReturnType<typeof userEvent.setup>) => {
    await user.click(within(inspector()).getByRole("tab", { name: "Last call" }));
    return within(inspector()).getByRole("tabpanel", { name: "Last call" });
  };
  const transcriptPane = () => screen.getByRole("region", { name: "Submitted transcript" });
  const runStatus = () => {
    const region = document.querySelector('[data-slot="run-status"]');
    if (!(region instanceof HTMLElement)) throw new Error("no run status region");
    return region;
  };
  // A viewport whose width the test changes mid-run: the split-view query answers `wide`, change listeners fire.
  const viewport = (initiallyWide: boolean) => {
    let wide = initiallyWide;
    const listeners = new Set<() => void>();
    vi.stubGlobal(
      "matchMedia",
      vi.fn((query: string) => ({
        matches: query === "(pointer: fine)" || (query === "(min-width: 48rem)" && wide),
        media: query,
        addEventListener: (_type: string, listener: () => void) => listeners.add(listener),
        removeEventListener: (_type: string, listener: () => void) => listeners.delete(listener),
      })),
    );
    return (next: boolean) =>
      act(() => {
        wide = next;
        for (const listener of listeners) listener();
      });
  };
  const mark = (id: string) => transcriptPane().querySelector(`mark[data-req="${id}"]`);

  it("invites a first estimate until one runs", () => {
    setup();
    expect(screen.getByText("Your estimate appears here")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Submitted transcript" })).not.toBeInTheDocument();
  });

  it("submits the typed form and streams the estimate beside the submitted transcript", async () => {
    const { user, input, estimate } = setup();
    await loaded();
    await user.type(input, "We need a booking portal.");
    await user.click(screen.getByRole("radio", { name: "Mobile app" }));
    await user.click(estimate);

    expect(await screen.findByRole("button", { name: "Stop" })).toBeInTheDocument();
    expect(sent(0)).toEqual({ url: "/api/estimate/stream?prompt_version=v1", body: { ...DEFAULTS, project_type: "mobile_app", transcription: "We need a booking portal." } });
    expect(transcriptPane()).toHaveTextContent("We need a booking portal.");
    expect(screen.getByText("Mobile app, medium detail, phases table, prompt v1")).toBeInTheDocument();
    expect(input).toHaveValue("We need a booking portal."); // the form keeps the transcript for the next run
    expect(estimate).toHaveFocus(); // a mouse keeps focus where it was
    expect(screen.getByRole("separator", { name: "Resize the transcript and the estimate" })).toHaveAttribute("tabindex", "0");
    // side by side there are no tabs: each pane is a group named by its heading
    expect(screen.queryByRole("tablist", { name: "Result" })).not.toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Transcript" })).toContainElement(transcriptPane());
    expect(screen.getByRole("group", { name: "Estimate" })).toContainElement(screen.getByRole("button", { name: "Stop" }));
  });

  it("highlights each grounded quote in the transcript, and the one behind the hovered or focused requirement", async () => {
    const { user, input } = setup();
    await run(user, input);
    // R1's quote is complete once R2 has started; R2's, cut short, would match R1's sentence ("patients log in")
    streams[0].push(frame("partial", { seq: 1, breakdown: { requirements: [{ id: "R1", evidence: "patients log in, see their" }, { id: "R2", evidence: "patients" }] } }));
    await waitFor(() => expect(mark("R1")).toHaveTextContent("patients log in, see their")); // marks follow the stream
    expect(transcriptPane().querySelector('mark[data-req~="R2"]')).toBeNull();

    await finish(0);
    expect(runStatus()).toBeEmptyDOMElement(); // the visible estimate announces itself; no second announcement
    expect(mark("R1")).toHaveTextContent("We want a web portal where patients log in, see their upcoming appointments, and download invoices as PDF"); // edge punctuation trimmed, as the server does
    expect(mark("R2")).toBeInTheDocument();
    expect(mark("R3")).toBeNull(); // ungrounded: ⚠ beside the requirement, no mark
    expect(screen.getByText("Quote not found in the transcript")).toBeInTheDocument();

    await user.hover(screen.getByText("Patients log in and see their upcoming appointments."));
    expect(mark("R1")).toHaveAttribute("data-active");
    await user.unhover(screen.getByText("Patients log in and see their upcoming appointments."));
    expect(mark("R1")).not.toHaveAttribute("data-active");
    act(() => screen.getByRole("button", { name: "Evidence for R2" }).focus());
    expect(mark("R2")).toHaveAttribute("data-active");
  });

  it("follows the server's grounding report once the result arrives: a flagged quote gets ⚠ and no mark, even if found here", async () => {
    const { user, input } = setup();
    await run(user, input);
    await finish(0, { ...fullResponse, grounding: { ...fullResponse.grounding, ungrounded_requirement_ids: ["R1", "R3"] } });
    expect(mark("R1")).toBeNull();
    expect(mark("R2")).toBeInTheDocument();
    expect(screen.getAllByText("Quote not found in the transcript")).toHaveLength(2);
  });

  // §8 managed focus on a touch screen: never the transcript (the keyboard would cover the result), but the new Stop.
  it("on a touch screen, moves focus from Estimate to the new Stop without scrolling, never into the transcript", async () => {
    stubPointer("coarse");
    const { user, input, estimate } = setup();
    await loaded();
    await user.type(input, "We need a booking portal.");
    const focus = vi.spyOn(HTMLElement.prototype, "focus");
    await user.click(estimate);
    const stop = await screen.findByRole("button", { name: "Stop" });
    await waitFor(() => expect(stop).toHaveFocus());
    expect(focus.mock.contexts.at(-1)).toBe(stop);
    expect(focus).toHaveBeenLastCalledWith({ preventScroll: true });
    expect(input).not.toHaveFocus();
    focus.mockRestore();
  });

  it("on a touch screen, Edit transcript still moves focus into the transcript (the user asked to edit it)", async () => {
    stubPointer("coarse");
    respond = () => Response.json(tooLong, { status: 422 });
    const { user, input } = setup();
    await run(user, input, "A very long transcript");
    await user.click(await screen.findByRole("button", { name: "Edit transcript" }));
    expect(input).toHaveValue("A very long transcript");
    expect(input).toHaveFocus();
  });

  it("puts a rejected transcript back from the error card, asking first if the draft changed since", async () => {
    respond = () => Response.json(tooLong, { status: 422 });
    const { user, input } = setup();
    await loaded();
    await user.type(input, "A very long transcript");
    await user.keyboard("{Control>}{Enter}{/Control}");
    await user.click(await screen.findByRole("button", { name: "Edit transcript" }));
    expect(input).toHaveValue("A very long transcript");
    expect(input).toHaveFocus();

    await user.clear(input);
    await user.type(input, "Something else");
    await user.click(screen.getByRole("button", { name: "Edit transcript" }));
    expect(screen.getByRole("group", { name: "Replace your draft with the transcript to shorten?" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Keep my draft" })).toHaveFocus());
    expect(input).toHaveValue("Something else");
  });

  it("keeps focus in the transcript after Cmd+Enter, so Esc stops the stream from there", async () => {
    const { user, input } = setup();
    await loaded();
    await user.type(input, "We need a booking portal.");
    await user.keyboard("{Meta>}{Enter}{/Meta}");
    await screen.findByRole("button", { name: "Stop" });
    expect(input).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(await screen.findByText("Stopped")).toBeInTheDocument();
    expect(estimateCalls()[0][1]?.signal?.aborted).toBe(true);
  });

  it("shows the last completed call in the inspector; a run that is streaming or stopped does not replace it", async () => {
    const { user, input, estimate } = setup();
    expect(screen.getByRole("button", { name: "Inspector" })).toHaveAttribute("aria-haspopup", "dialog"); // the sheet below 1024 px
    expect(await lastCall(user)).toHaveTextContent("Run an estimate to see its metrics.");

    await run(user, input);
    expect(await lastCall(user)).toHaveTextContent("Run an estimate to see its metrics."); // still streaming
    await finish(0);
    expect(await within(await lastCall(user)).findByText("req-1")).toBeInTheDocument();
    expect(await lastCall(user)).toHaveTextContent("Physiotherapy patient portal");

    await user.click(estimate);
    await screen.findByRole("button", { name: "Stop" });
    await user.click(screen.getByRole("button", { name: "Stop" }));
    await user.click(screen.getByRole("button", { name: "Regenerate" }));
    await user.click(await screen.findByRole("button", { name: "Stop" }));
    expect(await lastCall(user)).toHaveTextContent("req-1");

    await user.click(screen.getByRole("button", { name: "Regenerate" }));
    await finish(3, { ...fullResponse, model: "gpt-4o" });
    expect(within(await lastCall(user)).getByText("req-4")).toBeInTheDocument();
  });

  it("counts the inspector's last call from the latest result, even one React has not rendered yet", async () => {
    const { user, input, estimate } = setup();
    await run(user, input);
    await act(async () => {
      streams[0].push(frame("result", fullResponse));
      await new Promise((resolve) => setTimeout(resolve, 0)); // the stream applies `result`; act holds the render
      fireEvent.click(estimate); // the last render still says "streaming"
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    await waitFor(() => expect(estimateCalls()).toHaveLength(2));
    expect(within(await lastCall(user)).getByText("req-1")).toBeInTheDocument();
  });

  it("regenerates with the run's own transcript, choices and prompt version, skipping the cache, whatever the form says now", async () => {
    const { user, input } = setup();
    await loaded();
    await user.click(screen.getByRole("button", { name: "Advanced" }));
    await user.selectOptions(screen.getByRole("combobox", { name: "Prompt version" }), "v2");
    await run(user, input, "First transcript");
    await finish(0);

    await user.type(input, " edited");
    await user.click(screen.getByRole("radio", { name: "Narrative" }));
    await user.selectOptions(screen.getByRole("combobox", { name: "Prompt version" }), "v1");
    await user.click(screen.getByRole("button", { name: "Regenerate" }));
    expect(sent(1)).toEqual({ url: "/api/estimate/stream?prompt_version=v2&refresh=true", body: { ...DEFAULTS, transcription: "First transcript" } });
  });

  it("keeps the previous estimate when a regenerate is stopped, and through repeated stopped regenerates", async () => {
    const { user, input } = setup();
    await run(user, input);
    await finish(0, { ...fullResponse, estimation: "# Previous estimate" });

    const scroller = screen.getByRole("article").closest(".overflow-y-auto");
    if (!scroller) throw new Error("no result scroller");
    scroller.scrollTop = 300;
    await user.click(screen.getByRole("button", { name: "Regenerate" }));
    expect(scroller.scrollTop).toBe(0); // the new attempt streams in from the top
    streams[1].push(frame("partial", { seq: 1, breakdown: { project_name: "Fresh attempt" } }));
    expect(await screen.findByRole("heading", { level: 2, name: "Fresh attempt" })).toBeInTheDocument(); // the new attempt is what streams
    await user.click(screen.getByRole("button", { name: "Stop" }));
    expect(screen.getByText("Stopped — kept the previous estimate")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Physiotherapy patient portal" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Regenerate" }));
    await user.click(await screen.findByRole("button", { name: "Stop" }));
    await user.click(screen.getByRole("button", { name: "Copy as markdown" }));
    expect(await navigator.clipboard.readText()).toBe("# Previous estimate");
  });

  it("keeps the previous estimate below the error card when a regenerate fails", async () => {
    const { user, input } = setup();
    await run(user, input);
    await finish(0);
    await user.click(screen.getByRole("button", { name: "Regenerate" }));
    streams[1].push(frame("error", { code: "upstream_unavailable", message: "down", retryable: true, request_id: "req-9" }));
    const card = await screen.findByRole("alert");
    expect(card).toHaveTextContent("The previous estimate is kept below.");
    expect(screen.getByRole("heading", { level: 2, name: "Physiotherapy patient portal" })).toBeInTheDocument();
    expect(mark("R1")).toBeInTheDocument(); // the kept estimate's quotes stay marked
  });

  it("stops a streaming run when a new estimate is submitted, and shows the new one", async () => {
    const { user, input, estimate } = setup();
    await run(user, input, "First");
    streams[0].push(frame("partial", { seq: 1, breakdown: { project_name: "First" } }));
    await screen.findByRole("heading", { level: 2, name: "First" });
    await user.clear(input);
    await user.type(input, "Second");
    await user.click(estimate);
    await waitFor(() => expect(estimateCalls()).toHaveLength(2));
    expect(estimateCalls()[0][1]?.signal?.aborted).toBe(true);
    expect(transcriptPane()).toHaveTextContent("Second");
    expect(screen.queryByRole("heading", { level: 2, name: "First" })).not.toBeInTheDocument();
  });

  it("switches between the structured view and the server's document once a result exists, and back for each new run", async () => {
    const narrative = "## Estimation: Booking\n\n**Backend** — 3 tasks, 120.0 h expected (90.0–170.0 h). T3 Booking API: slot checks.\n";
    const phases = "## Estimation: Booking\n\n| Phase | Tasks | Expected h | Range h |\n|---|---:|---:|---|\n| backend | 3 | 120.0 | 90.0–170.0 |\n";
    const { user, input, estimate } = setup();
    await run(user, input);
    expect(screen.queryByRole("radiogroup", { name: "Result view" })).not.toBeInTheDocument(); // nothing to show as a document yet
    await finish(0, { ...fullResponse, estimation: narrative });

    const structured = screen.getByRole("radio", { name: "Structured" });
    expect(structured).toBeChecked();
    const scroller = screen.getByRole("article").closest(".overflow-y-auto");
    if (!scroller) throw new Error("no result scroller");
    scroller.scrollTop = 300;
    await user.click(screen.getByRole("radio", { name: "Document" }));
    expect(scroller.scrollTop).toBe(0); // each view starts at its top
    const prose = screen.getByText(/3 tasks, 120\.0 h expected/);
    expect(prose.tagName).toBe("P");
    expect(within(prose).getByText("Backend").tagName).toBe("STRONG");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByText("Summary", { selector: "h3" })).not.toBeInTheDocument(); // not the structured view

    await user.click(estimate);
    await finish(1, { ...fullResponse, estimation: phases });
    expect(screen.getByRole("radio", { name: "Structured" })).toBeChecked();
    await user.click(screen.getByRole("radio", { name: "Document" }));
    const table = screen.getByRole("table");
    expect(within(table).getAllByRole("columnheader").map((cell) => cell.textContent)).toEqual(["Phase", "Tasks", "Expected h", "Range h"]);
    expect(within(table).getByRole("cell", { name: "120.0" })).toHaveStyle({ textAlign: "right" });
  });

  it("shows the inspector the prompt the form's current choices would use", async () => {
    const { user } = setup();
    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalledWith("/api/context?project_type=web_saas&detail_level=medium&output_format=phases_table", expect.anything()));
    await user.click(screen.getByRole("radio", { name: "Mobile app" }));
    await waitFor(() =>
      expect(vi.mocked(fetch)).toHaveBeenLastCalledWith("/api/context?project_type=mobile_app&detail_level=medium&output_format=phases_table", expect.anything()),
    );
    expect(await within(inspector()).findByRole("region", { name: "System prompt" })).toHaveTextContent(context.system_prompt);
  });

  it("counts the transcript against 50,000 characters until the service context loads, then against its limit", async () => {
    let load!: (res: Response) => void;
    serviceContext = new Promise((resolve) => (load = resolve));
    setup();
    expect(screen.getByText("0 / 50,000")).toBeInTheDocument();
    await act(async () => load(Response.json({ ...context, max_transcription_chars: 1200 })));
    expect(await screen.findByText("0 / 1,200")).toBeInTheDocument();
  });

  // ui-1 (session 3): a fixed header and form must never leave the result no height. Below 480 px tall (772 px side by
  // side) nothing is fixed and the page scrolls as a whole, with the split a full viewport tall; below 768 px wide the
  // workspace scrolls in one.
  it("keeps the result usable on short and narrow viewports", async () => {
    const { user, input } = setup();
    const main = screen.getByRole("main");
    const shell = screen.getByRole("banner").parentElement;
    expect(shell).toHaveClass("h-dvh", "short:h-auto", "short:min-h-dvh");
    expect(main).toHaveClass("overflow-hidden", "max-md:overflow-y-auto", "short:overflow-visible");
    // the inspector panel then sticks a viewport tall, so its tabs stay in view beside the result
    expect(screen.getByRole("complementary", { name: "Inspector" })).toHaveClass("short:sticky", "short:top-0", "short:h-dvh", "short:self-start");
    await run(user, input);
    const split = transcriptPane().closest("[data-slot=split-view]");
    expect(split).toHaveClass("flex-1", "md:short:h-dvh", "md:short:flex-none");
    expect(input).toHaveClass("max-h-32"); // compact once a run sits below the form
  });

  it("below 768 px, shows the transcript and the estimate as tabs, opening Estimate when a run starts", async () => {
    stubPointer("fine", { wide: false });
    const { user, input } = setup();
    await run(user, input, "We need a booking portal.");
    const split = screen.getByRole("tablist", { name: "Result" }).closest("[data-slot=split-view]");
    expect(vi.mocked(Element.prototype.scrollIntoView).mock.contexts).toContain(split); // the result comes into view below the form
    const tabs = screen.getByRole("tablist", { name: "Result" });
    expect(within(tabs).getAllByRole("tab").map((tab) => tab.textContent)).toEqual(["Transcript", "Estimate"]);
    expect(screen.getByRole("tab", { name: "Estimate", selected: true })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Stop" })).toBeInTheDocument();
    const handle = screen.getByRole("separator", { name: "Resize the transcript and the estimate" });
    expect(handle).toHaveClass("max-md:hidden"); // the same tree as side by side, laid out as tabs by CSS
    expect(handle).not.toHaveAttribute("tabindex"); // and the split is disabled

    await user.click(screen.getByRole("tab", { name: "Transcript" }));
    expect(transcriptPane()).toHaveTextContent("We need a booking portal.");
  });

  // A hidden tab panel's live regions are not announced, so the run's end is announced outside the tabs.
  it("below 768 px, keeps the estimate streaming behind the Transcript tab and announces how it ends outside the tabs", async () => {
    stubPointer("fine", { wide: false });
    const { user, input } = setup();
    await run(user, input);
    await user.click(screen.getByRole("tab", { name: "Transcript" }));
    const panel = screen.getByRole("button", { name: "Stop" }).closest('[role="tabpanel"]');
    expect(panel).toHaveAttribute("data-state", "inactive"); // still mounted, hidden by CSS below 768 px
    expect(panel).toHaveClass("max-md:data-[state=inactive]:hidden");
    expect(runStatus()).toBeEmptyDOMElement();

    await finish(0);
    expect(runStatus()).toHaveTextContent("Estimate ready");
    await user.click(screen.getByRole("tab", { name: "Estimate" }));
    expect(runStatus()).toBeEmptyDOMElement();
    await user.click(screen.getByRole("tab", { name: "Transcript" }));
    expect(runStatus()).toBeEmptyDOMElement(); // nothing new happened while it was hidden
  });

  it("below 768 px, Esc stops a stream while the Transcript tab is open, and a failure is announced there too", async () => {
    stubPointer("fine", { wide: false });
    const { user, input, estimate } = setup();
    await run(user, input);
    await user.click(screen.getByRole("tab", { name: "Transcript" }));
    await user.keyboard("{Escape}");
    await waitFor(() => expect(runStatus()).toHaveTextContent("Stopped"));
    expect(estimateCalls()[0][1]?.signal?.aborted).toBe(true);

    await user.click(estimate);
    await user.click(screen.getByRole("tab", { name: "Transcript" }));
    streams[1].push(frame("error", { code: "upstream_unavailable", message: "down", retryable: true, request_id: "req-9" }));
    await waitFor(() => expect(runStatus()).toHaveTextContent("The AI service is unavailable right now. Try again in a moment."));
  });

  // Below 768 px the transcript sits behind a tab, and reaching it ends the hover or focus that linked a requirement.
  it("below 768 px, Evidence pins its requirement and opens the transcript at its quote, until the next pin or run", async () => {
    stubPointer("fine", { wide: false });
    const { user, input, estimate } = setup();
    await run(user, input);
    await finish(0);
    const scrolled = vi.mocked(Element.prototype.scrollIntoView);
    scrolled.mockClear();
    const evidence = (id: string) => screen.getByRole("button", { name: `Evidence for ${id}` });

    await user.click(evidence("R2"));
    expect(screen.getByRole("tab", { name: "Transcript", selected: true })).toBeInTheDocument();
    expect(transcriptPane()).toHaveFocus(); // the Evidence button is hidden now
    expect(mark("R2")).toHaveAttribute("data-active");
    // `main`, not the pane, scrolls below 768 px, so the quote is brought into view through every scrolling ancestor
    expect(scrolled.mock.contexts).toEqual([mark("R2")]);
    expect(scrolled).toHaveBeenCalledWith({ block: "center", behavior: "smooth" });
    expect(document.querySelector('[data-slot="hover-card-content"]')).toBeNull(); // the quote shows in the transcript instead

    await user.click(screen.getByRole("tab", { name: "Estimate" }));
    expect(evidence("R2").closest("li")).toHaveAttribute("data-active"); // hover and focus have left; the pin stays
    await user.click(screen.getByRole("tab", { name: "Transcript" }));
    expect(mark("R2")).toHaveAttribute("data-active");

    await user.click(screen.getByRole("tab", { name: "Estimate" }));
    await user.click(evidence("R1"));
    expect(mark("R1")).toHaveAttribute("data-active");
    expect(mark("R2")).not.toHaveAttribute("data-active");

    await user.click(estimate);
    await finish(1);
    expect(transcriptPane().querySelector("mark[data-active]")).toBeNull();

    await user.click(evidence("R2"));
    await user.click(screen.getByRole("tab", { name: "Estimate" }));
    await user.click(screen.getByRole("button", { name: "Regenerate" }));
    await finish(2);
    expect(mark("R2")).toBeInTheDocument();
    expect(transcriptPane().querySelector("mark[data-active]")).toBeNull(); // the new attempt numbers its own requirements
  });

  it("leaves the evidence card closed after a tap pins its requirement, also once the viewport widens", async () => {
    const resize = viewport(false);
    const { user, input } = setup();
    await run(user, input);
    await finish(0);
    const evidence = screen.getByRole("button", { name: "Evidence for R2" });
    fireEvent.pointerDown(evidence, { pointerType: "touch" }); // a tap: Radix ignores touch, so the button opens the card itself
    await user.click(evidence);
    expect(mark("R2")).toHaveAttribute("data-active");
    const pastOpenDelay = () => act(() => new Promise((resolve) => setTimeout(resolve, 300)));
    await pastOpenDelay();
    resize(true); // later, the phone turns to landscape
    await pastOpenDelay();
    expect(document.querySelector('[data-slot="hover-card-content"]')).toBeNull();
  });

  it("keeps the run's panes, focus and scroll when the viewport crosses 768 px mid-run", async () => {
    const resize = viewport(true);
    const { user, input } = setup();
    await run(user, input);
    const stop = screen.getByRole("button", { name: "Stop" });
    act(() => stop.focus());
    const pane = transcriptPane();
    pane.scrollTop = 120;

    resize(false);
    expect(screen.getByRole("tablist", { name: "Result" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Stop" })).toBe(stop);
    expect(stop).toHaveFocus();
    expect(transcriptPane()).toBe(pane);
    expect(pane.scrollTop).toBe(120);

    resize(true);
    expect(screen.queryByRole("tablist", { name: "Result" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Stop" })).toBe(stop);
    expect(stop).toHaveFocus();
  });
});

describe("quotesOf", () => {
  const R1 = { id: "R1", statement: "Log in", evidence: "patients log in, see their upcoming appointments" };
  const streaming = (partial: PartialBreakdown): StreamState => ({ status: "streaming", phase: "calling_llm", partial, startedAt: 0 });

  // Evidence is a requirement's last field, so a snapshot can end inside the newest one's quote ("Pat" of "Patients…"),
  // which would mark the first place those letters appear.
  it("leaves out the newest requirement of a snapshot until a later field starts: its quote may be cut short", () => {
    const cut = { requirements: [R1, { id: "R2", statement: "Book", evidence: "Pat" }] };
    expect(quotesOf(streaming(cut))).toEqual([{ id: "R1", evidence: R1.evidence }]);
    expect(quotesOf(streaming({ requirements: [{ id: "R1", evidence: "pat" }] }))).toEqual([]);

    const closed = { requirements: [R1, { id: "R2", statement: "Book", evidence: "Patients should be able to book" }], assumptions: [] };
    expect(quotesOf(streaming(closed))).toEqual([
      { id: "R1", evidence: R1.evidence },
      { id: "R2", evidence: "Patients should be able to book" },
    ]);
  });

  it("keeps a stream that stopped or failed mid-quote from marking the cut-short quote", () => {
    const requirements = [R1, { id: "R2", evidence: "Pat" }];
    expect(quotesOf({ status: "cancelled", partial: { requirements } })).toEqual([{ id: "R1", evidence: R1.evidence }]);
    expect(quotesOf({ status: "error", error: { code: "upstream_unavailable", message: "down", retryable: true }, partial: { requirements } })).toEqual([
      { id: "R1", evidence: R1.evidence },
    ]);
  });

  it("marks every quote the server grounded once the result arrives, and nothing before a run", () => {
    expect(quotesOf({ status: "done", result: fullResponse }).map(({ id }) => id)).toEqual(["R1", "R2"]); // R3 is ungrounded
    expect(quotesOf({ status: "idle" })).toEqual([]);
  });
});
