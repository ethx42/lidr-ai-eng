import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderToString } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fullResponse } from "@/lib/estimate/fixtures";
import type { Sample } from "@/lib/samples";
import { stubPointer } from "@/test/pointer";
import { Chat } from "./chat";

const SAMPLES: Sample[] = [
  { id: "course-meeting", title: "Course meeting", description: "Fitness studios, detailed call", text: "Laura: We run four fitness studios." },
  { id: "clinic-portal", title: "Clinic portal", description: "Patient portal, medium scope", text: "Sofía: We have three physiotherapy clinics." },
  { id: "vague-marketplace", title: "Vague marketplace", description: "An early idea", text: "Pablo: Like Airbnb, for things." },
];
const context = { prompt_version: "v1", system_prompt: "", references: [], chain: ["replay:gpt-4o-mini"], max_transcription_chars: 50_000 };
const tooLong = { error: { code: "invalid_request", message: "Transcription exceeds 50000 characters.", details: [{ type: "string_too_long" }] }, request_id: "req-422" };

describe("Chat", () => {
  let stream: (init?: RequestInit) => Response;

  beforeEach(() => {
    sessionStorage.clear();
    stubPointer("fine");
    Object.defineProperty(Element.prototype, "scrollIntoView", { value: vi.fn(), configurable: true }); // not in jsdom
    stream = () => new Response(new ReadableStream(), { headers: { "content-type": "text/event-stream" } }); // never ends
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async (url, init) => (String(url).startsWith("/api/context") ? Response.json(context) : stream(init))),
    );
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    Reflect.deleteProperty(Element.prototype, "scrollIntoView");
  });

  const setup = () => {
    const user = userEvent.setup();
    render(<Chat samples={SAMPLES} />);
    return { user, input: screen.getByRole("textbox", { name: "Meeting transcript" }), send: screen.getByRole("button", { name: "Estimate" }) };
  };
  const streamCalls = () => vi.mocked(fetch).mock.calls.filter(([url]) => String(url).startsWith("/api/estimate"));

  it("offers the three samples on an empty thread; a card fills the composer without sending", async () => {
    const { user, input } = setup();
    const cards = within(screen.getByRole("list", { name: "Sample transcripts" })).getAllByRole("button");
    expect(cards.map((card) => card.textContent)).toEqual(SAMPLES.map(({ title, description }) => `${title}${description}`));
    expect(cards[1]).toHaveAccessibleName("Clinic portal");

    await user.click(cards[1]);
    expect(input).toHaveValue(SAMPLES[1].text);
    expect(input).toHaveFocus();
    expect(streamCalls()).toHaveLength(0);
  });

  it("asks before a sample card replaces a draft", async () => {
    const { user, input } = setup();
    await user.type(input, "My notes");
    await user.click(screen.getByRole("button", { name: "Vague marketplace" }));
    expect(screen.getByRole("group", { name: "Replace your draft with the “Vague marketplace” sample?" })).toBeInTheDocument();
    expect(input).toHaveValue("My notes");
    await user.click(screen.getByRole("button", { name: "Replace draft" }));
    expect(input).toHaveValue(SAMPLES[2].text);
  });

  it("sends the draft, clears the composer and keeps focus in it", async () => {
    const { user, input, send } = setup();
    await user.type(input, "We need a booking portal.");
    await user.click(send);
    expect(input).toHaveValue("");
    expect(input).toHaveFocus();
    expect(screen.getByText("We need a booking portal.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Stop" })).toBeInTheDocument();
    expect(JSON.parse(String(streamCalls()[0][1]?.body))).toEqual({ transcription: "We need a booking portal.", project_type: "web_saas", detail_level: "medium", output_format: "phases_table" });
  });

  it("on a touch screen, never moves focus into the transcript, so the on-screen keyboard stays closed", async () => {
    stubPointer("coarse");
    const { user, input, send } = setup();
    await user.click(screen.getByRole("button", { name: "Clinic portal" }));
    expect(input).toHaveValue(SAMPLES[1].text);
    expect(input).not.toHaveFocus();

    await user.click(send);
    expect(screen.getByRole("button", { name: "Stop" })).toBeInTheDocument();
    expect(input).toHaveValue("");
    expect(input).not.toHaveFocus();
  });

  // §8 managed focus: Estimate is disabled once the composer clears, so focus must not stay on it or fall to the page.
  it("on a touch screen, moves focus from Estimate to the new turn's Stop without scrolling", async () => {
    stubPointer("coarse");
    const { user, input, send } = setup();
    await user.type(input, "We need a booking portal.");
    const focus = vi.spyOn(HTMLElement.prototype, "focus");
    await user.click(send);
    const stop = screen.getByRole("button", { name: "Stop" });
    expect(stop).toHaveFocus();
    expect(focus.mock.contexts.at(-1)).toBe(stop);
    expect(focus).toHaveBeenLastCalledWith({ preventScroll: true });
    focus.mockRestore();
  });

  it("on a touch screen, Edit transcript still moves focus into the transcript (the user asked to edit it)", async () => {
    stubPointer("coarse");
    stream = () => Response.json(tooLong, { status: 422 });
    const { user, input, send } = setup();
    await user.type(input, "A very long transcript");
    await user.click(send);
    await user.click(await screen.findByRole("button", { name: "Edit transcript" }));
    expect(input).toHaveValue("A very long transcript");
    expect(input).toHaveFocus();
  });

  it("puts a rejected transcript back in the composer from the error card, asking first if there is a draft", async () => {
    stream = () => Response.json(tooLong, { status: 422 });
    const { user, input } = setup();
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

  it("shows the latest completed call in the inspector panel", async () => {
    const result = `event: result\ndata: ${JSON.stringify(fullResponse)}\n\n`;
    stream = () => new Response(result, { headers: { "content-type": "text/event-stream", "x-request-id": "req-7" } });
    const { user, input, send } = setup();
    expect(screen.getByRole("button", { name: "Inspector" })).toHaveAttribute("aria-haspopup", "dialog"); // the sheet below 1024 px
    const inspector = screen.getByRole("complementary", { name: "Inspector" });
    await user.click(within(inspector).getByRole("tab", { name: "Last call" }));
    expect(within(inspector).getByText("Run an estimate to see its metrics.")).toBeInTheDocument();

    await user.type(input, "We need a booking portal.");
    await user.click(send);
    expect(await within(inspector).findByText("req-7")).toBeInTheDocument();
    expect(within(inspector).getByText("Physiotherapy patient portal")).toBeInTheDocument();
  });

  // ui-1: a fixed 48 px header and a ~213 px composer left the thread 0 px at 320x256 (400% zoom) and ~95 px on a
  // landscape phone. The composer is compact now, and below 480 px tall nothing is fixed: the whole page scrolls.
  it("keeps the thread usable on short viewports: a compact composer, and a page that scrolls as a whole below 480 px", async () => {
    const { user, input } = setup();
    const main = screen.getByRole("main");
    const shell = screen.getByRole("banner").parentElement;
    expect(shell).toHaveClass("h-dvh", "short:h-auto", "short:min-h-dvh");
    expect(main).toHaveClass("overflow-y-auto", "short:overflow-visible");
    expect(input).toHaveClass("min-h-12");
    expect(input).not.toHaveClass("min-h-20");
    expect(screen.getByText("Paste or type a transcript to estimate.")).toHaveClass("sr-only"); // the placeholder says it

    const form = screen.getByRole("form", { name: "New estimate" });
    const note = "Each transcript is estimated on its own. Conversation memory arrives in a later version.";
    expect(within(form).queryByText(/estimated on its own/)).not.toBeInTheDocument();
    expect(within(main).getByText(note)).toBeInTheDocument(); // in the empty state
    expect(input).toHaveAccessibleDescription(expect.stringContaining(note));

    await user.type(input, "We need a booking portal.");
    await user.keyboard("{Control>}{Enter}{/Control}");
    expect(within(main).getAllByText(note)).toHaveLength(1); // once, above the thread
    expect(within(main).getByText(note).compareDocumentPosition(screen.getByRole("list", { name: "Estimates" })) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("renders a skeleton, not the stored thread, on the server", () => {
    sessionStorage.setItem("estimator.thread.v1", JSON.stringify([{ id: "a", transcription: "Stored transcript", state: { status: "done", result: fullResponse } }]));
    const html = renderToString(<Chat samples={SAMPLES} />);
    expect(html).toContain('data-slot="skeleton"');
    expect(html).not.toContain("Stored transcript");
    expect(html).not.toContain("Course meeting");
  });
});
