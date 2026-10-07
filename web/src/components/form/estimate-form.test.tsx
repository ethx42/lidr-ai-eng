import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createRef } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Sample } from "@/lib/samples";
import { press } from "@/test/keyboard";
import { stubPointer } from "@/test/pointer";
import { EstimateForm, type EstimateFormHandle } from "./estimate-form";

describe("EstimateForm", () => {
  it("submits typed params with brief enum values", async () => {
    const onSubmit = vi.fn();
    render(<EstimateForm onSubmit={onSubmit} versions={["v1", "v2"]} defaultVersion="v2" />);
    await userEvent.type(screen.getByRole("textbox", { name: /transcript/i }), "Client: we need a booking app for our studios.");
    await userEvent.click(screen.getByRole("radio", { name: /mobile app/i }));
    await userEvent.click(screen.getByRole("radio", { name: /detailed/i }));
    await userEvent.click(screen.getByRole("button", { name: /estimate/i }));
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ project_type: "mobile_app", detail_level: "detailed", output_format: "phases_table" }),
      { promptVersion: "v2" },
    );
  });
  it("blocks submit and explains when the transcript is empty", async () => {
    const onSubmit = vi.fn();
    render(<EstimateForm onSubmit={onSubmit} versions={["v1"]} defaultVersion="v1" />);
    await userEvent.click(screen.getByRole("button", { name: /estimate/i }));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByText(/paste or upload a transcript/i)).toBeVisible();
  });
});

const SAMPLES: Sample[] = [
  { id: "course-meeting", title: "Course meeting", description: "Fitness studios, detailed call", text: "Laura: We run four fitness studios." },
  { id: "clinic-portal", title: "Clinic portal", description: "Patient portal, medium scope", text: "Sofía: We have three physiotherapy clinics.\nTomás: Where do appointments live?" },
];
const EMPTY = "Paste or upload a transcript to estimate.";

