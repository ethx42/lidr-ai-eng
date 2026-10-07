import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRef } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ServiceContextProvider } from "@/components/service-context";
import { useDraft } from "@/hooks/use-draft";
import type { Sample } from "@/lib/samples";
import { stubPointer } from "@/test/pointer";
import { Composer } from "./composer";

const SAMPLES: Sample[] = [
  { id: "course-meeting", title: "Course meeting", description: "Fitness studios, detailed call", text: "Laura: We run four fitness studios." },
  { id: "clinic-portal", title: "Clinic portal", description: "Patient portal, medium scope", text: "Sofía: We have three physiotherapy clinics.\nTomás: Where do appointments live?" },
];

const context = (max: number) => ({ prompt_version: "v1", system_prompt: "", references: [], chain: ["replay:gpt-4o-mini"], max_transcription_chars: max });

const Harness = ({ onSend }: { onSend: () => void }) => {
  const draft = useDraft();
  const inputRef = useRef<HTMLTextAreaElement>(null);
  return (
    <ServiceContextProvider>
      <Composer inputRef={inputRef} draft={draft} onSend={onSend} samples={SAMPLES} />
    </ServiceContextProvider>
  );
};

describe("Composer", () => {
  let resolveContext: (value: Response) => void;

  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(() => new Promise((resolve) => { resolveContext = resolve; })));
    stubPointer("fine");
  });
  afterEach(() => vi.unstubAllGlobals());

  const setup = () => {
    const onSend = vi.fn();
    const user = userEvent.setup();
    render(<Harness onSend={onSend} />);
    return { onSend, user, input: screen.getByRole("textbox", { name: "Meeting transcript" }), send: screen.getByRole("button", { name: "Estimate" }) };
  };
  const loadLimit = async (max: number) => {
    await act(async () => resolveContext(Response.json(context(max))));
    await waitFor(() => expect(screen.getByText(new RegExp(` / ${max.toLocaleString("en-US")}$`))).toBeInTheDocument());
  };

  it("sends on Cmd+Enter and Ctrl+Enter; Enter alone inserts a newline", async () => {
    const { onSend, user, input } = setup();
    await user.type(input, "Line one{Enter}Line two");
    expect(input).toHaveValue("Line one\nLine two");
    expect(onSend).not.toHaveBeenCalled();

    await user.keyboard("{Meta>}{Enter}{/Meta}");
    expect(onSend).toHaveBeenCalledTimes(1);
    await user.keyboard("{Control>}{Enter}{/Control}");
    expect(onSend).toHaveBeenCalledTimes(2);
    expect(input).toHaveValue("Line one\nLine two"); // the shortcut never adds a newline
  });

  it("ignores Cmd/Ctrl+Enter while an IME composition is active", async () => {
    const { onSend, user, input } = setup();
    await user.type(input, "Reunión");
    fireEvent.keyDown(input, { key: "Enter", metaKey: true, isComposing: true });
    fireEvent.keyDown(input, { key: "Enter", ctrlKey: true, keyCode: 229 }); // Safari ends the composition before this keydown
    expect(onSend).not.toHaveBeenCalled();
    fireEvent.keyDown(input, { key: "Enter", ctrlKey: true });
    expect(onSend).toHaveBeenCalledTimes(1);
  });

  it("sends from the button", async () => {
    const { onSend, user, input, send } = setup();
    await user.type(input, "We need a booking portal.");
    await user.click(send);
    expect(onSend).toHaveBeenCalledTimes(1);
  });

  it("disables Send while the transcript is empty or blank, and says why", async () => {
    const { onSend, user, input, send } = setup();
    expect(send).toBeDisabled();
    expect(send).toHaveAccessibleDescription("Paste or type a transcript to estimate.");
    expect(screen.getByText("Paste or type a transcript to estimate.")).toHaveClass("sr-only"); // the placeholder already shows it

    await user.type(input, "   ");
    expect(send).toBeDisabled();
    await user.keyboard("{Meta>}{Enter}{/Meta}");
    expect(onSend).not.toHaveBeenCalled();

    await user.type(input, "Hi");
    expect(send).toBeEnabled();
    expect(screen.queryByText("Paste or type a transcript to estimate.")).not.toBeInTheDocument();
  });

  it("counts characters against 50,000 until the context loads, then against its limit", async () => {
    const { user, input } = setup();
    expect(screen.getByText("0 / 50,000")).toBeInTheDocument();
    await user.type(input, "  Hello 👋  "); // trimmed and counted in code points, as the AI service counts
    expect(screen.getByText("7 / 50,000")).toBeInTheDocument();
    expect(input).toHaveAccessibleDescription(/7 \/ 50,000 characters/);

    await loadLimit(1200);
    expect(screen.getByText("7 / 1,200")).toBeInTheDocument();
  });

  it("turns the counter to the warning colour above 90 % of the limit", async () => {
    const { user, input, send } = setup();
    await loadLimit(10);
    await user.type(input, "123456789");
    expect(screen.getByText("9 / 10")).not.toHaveClass("text-warning");
    await user.type(input, "0");
    expect(screen.getByText("10 / 10")).toHaveClass("text-warning");
    expect(send).toBeEnabled(); // exactly at the limit is still accepted
  });

  it("disables Send over the limit and asks to shorten the transcript, announcing it only when crossing", async () => {
    const { onSend, user, input, send } = setup();
    await loadLimit(10);
    const status = screen.getByRole("status");
    await user.type(input, "12345678901");
    expect(send).toBeDisabled();
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(status).toHaveTextContent("Shorten the transcript to send it.");
    expect(screen.getByText("It is 1 character over the limit.")).toBeInTheDocument();
    expect(send).toHaveAccessibleDescription("Shorten the transcript to send it. It is 1 character over the limit.");
    await user.keyboard("{Control>}{Enter}{/Control}");
    expect(onSend).not.toHaveBeenCalled();

    const announced = status.firstChild;
    await user.type(input, "2");
    expect(screen.getByText("It is 2 characters over the limit.")).toBeInTheDocument();
    expect(status.firstChild).toBe(announced); // the live region did not change, so nothing is re-announced

    await user.type(input, "{Backspace}{Backspace}");
    expect(send).toBeEnabled();
    expect(status).toBeEmptyDOMElement();
  });

  const pickSample = async (user: ReturnType<typeof userEvent.setup>, name: RegExp) => {
    await user.click(screen.getByRole("button", { name: "Samples" }));
    await user.click(await screen.findByRole("menuitem", { name }));
  };

  it("inserts a picked sample into an empty composer without sending it", async () => {
    const { onSend, user, input } = setup();
    await pickSample(user, /Clinic portal/);
    expect(input).toHaveValue(SAMPLES[1].text);
    await waitFor(() => expect(input).toHaveFocus());
    expect(onSend).not.toHaveBeenCalled();
  });

  it("asks before replacing a draft with a sample, and keeps the draft unless confirmed", async () => {
    const { onSend, user, input } = setup();
    await user.type(input, "My notes");
    await pickSample(user, /Clinic portal/);
    const confirm = screen.getByRole("group", { name: "Replace your draft with the “Clinic portal” sample?" });
    const keep = within(confirm).getByRole("button", { name: "Keep my draft" });
    await waitFor(() => expect(keep).toHaveFocus());
    expect(input).toHaveValue("My notes");

    await user.click(keep);
    expect(input).toHaveValue("My notes");
    expect(input).toHaveFocus();
    expect(screen.queryByRole("group")).not.toBeInTheDocument();

    await pickSample(user, /Clinic portal/);
    await user.click(screen.getByRole("button", { name: "Replace draft" }));
    expect(input).toHaveValue(SAMPLES[1].text);
    expect(input).toHaveFocus();
    expect(onSend).not.toHaveBeenCalled();
  });

  it("on a touch screen, leaves the transcript unfocused after a pick or an answer (Samples keeps focus)", async () => {
    stubPointer("coarse");
    const { user, input } = setup();
    await pickSample(user, /Clinic portal/);
    expect(input).toHaveValue(SAMPLES[1].text);
    await waitFor(() => expect(screen.getByRole("button", { name: "Samples" })).toHaveFocus());

    await pickSample(user, /Course meeting/);
    await user.click(await screen.findByRole("button", { name: "Replace draft" }));
    expect(input).toHaveValue(SAMPLES[0].text);
    expect(input).not.toHaveFocus();
  });

  it("keeps the draft on Escape, without the key reaching the stream's Stop shortcut", async () => {
    const { user, input } = setup();
    await user.type(input, "My notes");
    await pickSample(user, /Course meeting/);
    const keep = screen.getByRole("button", { name: "Keep my draft" });
    await waitFor(() => expect(keep).toHaveFocus());
    let reachedDocument: boolean | undefined;
    const listener = (event: KeyboardEvent) => (reachedDocument = event.defaultPrevented);
    document.addEventListener("keydown", listener);
    await user.keyboard("{Escape}");
    document.removeEventListener("keydown", listener);
    expect(reachedDocument).toBe(true); // handled: a document listener sees defaultPrevented
    expect(input).toHaveValue("My notes");
    expect(input).toHaveFocus();
    expect(screen.queryByRole("group")).not.toBeInTheDocument();
  });
});
