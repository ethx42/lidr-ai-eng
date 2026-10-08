import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Toaster, toast } from "sonner";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { quotesOf } from "@/components/session/turn-card";
import { ServiceContextProvider } from "@/components/service-context";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { components } from "@/lib/ai-service/schema";
import { fullEstimate, fullResponse } from "@/lib/estimate/fixtures";
import type { PartialBreakdown, StreamState } from "@/lib/estimate/types";
import type { Sample } from "@/lib/samples";
import { stubPointer } from "@/test/pointer";
import { Workspace } from "./workspace";

type Schemas = components["schemas"];

const SAMPLES: Sample[] = [
  { id: "clinic-portal", title: "Clinic portal", description: "Patient portal, medium scope", text: "Sofía: We have three physiotherapy clinics." },
];
// Holds the fixture's R1 and R2 quotes; R3's is not in it (the fixture's grounding report flags R3).
const TRANSCRIPT = [
  "Sofía: We want a web portal where patients log in, see their upcoming appointments, and download invoices as PDF.",
  "Sofía: Yes, patients should be able to book a new session with their physiotherapist, and cancel up to 24 hours before.",
].join("\n");
const SESSIONS = ["0b6f3c1e-4d2a-4f8b-9c3e-2a1d5e6f7a8b", "5d1e2f3a-4b5c-4d6e-8f7a-9b0c1d2e3f4a"];
const context = {
  prompt_version: "v2",
  available_versions: ["v1", "v2", "v3"],
  system_prompt: "You estimate software projects.",
  references: [],
  chain: ["replay:gpt-4o-mini"],
  max_transcription_chars: 50_000,
};
const EMPTY_MEMORY: Schemas["ProjectMetadata"] = { project_name: null, assumed_team_size: null, mentioned_technologies: [], agreed_scope: null };
const MEMORY: Schemas["ProjectMetadata"] = {
  project_name: "Physiotherapy patient portal",
  assumed_team_size: 3,
  mentioned_technologies: ["ClinicCloud"],
  agreed_scope: "A responsive patient portal for three physiotherapy clinics.",
};
const turnResult = (over: Partial<Schemas["TurnResponse"]> = {}): Schemas["TurnResponse"] => ({
  ...fullResponse,
  breakdown: fullEstimate,
  prompt_version: "v3",
  session_id: SESSIONS[0],
  project_metadata: MEMORY,
  metadata_changes: ["project_name", "assumed_team_size", "mentioned_technologies", "agreed_scope"],
  history_turns: 1,
  ...over,
});
const tooLong = { error: { code: "invalid_request", message: "Transcription exceeds 50000 characters.", details: [{ type: "string_too_long" }] }, request_id: "req-422" };
const pdf = (name = "spec.pdf") => new File(["%PDF-1.7"], name, { type: "application/pdf" });

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
  let createSession: (() => Response) | undefined;
  let created: number;
  let storedHistory: number; // what GET /api/sessions/{id} reports for a session this tab already had

  beforeEach(() => {
    streams = [];
    respond = undefined;
    serviceContext = undefined;
    createSession = undefined;
    created = 0;
    storedHistory = 0;
    sessionStorage.clear();
    stubPointer("fine");
    Object.defineProperty(HTMLElement.prototype, "scrollTo", { value: vi.fn(), configurable: true });
    Object.defineProperty(Element.prototype, "scrollIntoView", { value: vi.fn(), configurable: true });
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async (url, init) => {
        const path = String(url);
        const method = init?.method ?? "GET";
        if (path === "/api/context") return serviceContext ?? Response.json(context);
        if (path.startsWith("/api/context")) return Response.json(context);
        if (path === "/api/sessions" && method === "POST") {
          if (createSession) return createSession();
          return Response.json({ session_id: SESSIONS[created++] }, { status: 201 });
        }
        if (path.startsWith("/api/sessions/") && method === "GET") {
          const id = path.split("/").at(-1);
          const history_turns = SESSIONS.slice(0, created).includes(id ?? "") ? 0 : storedHistory;
          return Response.json({ session_id: id, project_metadata: EMPTY_MEMORY, history_turns, max_turns: 6, prompt_version: "v3" });
        }
        if (respond) return respond(init);
        const stream = sseBody(init?.signal);
        streams.push(stream);
        return new Response(stream.body, { headers: { "content-type": "text/event-stream", "x-request-id": `req-${streams.length}` } });
      }),
    );
  });
  afterEach(() => {
    toast.dismiss(); // sonner's store outlives the test, and a new Toaster replays the toasts still active
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    Reflect.deleteProperty(HTMLElement.prototype, "scrollTo");
    Reflect.deleteProperty(Element.prototype, "scrollIntoView");
  });

  const setup = () => {
    const user = userEvent.setup({ applyAccept: false });
    // the providers and the toaster the root layout gives the page
    render(
      <TooltipProvider>
        <ServiceContextProvider>
          <Workspace samples={SAMPLES} />
          <Toaster />
        </ServiceContextProvider>
      </TooltipProvider>,
    );
    return { user, input: screen.getByRole("textbox", { name: "Transcript for this turn" }), estimate: screen.getByRole("button", { name: "Estimate" }) };
  };
  const calls = (pattern: RegExp, method = "POST") => vi.mocked(fetch).mock.calls.filter(([url, init]) => pattern.test(String(url)) && (init?.method ?? "GET") === method);
  const turnCalls = () => calls(/\/estimate\/stream$/);
  const sent = (call: number) => {
    const [url, init] = turnCalls()[call];
    const form = init?.body;
    if (!(form instanceof FormData)) throw new Error("not a multipart turn");
    return { url: String(url), form, headers: new Headers(init?.headers) };
  };
  const fields = (form: FormData) => Object.fromEntries([...form.keys()].filter((key) => key !== "attachments").map((key) => [key, form.get(key)]));
  const fileNames = (form: FormData) => form.getAll("attachments").map((file) => (file as File).name);
  // The header shows the service context, and the meter the session's view.
  const loaded = async () => {
    await screen.findByText("Model:");
    await screen.findByText(/^History \d+ \/ 6 turns$/);
  };
  const attach = (user: ReturnType<typeof userEvent.setup>, ...files: File[]) => user.upload(screen.getByLabelText("Attach documents"), files);
  const run = async (user: ReturnType<typeof userEvent.setup>, input: HTMLElement, text = TRANSCRIPT) => {
    await loaded();
    const before = turnCalls().length;
    await user.type(input, text);
    await user.click(screen.getByRole("button", { name: "Estimate" }));
    await waitFor(() => expect(turnCalls()).toHaveLength(before + 1));
  };
  // Streams are per attempt and turns per message: a retried turn's stream index runs ahead of its number.
  const finish = async (stream: number, result: unknown = turnResult(), n = stream + 1) => {
    streams[stream].push(frame("result", result));
    await waitFor(() => expect(within(turn(n)).getByRole("button", { name: "Copy as markdown" })).toBeInTheDocument());
  };
  const thread = () => screen.getByRole("list", { name: "Conversation" });
  const turns = () => within(thread()).queryAllByRole("listitem").filter((item) => item.parentElement === thread());
  const turn = (n: number) => {
    const card = turns()[n - 1];
    if (!card) throw new Error(`no turn ${n}`);
    expect(card).toHaveAccessibleName(`Turn ${n}`);
    return card;
  };
  const openTranscript = async (user: ReturnType<typeof userEvent.setup>, n = 1) => {
    const toggle = within(turn(n)).getByRole("button", { name: /^Transcript/ });
    if (toggle.getAttribute("aria-expanded") !== "true") await user.click(toggle);
    return transcriptPane(n);
  };
  const transcriptPane = (n = 1) => screen.getByRole("region", { name: `Transcript of turn ${n}` });
  const mark = (id: string, n = 1) => transcriptPane(n).querySelector(`mark[data-req="${id}"]`);
  const memory = () => screen.getByRole("complementary", { name: "Project memory" });
  const fact = (label: string) => {
    const value = within(memory()).getByText(label, { selector: "dt, dt *" }).closest("div")?.querySelector("dd");
    if (!(value instanceof HTMLElement)) throw new Error(`no fact ${label}`);
    return value;
  };
  const inspector = async (user: ReturnType<typeof userEvent.setup>, tab: "Context" | "Last call") => {
    await user.click(screen.getByRole("button", { name: "Inspector" }));
    const sheet = screen.getByRole("dialog", { name: "Inspector" });
    await user.click(within(sheet).getByRole("tab", { name: tab }));
    const text = within(sheet).getByRole("tabpanel", { name: tab }).textContent;
    await user.click(within(sheet).getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    return text;
  };
  // A viewport whose width the test changes mid-run: the turn card's query answers `wide`, change listeners fire.
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

  describe("a conversation", () => {
    it("starts a session on load and invites a first turn", async () => {
      setup();
      expect(screen.getByText("Start the conversation")).toBeInTheDocument();
      await loaded();
      expect(screen.getByText("History 0 / 6 turns")).toBeInTheDocument();
      expect(fact("Project name")).toHaveTextContent("Not mentioned yet");
      // one landmark for the memory column (the panel inside is not a second region of the same name)
      expect(screen.getAllByRole("complementary", { name: "Project memory" })).toHaveLength(1);
      expect(screen.queryByRole("region", { name: "Project memory" })).not.toBeInTheDocument();
      expect(calls(/^\/api\/sessions$/)).toHaveLength(1);
      expect(sessionStorage.getItem("estimator.sessionId")).toBe(SESSIONS[0]);
    });

    // After a reload the session is kept (sessionStorage) but this page never showed its turns.
    it("continues a stored conversation: says how many earlier turns it keeps, and numbers new turns after them", async () => {
      sessionStorage.setItem("estimator.sessionId", "7e1c9d2a-3b4f-4a5e-8c6d-0f1e2a3b4c5d");
      storedHistory = 3;
      const { user, input } = setup();
      expect(await screen.findByText("This conversation continues")).toBeInTheDocument();
      expect(screen.getByText(/3 earlier turns are kept in its history/)).toBeInTheDocument();
      expect(screen.queryByText("Start the conversation")).not.toBeInTheDocument();
      expect(calls(/^\/api\/sessions$/)).toHaveLength(0); // the stored session is used, not replaced
      await run(user, input, "Fourth call");
      expect(turns()[0]).toHaveAccessibleName("Turn 4");
    });

    it("sends the typed form and its attachments as one multipart turn of the session, then clears the composer", async () => {
      const { user, input, estimate } = setup();
      await loaded();
      await user.type(input, "We need a booking portal.");
      await attach(user, pdf("spec.pdf"), new File(["notes"], "notes.txt", { type: "text/plain" }));
      await user.click(screen.getByRole("radio", { name: "Mobile app" }));
      await user.click(estimate);

      expect(await within(turn(1)).findByRole("button", { name: "Stop" })).toBeInTheDocument();
      const { url, form, headers } = sent(0);
      expect(url).toBe(`/api/sessions/${SESSIONS[0]}/estimate/stream`);
      expect(fields(form)).toEqual({ transcript: "We need a booking portal.", project_type: "mobile_app", detail_level: "medium", output_format: "phases_table" });
      expect(fileNames(form)).toEqual(["spec.pdf", "notes.txt"]);
      expect(headers.has("content-type")).toBe(false); // the browser writes the multipart boundary

      // the turn keeps what was sent; the composer is ready for the next turn
      expect(within(turn(1)).getByText("Mobile app, medium detail, phases table")).toBeInTheDocument();
      expect(within(within(turn(1)).getByRole("list", { name: "Attachments" })).getAllByRole("listitem").map((item) => item.textContent)).toEqual([
        expect.stringContaining("spec.pdf"),
        expect.stringContaining("notes.txt"),
      ]);
      expect(estimate).toHaveFocus(); // a mouse keeps focus where it was
      expect(input).toHaveValue("");
      expect(screen.queryByRole("list", { name: "Attached documents" })).not.toBeInTheDocument();
      expect(screen.getByRole("radio", { name: "Mobile app" })).toBeChecked(); // the choices stay for the next turn
      expect(await openTranscript(user)).toHaveTextContent("We need a booking portal.");
    });

    it("updates the project memory and the history meter from each completed turn, marking what changed", async () => {
      const { user, input } = setup();
      await run(user, input);
      await finish(0);
      expect(fact("Project name")).toHaveTextContent("Physiotherapy patient portal");
      expect(fact("Technologies")).toHaveTextContent("ClinicCloud");
      expect(within(memory()).getAllByText("Updated in turn 1")).toHaveLength(4);
      expect(screen.getByText("History 1 / 6 turns")).toBeInTheDocument();
      expect(within(turn(1)).queryByText(/vs previous turn/)).not.toBeInTheDocument(); // nothing to compare the first turn with

      await run(user, input, "Second call: payments through Redsys.");
      const bigger = { ...fullEstimate, totals: { ...fullEstimate.totals, expected_hours: 125, estimated_cost: 7500 } };
      await finish(1, turnResult({ breakdown: bigger, project_metadata: { ...MEMORY, mentioned_technologies: ["ClinicCloud", "Redsys"] }, metadata_changes: ["mentioned_technologies"], history_turns: 2 }));
      expect(fact("Technologies")).toHaveTextContent("ClinicCloudRedsys");
      expect(within(memory()).getAllByText(/^Updated/)).toHaveLength(1);
      expect(within(fact("Technologies").previousElementSibling as HTMLElement).getByText("Updated in turn 2")).toBeInTheDocument();
      expect(screen.getByText("History 2 / 6 turns")).toBeInTheDocument();
      expect(within(turn(2)).getByText("+30 h, +$1,800 vs previous turn")).toBeInTheDocument();
    });

    // A stopped or failed turn has no totals and changes no memory: what is compared, and what changed, names its turn.
    it("names the turn behind the memory's marks and the totals' change when a stopped turn sits between", async () => {
      const { user, input } = setup();
      await run(user, input);
      await finish(0);
      await run(user, input, "Second call");
      await user.click(within(turn(2)).getByRole("button", { name: "Stop" }));
      await run(user, input, "Third call");
      expect(within(memory()).getAllByText("Updated in turn 1")).toHaveLength(4); // while turn 3 streams
      const bigger = { ...fullEstimate, totals: { ...fullEstimate.totals, expected_hours: 125, estimated_cost: 7500 } };
      await finish(2, turnResult({ breakdown: bigger, metadata_changes: ["agreed_scope"], history_turns: 2 }));
      expect(within(turn(3)).getByText("+30 h, +$1,800 vs turn 1")).toBeInTheDocument();
      expect(within(fact("Agreed scope").previousElementSibling as HTMLElement).getByText("Updated in turn 3")).toBeInTheDocument();
      expect(within(memory()).getAllByText(/^Updated/)).toHaveLength(1);
    });

    // Heading navigation reads the conversation turn by turn: each turn's label is its h2, and its estimate sits below it.
    it("gives each turn a heading, with the estimate's title and sections, structured or as a document, one level below", async () => {
      const { user, input } = setup();
      await run(user, input);
      await finish(0, turnResult({ estimation: "## Estimation: Booking\n\n### Task breakdown\n\nThree tasks.\n" }));
      const card = turn(1);
      expect(within(card).getAllByRole("heading", { level: 2 }).map((heading) => heading.textContent)).toEqual(["Turn 1"]);
      expect(within(card).getAllByRole("heading", { level: 3 }).map((heading) => heading.textContent)).toEqual([fullEstimate.project_name]);
      expect(within(card).getAllByRole("heading", { level: 4 }).map((heading) => heading.textContent)).toEqual([
        "Summary",
        "Requirements",
        "Assumptions",
        "Open questions",
        "Tasks",
        "Team",
        "Risks",
        "Confidence",
      ]);

      await user.click(within(card).getByRole("radio", { name: "Document" }));
      expect(within(card).getAllByRole("heading", { level: 3 }).map((heading) => heading.textContent)).toEqual(["Estimation: Booking"]);
      expect(within(card).getAllByRole("heading", { level: 4 }).map((heading) => heading.textContent)).toEqual(["Task breakdown"]);
    });

    // S5-R3: re-running a completed turn would fork the history.
    it("offers no Regenerate on a completed turn; a stopped turn offers Retry and resubmits the same transcript, choices and files", async () => {
      const { user, input } = setup();
      await run(user, input, "First turn");
      await finish(0);
      expect(within(turn(1)).queryByRole("button", { name: "Regenerate" })).not.toBeInTheDocument();
      expect(within(turn(1)).queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();

      await user.type(input, "Second turn");
      await attach(user, pdf("spec.pdf"));
      await user.click(screen.getByRole("radio", { name: "Narrative" }));
      await user.click(screen.getByRole("button", { name: "Estimate" }));
      await user.click(await within(turn(2)).findByRole("button", { name: "Stop" }));
      const retry = within(turn(2)).getByRole("button", { name: "Retry" });
      expect(retry).toHaveFocus();

      await user.type(input, "Something else");
      await user.click(screen.getByRole("radio", { name: "Line items" }));
      await user.click(retry);
      await waitFor(() => expect(turnCalls()).toHaveLength(3));
      expect(fields(sent(2).form)).toEqual(fields(sent(1).form));
      expect(fields(sent(2).form)).toMatchObject({ transcript: "Second turn", output_format: "narrative" });
      expect(fileNames(sent(2).form)).toEqual(["spec.pdf"]);
      expect(turns()).toHaveLength(2); // a new attempt at the same turn
      expect(await within(turn(2)).findByRole("button", { name: "Stop" })).toHaveFocus();
      expect(input).toHaveValue("Something else");
    });

    it("refuses a new turn while one is answering, without stopping it", async () => {
      const { user, input, estimate } = setup();
      await run(user, input, "First");
      await user.type(input, "Second");
      await user.click(estimate);
      expect(await screen.findByText("This conversation is still answering the previous turn")).toBeInTheDocument();
      expect(turnCalls()).toHaveLength(1);
      expect(turnCalls()[0][1]?.signal?.aborted).toBe(false);
      expect(input).toHaveValue("Second");
      expect(turns()).toHaveLength(1);
    });

    it("starts a new conversation from the header, asking first while a turn is answering", async () => {
      const { user, input } = setup();
      await run(user, input, "First");
      await user.click(screen.getByRole("button", { name: "New conversation" }));
      const dialog = screen.getByRole("alertdialog", { name: "Start a new conversation?" });
      expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus();
      await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
      expect(turnCalls()[0][1]?.signal?.aborted).toBe(false);
      expect(turns()).toHaveLength(1);
      // the dialog opens from state, with no trigger to return to: focus goes back to the button that asked
      await waitFor(() => expect(screen.getByRole("button", { name: "New conversation" })).toHaveFocus());

      await user.click(screen.getByRole("button", { name: "New conversation" }));
      await user.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Start new" }));
      expect(turnCalls()[0][1]?.signal?.aborted).toBe(true);
      await waitFor(() => expect(input).toHaveFocus()); // with a mouse, ready for the new conversation's first turn
      await waitFor(() => expect(sessionStorage.getItem("estimator.sessionId")).toBe(SESSIONS[1]));
      expect(screen.getByText("Start the conversation")).toBeInTheDocument();
      expect(await screen.findByText("History 0 / 6 turns")).toBeInTheDocument();
      expect(await screen.findByText("Started a new conversation.")).toBeInTheDocument();

      await run(user, input, "Fresh start");
      expect(sent(1).url).toBe(`/api/sessions/${SESSIONS[1]}/estimate/stream`);
    });

    it("starts a new conversation at once when no turn is answering, forgetting the memory", async () => {
      const { user, input } = setup();
      await run(user, input);
      await finish(0);
      await user.click(screen.getByRole("button", { name: "New conversation" }));
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
      expect(input).toHaveFocus();
      expect(await screen.findByText("History 0 / 6 turns")).toBeInTheDocument();
      expect(fact("Project name")).toHaveTextContent("Not mentioned yet");
      expect(screen.queryByRole("list", { name: "Conversation" })).not.toBeInTheDocument();
    });

    // Review Focus 4: a session idle past its TTL, or evicted, answers 404.
    it("recovers from an expired session: starts a new one, says so, and puts the message back in the composer", async () => {
      respond = () => Response.json({ error: { code: "session_not_found", message: "Session not found or expired." }, request_id: "r" }, { status: 404 });
      const { user, input } = setup();
      await loaded();
      await user.type(input, "Lost turn");
      await attach(user, pdf("spec.pdf"));
      await user.click(screen.getByRole("button", { name: "Estimate" }));
      expect(await screen.findByText("This conversation expired, so a new one was started. Your message is back in the composer.")).toBeInTheDocument();
      await waitFor(() => expect(sessionStorage.getItem("estimator.sessionId")).toBe(SESSIONS[1]));
      expect(input).toHaveValue("Lost turn");
      expect(within(screen.getByRole("list", { name: "Attached documents" })).getByText("spec.pdf")).toBeInTheDocument();
      expect(screen.queryByRole("list", { name: "Conversation" })).not.toBeInTheDocument();

      respond = undefined;
      await user.click(screen.getByRole("button", { name: "Estimate" }));
      await waitFor(() => expect(turnCalls()).toHaveLength(2));
      expect(sent(1).url).toBe(`/api/sessions/${SESSIONS[1]}/estimate/stream`);
      expect(fileNames(sent(1).form)).toEqual(["spec.pdf"]);
    });

    // The answers on screen are the user's until they ask for a new conversation: they have not copied them all yet.
    it("keeps the turns already shown, read-only, above a note when the session expires mid-conversation, until New conversation", async () => {
      const { user, input } = setup();
      await run(user, input);
      await finish(0);
      await run(user, input, "Second call");
      await user.click(within(turn(2)).getByRole("button", { name: "Stop" }));
      respond = () => Response.json({ error: { code: "session_not_found", message: "Session not found or expired." }, request_id: "r" }, { status: 404 });
      await run(user, input, "Third call");
      expect(await screen.findByText("This conversation expired, so a new one was started. Your message is back in the composer.")).toBeInTheDocument();
      await waitFor(() => expect(sessionStorage.getItem("estimator.sessionId")).toBe(SESSIONS[1]));
      expect(input).toHaveValue("Third call");
      expect(await screen.findByText("History 0 / 6 turns")).toBeInTheDocument();
      expect(fact("Project name")).toHaveTextContent("Not mentioned yet"); // the new conversation's memory

      const expired = screen.getByRole("list", { name: "Expired conversation" });
      const kept = within(expired).getAllByRole("listitem").filter((item) => item.parentElement === expired);
      expect(kept.map((card) => within(card).getByRole("heading", { level: 2 }).textContent)).toEqual(["Turn 1", "Turn 2"]);
      expect(within(kept[0]).getByRole("heading", { level: 3, name: fullEstimate.project_name })).toBeInTheDocument();
      expect(within(kept[0]).getByRole("button", { name: "Copy as markdown" })).toBeInTheDocument();
      expect(within(kept[1]).getByText("Stopped")).toBeInTheDocument();
      expect(within(kept[1]).queryByRole("button", { name: "Retry" })).not.toBeInTheDocument(); // its session is gone
      expect(screen.getByRole("heading", { level: 2, name: "This conversation expired" })).toBeInTheDocument();
      expect(screen.getByText("The answers above are kept for reference. The new conversation starts without their history and memory.")).toBeInTheDocument();
      expect(screen.queryByText("Start the conversation")).not.toBeInTheDocument();
      expect(screen.queryByRole("list", { name: "Conversation" })).not.toBeInTheDocument();

      respond = undefined;
      await user.click(screen.getByRole("button", { name: "Estimate" }));
      await waitFor(() => expect(turnCalls()).toHaveLength(4));
      expect(sent(3).url).toBe(`/api/sessions/${SESSIONS[1]}/estimate/stream`);
      expect(turns()).toHaveLength(1);
      expect(turn(1)).toHaveTextContent("Turn 1"); // the new conversation numbers its own turns
      expect(screen.getByRole("list", { name: "Expired conversation" })).toBeInTheDocument();

      await user.click(within(turn(1)).getByRole("button", { name: "Stop" }));
      await user.click(screen.getByRole("button", { name: "New conversation" }));
      expect(screen.queryByRole("list", { name: "Expired conversation" })).not.toBeInTheDocument();
      expect(screen.queryByText("This conversation expired")).not.toBeInTheDocument();
      expect(screen.getByText("Start the conversation")).toBeInTheDocument();
    });

    it("recovers when the session vanishes mid-turn (an error event)", async () => {
      const { user, input } = setup();
      await run(user, input, "Mid-turn");
      streams[0].push(frame("error", { code: "session_not_found", message: "gone", retryable: false, request_id: "r" }));
      expect(await screen.findByText(/This conversation expired/)).toBeInTheDocument();
      await waitFor(() => expect(sessionStorage.getItem("estimator.sessionId")).toBe(SESSIONS[1]));
      expect(input).toHaveValue("Mid-turn");
    });

    it("puts the message back when the session is busy with another turn (409)", async () => {
      respond = () => Response.json({ error: { code: "session_busy", message: "busy" }, request_id: "r" }, { status: 409 });
      const { user, input } = setup();
      await run(user, input, "Too soon");
      expect(await screen.findByText("This conversation is still answering the previous turn")).toBeInTheDocument();
      await waitFor(() => expect(input).toHaveValue("Too soon"));
      expect(screen.queryByRole("list", { name: "Conversation" })).not.toBeInTheDocument();
      expect(sessionStorage.getItem("estimator.sessionId")).toBe(SESSIONS[0]); // the same conversation
    });

    // The fix is in the attachments: focus goes to the rejected file, which carries the service's reason.
    it("puts a turn whose attachment was rejected back in the composer, with that file marked by the service's reason and focused", async () => {
      respond = () => Response.json({ error: { code: "invalid_attachment", message: "scan.pdf: unreadable PDF" }, request_id: "r" }, { status: 422 });
      const { user, input } = setup();
      await loaded();
      await user.type(input, "With a bad file");
      await attach(user, pdf("brief.pdf"), pdf("scan.pdf"));
      await user.click(screen.getByRole("button", { name: "Estimate" }));
      const card = await within(turn(1)).findByRole("alert");
      expect(card).toHaveTextContent("An attachment was rejected: scan.pdf: unreadable PDF.");
      await user.click(within(card).getByRole("button", { name: "Edit attachments" }));
      expect(input).toHaveValue("With a bad file");
      const attached = screen.getByRole("list", { name: "Attached documents" });
      const remove = within(attached).getByRole("button", { name: "Remove scan.pdf" });
      expect(remove).toHaveFocus();
      expect(remove).toHaveAccessibleDescription("scan.pdf: unreadable PDF");
      expect(remove.closest("li")).toHaveTextContent("Rejected");
      expect(within(attached).getByRole("button", { name: "Remove brief.pdf" }).closest("li")).not.toHaveTextContent("Rejected");
      expect(screen.getByText("scan.pdf: unreadable PDF")).toBeVisible();

      await user.click(remove); // the reason goes with the file
      expect(screen.queryByText("scan.pdf: unreadable PDF")).not.toBeInTheDocument();
      expect(screen.queryByText("Rejected")).not.toBeInTheDocument();

      // A different draft in the composer is never replaced silently: its question takes focus first.
      await user.clear(input);
      await user.type(input, "Something else");
      await user.click(within(card).getByRole("button", { name: "Edit attachments" }));
      expect(screen.getByRole("group", { name: "Replace your draft with the message with the rejected attachment?" })).toBeInTheDocument();
      await waitFor(() => expect(screen.getByRole("button", { name: "Keep my draft" })).toHaveFocus());
      expect(within(screen.getByRole("list", { name: "Attached documents" })).getByRole("button", { name: "Remove scan.pdf" })).toHaveAccessibleDescription("scan.pdf: unreadable PDF");
    });

    it("says when no conversation can be started, and tries again", async () => {
      createSession = () => Response.json({ error: { code: "sessions_full", message: "full" } }, { status: 503 });
      const { user, input } = setup();
      const error = await within(memory()).findByText("The conversation could not be started.");
      await user.type(input, "Anyone there?");
      await user.click(screen.getByRole("button", { name: "Estimate" }));
      expect(await screen.findByText("No conversation yet: the AI service could not start one. Try again in a moment.")).toBeInTheDocument();
      expect(turnCalls()).toHaveLength(0);

      createSession = undefined;
      await user.click(within(error.closest('[data-slot="alert"]') as HTMLElement).getByRole("button", { name: "Retry" }));
      expect(await screen.findByText("History 0 / 6 turns")).toBeInTheDocument();
      expect(within(memory()).queryByText("The conversation could not be started.")).not.toBeInTheDocument();
    });
  });

  describe("evidence in a turn", () => {
    it("highlights each grounded quote in the turn's transcript, and the one behind the hovered or focused requirement", async () => {
      const { user, input } = setup();
      await run(user, input);
      await openTranscript(user);
      // R1's quote is complete once R2 has started; R2's, cut short, would match R1's sentence ("patients log in")
      streams[0].push(frame("partial", { seq: 1, breakdown: { requirements: [{ id: "R1", evidence: "patients log in, see their" }, { id: "R2", evidence: "patients" }] } }));
      await waitFor(() => expect(mark("R1")).toHaveTextContent("patients log in, see their")); // marks follow the stream
      expect(transcriptPane().querySelector('mark[data-req~="R2"]')).toBeNull();

      await finish(0);
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
      await openTranscript(user);
      await finish(0, turnResult({ grounding: { ...fullResponse.grounding, ungrounded_requirement_ids: ["R1", "R3"] } }));
      expect(mark("R1")).toBeNull();
      expect(mark("R2")).toBeInTheDocument();
      expect(screen.getAllByText("Quote not found in the transcript")).toHaveLength(2);
    });

    // Grounding covers the conversation the model saw, so a quote can come from an earlier turn: no mark here.
    it("says where a grounded quote from an earlier message comes from, instead of marking it", async () => {
      const { user, input } = setup();
      await run(user, input);
      await finish(0);
      await run(user, input, "Second call: nothing new about logins.");
      await finish(1, turnResult({ history_turns: 2 }));
      await openTranscript(user, 2);
      expect(transcriptPane(2).querySelector("mark")).toBeNull();
      act(() => within(turn(2)).getByRole("button", { name: "Evidence for R1" }).focus());
      await waitFor(() => expect(document.querySelector('[data-slot="hover-card-content"]')).toHaveTextContent("Quote from an earlier message"));
    });

    it("below 768 px, Evidence opens the turn's transcript at its quote and pins it, until the next pin or attempt", async () => {
      stubPointer("fine", { wide: false });
      const { user, input } = setup();
      await run(user, input);
      await finish(0);
      const scrolled = vi.mocked(Element.prototype.scrollIntoView);
      scrolled.mockClear();
      const evidence = (id: string) => within(turn(1)).getByRole("button", { name: `Evidence for ${id}` });

      await user.click(evidence("R2"));
      expect(within(turn(1)).getByRole("button", { name: /^Transcript/ })).toHaveAttribute("aria-expanded", "true");
      expect(transcriptPane()).toHaveFocus();
      expect(mark("R2")).toHaveAttribute("data-active");
      // the page, not the pane, scrolls below 768 px, so the quote is brought into view through every scrolling ancestor
      expect(scrolled.mock.contexts).toEqual([mark("R2")]);
      expect(scrolled).toHaveBeenCalledWith({ block: "center", behavior: "smooth" });
      expect(document.querySelector('[data-slot="hover-card-content"]')).toBeNull(); // the quote shows in the transcript instead
      expect(evidence("R2").closest("li")).toHaveAttribute("data-active"); // hover and focus have left; the pin stays

      await user.click(evidence("R1"));
      expect(mark("R1")).toHaveAttribute("data-active");
      expect(mark("R2")).not.toHaveAttribute("data-active");

      // a pin made while a turn streams ends with that attempt: a Retry numbers its own requirements
      await run(user, input);
      const partial = frame("partial", { seq: 1, breakdown: { requirements: [{ id: "R1", statement: "Log in", evidence: "patients log in, see their" }], assumptions: [] } });
      streams[1].push(partial);
      await user.click(await within(turn(2)).findByRole("button", { name: "Evidence for R1" }));
      expect(mark("R1", 2)).toHaveAttribute("data-active");
      await user.click(within(turn(2)).getByRole("button", { name: "Stop" }));
      expect(mark("R1", 2)).toHaveAttribute("data-active"); // the stopped attempt keeps its pin
      await user.click(within(turn(2)).getByRole("button", { name: "Retry" }));
      streams[2].push(partial);
      await waitFor(() => expect(mark("R1", 2)).toBeInTheDocument());
      expect(transcriptPane(2).querySelector("mark[data-active]")).toBeNull();
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

    it("below 768 px, Evidence for a quote not found in the transcript shows the model's quote instead of pinning", async () => {
      stubPointer("fine", { wide: false });
      const { user, input } = setup();
      await run(user, input);
      await finish(0); // the grounding report flags R3: no mark to show
      await user.click(screen.getByRole("button", { name: "Evidence for R3" }));
      expect(within(turn(1)).getByRole("button", { name: /^Transcript/ })).toHaveAttribute("aria-expanded", "false");
      await waitFor(() => expect(document.querySelector('[data-slot="hover-card-content"]')).toHaveTextContent("Quote given by the model, not found in the transcript"));
    });

    it("ignores a pin side by side, where hover and focus link requirements to quotes", async () => {
      const resize = viewport(false);
      const { user, input } = setup();
      await run(user, input);
      await finish(0);
      await user.click(screen.getByRole("button", { name: "Evidence for R2" }));
      expect(mark("R2")).toHaveAttribute("data-active");
      resize(true);
      expect(transcriptPane().querySelector("mark[data-active]")).toBeNull();
      expect(screen.getByRole("button", { name: "Evidence for R2" }).closest("li")).not.toHaveAttribute("data-active");
    });
  });

  describe("composer and turn controls", () => {
    // §8 managed focus on a touch screen: never the composer (the keyboard would cover the result), but the new Stop.
    it("on a touch screen, Start new in the confirmation returns focus to New conversation, never into the composer", async () => {
      stubPointer("coarse");
      const { user, input } = setup();
      await run(user, input, "First");
      await user.click(screen.getByRole("button", { name: "New conversation" }));
      await user.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Start new" }));
      await waitFor(() => expect(screen.getByRole("button", { name: "New conversation" })).toHaveFocus());
    });

    it("on a touch screen, moves focus from Estimate to the new Stop without scrolling, never into the composer", async () => {
      stubPointer("coarse");
      const { user, input, estimate } = setup();
      await loaded();
      await user.type(input, "We need a booking portal.");
      const focus = vi.spyOn(HTMLElement.prototype, "focus");
      await user.click(estimate);
      const stop = await within(turn(1)).findByRole("button", { name: "Stop" });
      await waitFor(() => expect(stop).toHaveFocus());
      expect(focus.mock.contexts.at(-1)).toBe(stop);
      expect(focus).toHaveBeenLastCalledWith({ preventScroll: true });
      expect(input).not.toHaveFocus();
      focus.mockRestore();
    });

    it("brings the new turn into view below the sticky header", async () => {
      const { user, input } = setup();
      await run(user, input);
      expect(vi.mocked(Element.prototype.scrollIntoView).mock.contexts).toContain(turn(1));
      expect(turn(1)).toHaveClass("scroll-mt-16");
    });

    it("on a touch screen, Edit transcript still moves focus into the composer (the user asked to edit it)", async () => {
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

    it("keeps focus in the composer after Cmd+Enter, so Esc stops the stream from there", async () => {
      const { user, input } = setup();
      await loaded();
      await user.type(input, "We need a booking portal.");
      await user.keyboard("{Meta>}{Enter}{/Meta}");
      await within(turn(1)).findByRole("button", { name: "Stop" });
      expect(input).toHaveFocus();
      await user.keyboard("{Escape}");
      expect(await within(turn(1)).findByText("Stopped")).toBeInTheDocument();
      expect(turnCalls()[0][1]?.signal?.aborted).toBe(true);
    });

    // The page must not jump when the result arrives: the row that will hold the delta and the view toggle is there,
    // with a placeholder of the toggle's size, while the turn streams.
    it("reserves the result bar's room while a turn streams, and fills the same row when it completes", async () => {
      const { user, input } = setup();
      await run(user, input);
      const bar = turn(1).querySelector('[data-slot="turn-result-bar"]');
      if (!(bar instanceof HTMLElement)) throw new Error("no result bar while streaming");
      expect(bar).toHaveClass("min-h-9");
      expect(bar.querySelector('[data-slot="skeleton"]')).toHaveAttribute("aria-hidden", "true");
      expect(within(bar).queryByRole("radiogroup")).not.toBeInTheDocument();
      await finish(0);
      expect(turn(1).querySelector('[data-slot="turn-result-bar"]')).toBe(bar);
      expect(within(bar).getByRole("radiogroup", { name: "Result view" })).toBeInTheDocument();
      expect(bar.querySelector('[data-slot="skeleton"]')).toBeNull();
    });

    it("switches a completed turn between the structured view and the server's document; each turn starts structured", async () => {
      const narrative = "## Estimation: Booking\n\n**Backend** — 3 tasks, 120.0 h expected (90.0–170.0 h). T3 Booking API: slot checks.\n";
      const { user, input } = setup();
      await run(user, input);
      expect(within(turn(1)).queryByRole("radiogroup", { name: "Result view" })).not.toBeInTheDocument(); // nothing to show as a document yet
      await finish(0, turnResult({ estimation: narrative }));

      expect(within(turn(1)).getByRole("radio", { name: "Structured" })).toBeChecked();
      await user.click(within(turn(1)).getByRole("radio", { name: "Document" }));
      const prose = within(turn(1)).getByText(/3 tasks, 120\.0 h expected/);
      expect(prose.tagName).toBe("P");
      expect(within(turn(1)).queryByRole("table")).not.toBeInTheDocument();

      await run(user, input, "Next");
      await finish(1);
      expect(within(turn(2)).getByRole("radio", { name: "Structured" })).toBeChecked();
      expect(within(turn(1)).getByRole("radio", { name: "Document" })).toBeChecked(); // each turn keeps its own view
    });

    it("checks attachments against the service's limits once its context loads, against the defaults until then", async () => {
      let load!: (res: Response) => void;
      serviceContext = new Promise((resolve) => (load = resolve));
      const { user } = setup();
      expect(screen.getByText("PDF, DOCX or TXT, up to 5 files of 10 MB each")).toBeInTheDocument();
      await act(async () => load(Response.json({ ...context, max_attachments: 2, max_attachment_bytes: 1024 })));
      expect(await screen.findByText("PDF, DOCX or TXT, up to 2 files of 1 KB each")).toBeInTheDocument();
      await attach(user, pdf("a.pdf"), pdf("b.pdf"), pdf("c.pdf"), new File([new Uint8Array(2048)], "big.txt", { type: "text/plain" }));
      expect(within(screen.getByRole("list", { name: "Attached documents" })).getAllByRole("listitem")).toHaveLength(2);
      expect(screen.getByText("c.pdf was not added: up to 2 files per message.")).toBeInTheDocument();
      expect(screen.getByText("big.txt is too large: each file can be up to 1 KB.")).toBeInTheDocument();
    });

    it("caps a raised service limit at the BFF's, so it never offers files the BFF refuses", async () => {
      serviceContext = Promise.resolve(Response.json({ ...context, max_attachments: 8, max_attachment_bytes: 20 * 1024 * 1024 }));
      const { user } = setup();
      await loaded();
      expect(screen.getByText("PDF, DOCX or TXT, up to 5 files of 10 MB each")).toBeInTheDocument();
      await attach(user, ...["a", "b", "c", "d", "e", "f"].map((name) => pdf(`${name}.pdf`)));
      expect(within(screen.getByRole("list", { name: "Attached documents" })).getAllByRole("listitem")).toHaveLength(5);
      expect(screen.getByText("f.pdf was not added: up to 5 files per message.")).toBeInTheDocument();
    });

    it("counts the transcript against 50,000 characters until the service context loads, then against its limit", async () => {
      let load!: (res: Response) => void;
      serviceContext = new Promise((resolve) => (load = resolve));
      setup();
      expect(screen.getByText("0 / 50,000")).toBeInTheDocument();
      await act(async () => load(Response.json({ ...context, max_transcription_chars: 1200 })));
      expect(await screen.findByText("0 / 1,200")).toBeInTheDocument();
    });
  });

  describe("inspector", () => {
    it("opens as a sheet from the header and shows the prompt sessions send: the composer's choices on the session's prompt version", async () => {
      const { user } = setup();
      await loaded();
      await waitFor(() =>
        expect(vi.mocked(fetch)).toHaveBeenCalledWith("/api/context?project_type=web_saas&detail_level=medium&output_format=phases_table&prompt_version=v3", expect.anything()),
      );
      await user.click(screen.getByRole("radio", { name: "Mobile app" }));
      await waitFor(() =>
        expect(vi.mocked(fetch)).toHaveBeenLastCalledWith("/api/context?project_type=mobile_app&detail_level=medium&output_format=phases_table&prompt_version=v3", expect.anything()),
      );
      expect(screen.queryByRole("complementary", { name: "Inspector" })).not.toBeInTheDocument(); // the right column holds the memory
      // never the service default's prompt first: nothing is asked until the session's version is known
      const promptCalls = vi.mocked(fetch).mock.calls.map(([url]) => String(url)).filter((url) => url.startsWith("/api/context?"));
      expect(promptCalls.every((url) => url.endsWith("prompt_version=v3"))).toBe(true);
      expect(await inspector(user, "Context")).toContain(context.system_prompt);
    });

    it("shows the last completed turn's call; a turn that is streaming or stopped does not replace it", async () => {
      const { user, input } = setup();
      expect(await inspector(user, "Last call")).toContain("Run an estimate to see its metrics.");

      await run(user, input);
      expect(await inspector(user, "Last call")).toContain("Run an estimate to see its metrics."); // still streaming
      await finish(0);
      expect(await inspector(user, "Last call")).toContain("req-1");

      await run(user, input, "Second");
      await user.click(within(turn(2)).getByRole("button", { name: "Stop" }));
      expect(await inspector(user, "Last call")).toContain("req-1");

      await user.click(within(turn(2)).getByRole("button", { name: "Retry" }));
      await finish(2, turnResult({ model: "gpt-4o", history_turns: 2 }), 2);
      expect(await inspector(user, "Last call")).toContain("req-3");
    });

    it("counts the inspector's last call from the latest result, even one React has not rendered yet", async () => {
      const { user, input, estimate } = setup();
      await run(user, input);
      await user.type(input, "Next turn");
      await act(async () => {
        streams[0].push(frame("result", turnResult()));
        await new Promise((resolve) => setTimeout(resolve, 0)); // the stream applies `result`; act holds the render
        fireEvent.click(estimate); // the last render still says "streaming"
        await new Promise((resolve) => setTimeout(resolve, 0));
      });
      await waitFor(() => expect(turnCalls()).toHaveLength(2));
      expect(await inspector(user, "Last call")).toContain("req-1");
    });
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