describe("EstimateForm in detail", () => {
  beforeEach(() => stubPointer("fine"));
  afterEach(() => vi.unstubAllGlobals());

  const setup = ({ maxChars, versions = ["v1", "v2"], defaultVersion = "v1" }: { maxChars?: number; versions?: string[]; defaultVersion?: string } = {}) => {
    const onSubmit = vi.fn();
    const onParamsChange = vi.fn();
    const handle = createRef<EstimateFormHandle>();
    const user = userEvent.setup({ applyAccept: false });
    const props = { onSubmit, onParamsChange, samples: SAMPLES, handle, versions, defaultVersion };
    const view = render(<EstimateForm {...props} maxChars={maxChars} />);
    const rerender = (next: { maxChars?: number; versions?: string[]; defaultVersion?: string }) => view.rerender(<EstimateForm {...props} {...next} />);
    return {
      onSubmit,
      onParamsChange,
      handle,
      user,
      rerender,
      input: screen.getByRole("textbox", { name: "Transcript" }),
      estimate: screen.getByRole("button", { name: "Estimate" }),
    };
  };
  const body = (transcription: string, params = {}) => [
    { transcription, project_type: "web_saas", detail_level: "medium", output_format: "phases_table", ...params },
    { promptVersion: "v1" },
  ];

  it("defaults to a web SaaS at medium detail in a phases table, sending no output language", async () => {
    const { onSubmit, user, input, estimate } = setup();
    for (const [group, value] of [["Project type", "Web SaaS"], ["Detail level", "Medium"], ["Output format", "Phases table"]]) {
      expect(within(screen.getByRole("radiogroup", { name: group })).getByRole("radio", { checked: true })).toHaveAccessibleName(value);
    }
    // on a phone the four project types sit in two even rows; three options fit one row
    expect(screen.getByRole("radiogroup", { name: "Project type" })).toHaveClass("max-sm:grid", "max-sm:grid-cols-2");
    expect(screen.getByRole("radiogroup", { name: "Detail level" })).not.toHaveClass("max-sm:grid");
    await user.type(input, "  We need a booking portal.\n");
    await user.click(estimate);
    expect(onSubmit).toHaveBeenCalledWith(...body("We need a booking portal."));
    expect(Object.keys(onSubmit.mock.calls[0][0])).not.toContain("output_language");
    expect(input).toHaveValue("  We need a booking portal.\n"); // the form keeps the transcript for the next run
  });

  it("keeps one option chosen in each group (clicking the chosen one again keeps it) and reports changes", async () => {
    const { onSubmit, onParamsChange, user, input, estimate } = setup();
    const narrative = screen.getByRole("radio", { name: "Narrative" });
    await user.click(narrative);
    expect(onParamsChange).toHaveBeenLastCalledWith({ project_type: "web_saas", detail_level: "medium", output_format: "narrative", prompt_version: "" });
    await user.click(narrative);
    expect(narrative).toBeChecked();
    expect(onParamsChange).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole("radio", { name: "Data pipeline" }));
    await user.click(screen.getByRole("radio", { name: "Summary" }));
    await user.type(input, "Nightly sync.");
    await user.click(estimate);
    expect(onSubmit).toHaveBeenCalledWith(...body("Nightly sync.", { project_type: "data_pipeline", detail_level: "summary", output_format: "narrative" }));
  });

  // The ARIA radio group pattern: an arrow key moves focus and checks, as with native radios, so the option a screen
  // reader announces as focused is the value the estimate runs with.
  it("checks the option an arrow key moves to, and reports it", async () => {
    const { onParamsChange, user } = setup();
    act(() => screen.getByRole("radio", { name: "Medium" }).focus());
    await press(user, "ArrowRight");
    const detailed = screen.getByRole("radio", { name: "Detailed" });
    expect(detailed).toHaveFocus();
    expect(detailed).toBeChecked();
    expect(onParamsChange).toHaveBeenLastCalledWith({ project_type: "web_saas", detail_level: "detailed", output_format: "phases_table", prompt_version: "" });
    await press(user, "ArrowLeft");
    expect(screen.getByRole("radio", { name: "Medium" })).toBeChecked();
  });

  it("keeps the prompt version behind Advanced, defaulting to the service's version until one is picked", async () => {
    const { onSubmit, onParamsChange, user, input, estimate, rerender } = setup({ versions: [], defaultVersion: "" });
    const advanced = screen.getByRole("button", { name: "Advanced" });
    expect(advanced).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("combobox", { name: "Prompt version" })).not.toBeInTheDocument();
    await user.type(input, "Hi");
    await user.click(estimate);
    expect(onSubmit).toHaveBeenLastCalledWith(expect.anything(), { promptVersion: "" }); // unknown yet: the service's default

    rerender({ versions: ["v1", "v2"], defaultVersion: "v2" });
    await user.click(advanced);
    expect(advanced).toHaveAttribute("aria-expanded", "true");
    const select = screen.getByRole("combobox", { name: "Prompt version" });
    expect(select).toHaveValue("v2");
    expect(within(select).getAllByRole("option").map((option) => option.textContent)).toEqual(["v1", "v2"]);
    await user.click(estimate);
    expect(onSubmit).toHaveBeenLastCalledWith(expect.anything(), { promptVersion: "v2" });

    await user.selectOptions(select, "v1");
    expect(onParamsChange).toHaveBeenLastCalledWith(expect.objectContaining({ prompt_version: "v1" }));
    await user.click(estimate);
    expect(onSubmit).toHaveBeenLastCalledWith(expect.anything(), { promptVersion: "v1" });
  });

  it("submits on Cmd+Enter and Ctrl+Enter; Enter alone inserts a newline", async () => {
    const { onSubmit, user, input } = setup();
    await user.type(input, "Line one{Enter}Line two");
    expect(input).toHaveValue("Line one\nLine two");
    expect(onSubmit).not.toHaveBeenCalled();

    await user.keyboard("{Meta>}{Enter}{/Meta}");
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    await user.keyboard("{Control>}{Enter}{/Control}");
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(2));
    expect(input).toHaveValue("Line one\nLine two"); // the shortcut never adds a newline
    expect(input).toHaveFocus();
  });

  it("ignores Cmd/Ctrl+Enter while an IME composition is active", async () => {
    const { onSubmit, user, input } = setup();
    await user.type(input, "Reunión");
    fireEvent.keyDown(input, { key: "Enter", metaKey: true, isComposing: true });
    fireEvent.keyDown(input, { key: "Enter", ctrlKey: true, keyCode: 229 }); // Safari ends the composition before this keydown
    await act(async () => {});
    expect(onSubmit).not.toHaveBeenCalled();
    fireEvent.keyDown(input, { key: "Enter", ctrlKey: true });
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
  });

  it("explains an empty or blank transcript inline, on the field, and clears the message once there is text", async () => {
    const { onSubmit, user, input, estimate } = setup();
    expect(estimate).toBeEnabled();
    expect(screen.queryByText(EMPTY)).not.toBeInTheDocument();
    await user.type(input, "   ");
    await user.click(estimate);
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(EMPTY);
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAccessibleDescription(expect.stringContaining(EMPTY));
    expect(input).toHaveFocus();

    await user.type(input, "Hi");
    await waitFor(() => expect(screen.queryByText(EMPTY)).not.toBeInTheDocument());
    expect(input).not.toHaveAttribute("aria-invalid");
  });

  it("counts characters against 50,000 until a limit is given, then against it", async () => {
    const { user, input, rerender } = setup();
    expect(screen.getByText("0 / 50,000")).toBeInTheDocument();
    await user.type(input, "  Hello 👋  "); // trimmed and counted in code points, as the AI service counts
    expect(screen.getByText("7 / 50,000")).toBeInTheDocument();
    expect(input).toHaveAccessibleDescription(/7 \/ 50,000 characters/);

    rerender({ maxChars: 1200 });
    expect(screen.getByText("7 / 1,200")).toBeInTheDocument();
  });

  it("turns the counter to the warning colour above 90 % of the limit", async () => {
    const { onSubmit, user, input, estimate } = setup({ maxChars: 10 });
    await user.type(input, "123456789");
    expect(screen.getByText("9 / 10")).not.toHaveClass("text-warning");
    await user.type(input, "0");
    expect(screen.getByText("10 / 10")).toHaveClass("text-warning");
    await user.click(estimate);
    expect(onSubmit).toHaveBeenCalledTimes(1); // exactly at the limit is still accepted
  });

  it("blocks submit over the limit and asks to shorten the transcript, announcing it only when crossing", async () => {
    const { onSubmit, user, input, estimate } = setup({ maxChars: 10 });
    const status = screen.getByRole("status");
    await user.type(input, "12345678901");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(status).toHaveTextContent("Shorten the transcript to estimate it.");
    expect(screen.getByText("It is 1 character over the limit.")).toBeInTheDocument();
    expect(estimate).toHaveAccessibleDescription("Shorten the transcript to estimate it. It is 1 character over the limit.");
    await user.click(estimate);
    await user.keyboard("{Control>}{Enter}{/Control}");
    await act(async () => {});
    expect(onSubmit).not.toHaveBeenCalled();
    expect(input).toHaveFocus(); // the attempt lands on the field to shorten

    const announced = status.firstChild;
    await user.type(input, "2");
    expect(screen.getByText("It is 2 characters over the limit.")).toBeInTheDocument();
    expect(status.firstChild).toBe(announced); // the live region did not change, so nothing is re-announced

    await user.type(input, "{Backspace}{Backspace}");
    expect(status).toBeEmptyDOMElement();
    expect(estimate).not.toHaveAccessibleDescription();
    await user.click(estimate);
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  const pickSample = async (user: ReturnType<typeof userEvent.setup>, name: RegExp) => {
    await user.click(screen.getByRole("button", { name: "Load sample" }));
    await user.click(await screen.findByRole("menuitem", { name }));
  };

  it("inserts a picked sample into an empty transcript without submitting it", async () => {
    const { onSubmit, user, input } = setup();
    await pickSample(user, /Clinic portal/);
    expect(input).toHaveValue(SAMPLES[1].text);
    await waitFor(() => expect(input).toHaveFocus());
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("asks before replacing a draft with a sample, and keeps the draft unless confirmed", async () => {
    const { onSubmit, user, input } = setup();
    await user.type(input, "My notes");
    await pickSample(user, /Clinic portal/);
    const confirm = screen.getByRole("group", { name: "Replace your draft with the “Clinic portal” sample?" });
    const keep = within(confirm).getByRole("button", { name: "Keep my draft" });
    await waitFor(() => expect(keep).toHaveFocus());
    expect(input).toHaveValue("My notes");

    await user.click(keep);
    expect(input).toHaveValue("My notes");
    expect(input).toHaveFocus();
    expect(screen.queryByRole("group", { name: /Replace your draft/ })).not.toBeInTheDocument();

    await pickSample(user, /Clinic portal/);
    await user.click(screen.getByRole("button", { name: "Replace draft" }));
    expect(input).toHaveValue(SAMPLES[1].text);
    expect(input).toHaveFocus();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("on a touch screen, leaves the transcript unfocused after a pick or an answer (Load sample keeps focus)", async () => {
    stubPointer("coarse");
    const { user, input } = setup();
    await pickSample(user, /Clinic portal/);
    expect(input).toHaveValue(SAMPLES[1].text);
    await waitFor(() => expect(screen.getByRole("button", { name: "Load sample" })).toHaveFocus());

    await pickSample(user, /Course meeting/);
    await user.click(await screen.findByRole("button", { name: "Replace draft" }));
    expect(input).toHaveValue(SAMPLES[0].text);
    expect(input).not.toHaveFocus();
  });

  // §8 managed focus: the question's buttons go away with the answer, and focus must not fall to the page.
  it("on a touch screen, an answer to the replace question moves focus to Load sample, not to the page", async () => {
    stubPointer("coarse");
    const { user, input } = setup();
    const samples = screen.getByRole("button", { name: "Load sample" });
    await user.type(input, "My notes");
    await pickSample(user, /Clinic portal/);
    await waitFor(() => expect(screen.getByRole("button", { name: "Keep my draft" })).toHaveFocus());
    await user.click(screen.getByRole("button", { name: "Keep my draft" }));
    expect(input).toHaveValue("My notes");
    expect(samples).toHaveFocus();

    await pickSample(user, /Clinic portal/);
    await user.click(await screen.findByRole("button", { name: "Replace draft" }));
    expect(input).toHaveValue(SAMPLES[1].text);
    expect(samples).toHaveFocus();

    await user.type(input, " and more");
    await pickSample(user, /Course meeting/);
    await waitFor(() => expect(screen.getByRole("button", { name: "Keep my draft" })).toHaveFocus());
    await user.keyboard("{Escape}");
    expect(samples).toHaveFocus();
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
    expect(screen.queryByRole("group", { name: /Replace your draft/ })).not.toBeInTheDocument();
  });

  const fileInput = () => {
    const input = document.querySelector('input[type="file"]');
    if (!(input instanceof HTMLInputElement)) throw new Error("no file input");
    return input;
  };

  it("loads a .txt file into the transcript from Upload .txt, asking first when it would replace a draft", async () => {
    const { onSubmit, user, input } = setup();
    const upload = screen.getByRole("button", { name: "Upload .txt" });
    const click = vi.spyOn(fileInput(), "click");
    await user.click(upload);
    expect(click).toHaveBeenCalled();
    expect(fileInput()).toHaveAttribute("accept", ".txt,text/plain");

    await user.upload(fileInput(), new File(["Ana: We need a client portal."], "kickoff.txt", { type: "text/plain" }));
    await waitFor(() => expect(input).toHaveValue("Ana: We need a client portal."));
    expect(input).toHaveFocus();

    await user.type(input, " Edited.");
    await user.upload(fileInput(), new File(["Second call."], "follow-up.txt", { type: "" })); // some systems send no type
    const confirm = await screen.findByRole("group", { name: "Replace your draft with the file “follow-up.txt”?" });
    await user.click(within(confirm).getByRole("button", { name: "Replace draft" }));
    expect(input).toHaveValue("Second call.");
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("refuses a file that is not .txt, or too large to fit the limit, with an inline message", async () => {
    const { user, input } = setup({ maxChars: 10 });
    await user.upload(fileInput(), new File(["%PDF"], "notes.pdf", { type: "application/pdf" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("“notes.pdf” is not a .txt file. Choose a plain text file.");
    expect(input).toHaveValue("");

    await user.upload(fileInput(), new File(["x".repeat(41)], "long.txt", { type: "text/plain" })); // over 4 bytes per allowed character
    expect(await screen.findByRole("alert")).toHaveTextContent("“long.txt” is too large: a transcript holds at most 10 characters.");
    expect(input).toHaveValue("");
  });

  it("puts a rejected transcript back for editing on any pointer, asking first when the draft changed", async () => {
    stubPointer("coarse");
    const { handle, user, input } = setup();
    act(() => handle.current?.edit("A very long transcript"));
    expect(input).toHaveValue("A very long transcript");
    expect(input).toHaveFocus(); // the user asked to edit it, so even a touch screen opens the keyboard

    await user.clear(input);
    await user.type(input, "Something else");
    act(() => handle.current?.edit("A very long transcript"));
    expect(screen.getByRole("group", { name: "Replace your draft with the transcript to shorten?" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Keep my draft" })).toHaveFocus());
    expect(input).toHaveValue("Something else");
  });
});
