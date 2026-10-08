import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { components } from "@/lib/ai-service/schema";
import { breakdown, cleanGrounding, fullEstimate, fullResponse, groundingWithIssues, partials } from "@/lib/estimate/fixtures";
import type { PartialBreakdown, StreamState } from "@/lib/estimate/types";
import { EstimateView } from "./estimate-view";
import { StatusSteps } from "./status-steps";

// Unchecked wire data, as the stream hook delivers it: only the top level is known to be an object.
const wire = (json: string): PartialBreakdown => JSON.parse(json);
const wireGrounding = (json: string): components["schemas"]["GroundingReport"] => JSON.parse(json);

const closest = (element: Element, selector: string) => {
  const found = element.closest(selector);
  if (!(found instanceof HTMLElement)) throw new Error(`no ${selector} around ${element.textContent}`);
  return found;
};
const sectionOf = (title: string) => closest(screen.getByRole("heading", { level: 4, name: title }), "section");
const rowOf = (text: string) => closest(screen.getByText(text), "tr");
const requirementOf = (id: string) => closest(within(sectionOf("Requirements")).getByText(id), "li");
const totalsStrip = () => closest(screen.getByText("Expected", { selector: "dt" }), "dl");
const skeletonsIn = (element: Element) => element.querySelectorAll('[data-slot="skeleton"]');
const phaseHeaders = (element: Element) => [...element.querySelectorAll('th[scope="rowgroup"]')].map((th) => th.textContent);
// A task's row header is named by its task name only (not its rationale), so that is what cells announce.
const taskHeaders = (element: Element) =>
  [...element.querySelectorAll('th[scope="row"]')].map((th) => document.getElementById(th.getAttribute("aria-labelledby") ?? "")?.textContent);
const liveRegions = (element: Element) => element.querySelectorAll('[aria-live], [role="status"], [role="alert"], [role="log"]');

const SECTIONS = ["Summary", "Requirements", "Assumptions", "Open questions", "Tasks", "Team", "Risks", "Confidence"];

describe("EstimateView with the final estimate", () => {
  it("renders the project name as the only h3 and one h4 per section in schema order (the turn's label is the h2)", () => {
    render(<EstimateView data={fullEstimate} streaming={false} />);
    expect(screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent)).toEqual(["Physiotherapy patient portal"]);
    expect(screen.getAllByRole("heading", { level: 4 }).map((h) => h.textContent)).toEqual(SECTIONS);
  });

  it("pins the totals strip under the title: expected hours, range, duration and cost", () => {
    render(<EstimateView data={fullEstimate} streaming={false} />);
    const strip = totalsStrip();
    const title = screen.getByRole("heading", { level: 3 });
    expect(title.compareDocumentPosition(strip) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(strip.compareDocumentPosition(screen.getByRole("heading", { name: "Summary" })) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    for (const value of ["95 h", "62–144 h", "1–2 weeks", "$5,700"]) expect(within(strip).getByText(value)).toBeInTheDocument();
    expect(skeletonsIn(strip)).toHaveLength(0);
  });

  it("omits the cost when the estimate has no hourly rate", () => {
    render(<EstimateView data={{ ...fullEstimate, totals: { ...fullEstimate.totals, hourly_rate: null, estimated_cost: null } }} streaming={false} />);
    expect(within(totalsStrip()).queryByText("Cost")).not.toBeInTheDocument();
    expect(within(totalsStrip()).getByText("95 h")).toBeInTheDocument();
  });

  it("shows each requirement's evidence in a hover card that keyboard focus opens", async () => {
    render(<EstimateView data={fullEstimate} streaming={false} />);
    const evidence = breakdown.requirements[0].evidence;
    const trigger = screen.getByRole("button", { name: "Evidence for R1" });
    expect(trigger).toHaveAccessibleDescription(`“${evidence}”`);
    act(() => trigger.focus());
    await waitFor(() => expect(document.querySelector('[data-slot="hover-card-content"]')).toHaveTextContent(evidence));
  });

  it("groups tasks by phase and draws optimistic, likely and pessimistic hours as a range bar", () => {
    render(<EstimateView data={fullEstimate} streaming={false} />);
    const tasks = sectionOf("Tasks");
    expect(phaseHeaders(tasks)).toEqual(["Discovery", "Integrations", "Backend", "Frontend", "QA"]);
    const integrations = closest(within(tasks).getByText("Integrations", { selector: 'th[scope="rowgroup"]' }), "tbody");
    expect(within(integrations).getByText("ClinicCloud integration")).toBeInTheDocument();
    expect(within(integrations).getByText("Email reminders")).toBeInTheDocument();
    for (const task of breakdown.tasks) expect(within(rowOf(task.name)).getByRole("rowheader", { name: task.name })).toBeInTheDocument();
    const row = rowOf("Booking and cancellation API");
    expect(within(row).getByRole("img", { name: "Optimistic 8 h, likely 12 h, pessimistic 20 h" })).toBeInTheDocument();
    expect(within(row).getByText("12.5 h")).toBeInTheDocument();
  });

  it("shows team, risks with impact badges, open questions and confidence with its rationale", () => {
    render(<EstimateView data={fullEstimate} streaming={false} />);
    const team = within(sectionOf("Team"));
    expect(closest(team.getByText("Full-stack developer"), "li")).toHaveTextContent("2");
    const risks = within(sectionOf("Risks"));
    expect(closest(risks.getByText("High impact"), "li")).toHaveTextContent("The ClinicCloud API documentation may be incomplete.");
    expect(closest(risks.getByText("Medium impact"), "li")).toHaveTextContent("Plan a data protection review.");
    const questions = within(sectionOf("Open questions"));
    for (const question of breakdown.open_questions) expect(questions.getByText(question)).toBeInTheDocument();
    const confidence = within(sectionOf("Confidence"));
    expect(confidence.getByText("Medium confidence")).toBeInTheDocument();
    expect(confidence.getByText(breakdown.confidence_rationale)).toBeInTheDocument();
  });

  it("says a list is empty once the estimate is final, but keeps a skeleton while it may still grow", () => {
    const data = { ...fullEstimate, open_questions: [], risks: [] };
    const { rerender } = render(<EstimateView data={data} streaming />);
    expect(sectionOf("Open questions").querySelector('[data-skeleton="list"]')).toBeInTheDocument();
    rerender(<EstimateView data={data} streaming={false} />);
    expect(within(sectionOf("Open questions")).getByText("No open questions.")).toBeInTheDocument();
    expect(within(sectionOf("Risks")).getByText("No risks identified.")).toBeInTheDocument();
  });
});

describe("EstimateView with partial snapshots", () => {
  it.each(Object.entries(partials))("renders the %s snapshot without throwing", (_name, data) => {
    render(<EstimateView data={data} streaming />);
    expect(screen.getAllByRole("heading", { level: 3 })).toHaveLength(1);
    expect(screen.getAllByRole("heading", { level: 4 }).map((h) => h.textContent)).toEqual(SECTIONS);
  });

  it("renders sections not yet received as skeletons shaped like the final section", () => {
    render(<EstimateView data={partials.empty} streaming />);
    const shapes: Record<string, string> = {
      Summary: "paragraph",
      Requirements: "list",
      Assumptions: "list",
      "Open questions": "list",
      Tasks: "table",
      Team: "list",
      Risks: "list",
      Confidence: "paragraph",
    };
    for (const [title, shape] of Object.entries(shapes)) expect(sectionOf(title).querySelector(`[data-skeleton="${shape}"]`)).toBeInTheDocument();
  });

  it("shows the project name as soon as it arrives", () => {
    render(<EstimateView data={partials.projectNameOnly} streaming />);
    expect(screen.getByRole("heading", { level: 3, name: "Yo" })).toBeInTheDocument();
  });

  it("shows skeleton cells for a task whose hours have not arrived", () => {
    render(<EstimateView data={partials.taskWithoutHours} streaming />);
    const row = rowOf("Back");
    expect(within(row).queryByRole("img")).not.toBeInTheDocument();
    expect(skeletonsIn(row).length).toBeGreaterThanOrEqual(2);
  });

  it("shows skeletons for a requirement that only has an id", () => {
    render(<EstimateView data={partials.requirementIdOnly} streaming />);
    const requirement = requirementOf("R1");
    expect(skeletonsIn(requirement).length).toBeGreaterThanOrEqual(2);
    expect(within(requirement).queryByRole("button")).not.toBeInTheDocument();
  });

  it("keeps the totals strip and expected hours as skeletons until the final result", () => {
    render(<EstimateView data={breakdown} streaming />);
    const strip = totalsStrip();
    expect(within(strip).getByText("Range")).toBeInTheDocument();
    expect(within(strip).getByText("Duration")).toBeInTheDocument();
    expect(within(strip).queryByText(/ h$/)).not.toBeInTheDocument();
    expect(skeletonsIn(strip)).toHaveLength(3);
    const row = rowOf("Booking and cancellation API");
    expect(within(row).getByRole("img", { name: "Optimistic 8 h, likely 12 h, pessimistic 20 h" })).toBeInTheDocument();
    expect(within(row).queryByText("12.5 h")).not.toBeInTheDocument();
    expect(skeletonsIn(row)).toHaveLength(1);
  });

  it("keeps a task in the last group until its phase arrives, and only appends groups while streaming", () => {
    const [t1, t2, t3, t4] = breakdown.tasks.map(({ id, phase, name }) => ({ id, phase, name }));
    const { container, rerender } = render(<EstimateView data={{ tasks: [t1, t2, { id: t3.id }] }} streaming />);
    expect(phaseHeaders(container)).toEqual(["Discovery", "Integrations"]);
    expect(container.querySelectorAll("tbody")[1].querySelectorAll("tr")).toHaveLength(3); // header, T2, phase-less T3
    rerender(<EstimateView data={{ tasks: [t1, t2, t3] }} streaming />);
    expect(phaseHeaders(container)).toEqual(["Discovery", "Integrations", "Backend"]);
    expect(taskHeaders(container)).toEqual([t1.name, t2.name, t3.name]);
    // A task returning to an earlier phase is appended while streaming and regrouped once the estimate is final.
    const back: Partial<components["schemas"]["Task"]> = { id: "T9", phase: "integrations", name: "Webhooks" };
    rerender(<EstimateView data={{ tasks: [t1, t2, t3, t4, back] }} streaming />);
    expect(phaseHeaders(container)).toEqual(["Discovery", "Integrations", "Backend", "Frontend", "Integrations"]);
    expect(taskHeaders(container)).toEqual([t1.name, t2.name, t3.name, t4.name, "Webhooks"]);
    rerender(<EstimateView data={{ tasks: [t1, t2, t3, t4, back] }} streaming={false} />);
    expect(phaseHeaders(container)).toEqual(["Discovery", "Integrations", "Backend", "Frontend"]);
    expect(taskHeaders(container)).toEqual([t1.name, t2.name, "Webhooks", t3.name, t4.name]);
  });

  it("renders valid nesting and keeps list semantics on unstyled lists", () => {
    const { container, rerender } = render(<EstimateView data={partials.empty} streaming />);
    const invalid = 'span div, p div, h3 div, h4 div, dt div, dd > div, li > span div';
    expect(container.querySelectorAll(invalid)).toHaveLength(0);
    rerender(<EstimateView data={wire('{"requirements": [{"id": "R1"}], "tasks": [{"id": "T1"}], "team": [{}], "risks": [{}], "assumptions": [{}]}')} streaming />);
    expect(container.querySelectorAll(invalid)).toHaveLength(0);
    rerender(<EstimateView data={fullEstimate} grounding={groundingWithIssues} streaming={false} />);
    expect(container.querySelectorAll(invalid)).toHaveLength(0);
    for (const ul of container.querySelectorAll("ul:not(.list-disc)")) expect(ul).toHaveAttribute("role", "list");
  });

  it.each([
    ["null", "null"],
    ["wrong top-level types", '{"project_name": 42, "summary": ["x"], "tasks": "nope", "requirements": {"id": "R1"}, "team": null, "risks": 3, "open_questions": [1, null, "Real question?"], "totals": [], "confidence": "certain"}'],
    ["wrong item types", '{"tasks": [null, 5, "x", {"id": 7, "phase": "moon", "name": "Odd", "optimistic_hours": "8", "likely_hours": null, "pessimistic_hours": 1e400, "basis": "R1"}], "risks": [{"impact": "extreme", "description": {}}], "team": [{"role": "Dev", "count": "two"}], "assumptions": [[]]}'],
    ["wrong nested values", '{"requirements": [{"id": "R1", "statement": {"nested": true}, "evidence": ["x"]}], "totals": {"expected_hours": "95", "optimistic_hours": null}, "confidence_rationale": 0}'],
  ])("never throws on malformed wire data (%s), streaming or not", (_name, json) => {
    const data = wire(json);
    const { rerender } = render(<EstimateView data={data} streaming />);
    expect(screen.getAllByRole("heading", { level: 3 })).toHaveLength(1);
    rerender(<EstimateView data={data} grounding={wireGrounding('{"ungrounded_requirement_ids": "R1", "tasks_without_valid_basis": null}')} streaming={false} />);
    expect(screen.getAllByRole("heading", { level: 4 }).map((h) => h.textContent)).toEqual(SECTIONS);
  });

  it("drops malformed values instead of rendering them", () => {
    render(<EstimateView data={wire('{"project_name": 42, "open_questions": [1, null, "Real question?"], "tasks": [null, 5, "x", [], {"id": "T1", "phase": "moon", "name": "Odd", "optimistic_hours": "8", "likely_hours": 12, "pessimistic_hours": 20}]}')} streaming />);
    expect(screen.queryByText("42")).not.toBeInTheDocument();
    expect(within(sectionOf("Open questions")).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["Real question?"]);
    expect(within(sectionOf("Tasks")).getAllByRole("row")).toHaveLength(3); // header, phase group, the one object task
    expect(within(rowOf("Odd")).queryByRole("img")).not.toBeInTheDocument();
  });
});

describe("EstimateView grounding", () => {
  it("marks ungrounded requirements and tasks without a valid basis with ⚠", () => {
    render(<EstimateView data={fullEstimate} grounding={groundingWithIssues} streaming={false} />);
    const r3 = requirementOf("R3");
    expect(within(r3).getByText("Quote not found in the transcript")).toBeInTheDocument();
    expect(r3.querySelector("svg.lucide-triangle-alert")).toBeInTheDocument();
    expect(within(requirementOf("R1")).queryByText("Quote not found in the transcript")).not.toBeInTheDocument();
    const t5 = rowOf("Email reminders");
    expect(within(t5).getByText("No valid basis")).toBeInTheDocument();
    expect(t5.querySelector("svg.lucide-triangle-alert")).toBeInTheDocument();
    expect(within(rowOf("Booking and cancellation API")).queryByText("No valid basis")).not.toBeInTheDocument();
    expect(screen.getByText("1 requirement has no matching quote in the transcript and 1 task has no valid basis.")).toBeInTheDocument();
  });

  it("shows no warnings when everything is grounded", () => {
    render(<EstimateView data={fullEstimate} grounding={cleanGrounding} streaming={false} />);
    expect(screen.queryByText("Quote not found in the transcript")).not.toBeInTheDocument();
    expect(screen.queryByText("No valid basis")).not.toBeInTheDocument();
    expect(document.querySelector("svg.lucide-triangle-alert")).not.toBeInTheDocument();
  });
});

describe("EstimateView announcements and focus", () => {
  it("does not announce growing text; one polite region says 'Estimate ready' when streaming ends", () => {
    const { container, rerender } = render(<EstimateView data={breakdown} streaming />);
    const article = closest(screen.getByRole("heading", { level: 3 }), "article");
    expect(article).toHaveAttribute("aria-busy", "true");
    const [live, ...others] = liveRegions(container);
    expect(others).toHaveLength(0);
    expect(live).toHaveAttribute("aria-live", "polite");
    expect(live).toBeEmptyDOMElement();

    rerender(<EstimateView data={fullEstimate} grounding={groundingWithIssues} streaming={false} completed />);
    expect(liveRegions(container)).toHaveLength(1);
    expect(live).toHaveTextContent("Estimate ready");
    expect(article).toHaveAttribute("aria-busy", "false");
  });

  it("does not claim the estimate is ready when the stream stops before the result", () => {
    const { container, rerender } = render(<EstimateView data={breakdown} streaming />);
    rerender(<EstimateView data={breakdown} streaming={false} />);
    expect(liveRegions(container)[0]).toBeEmptyDOMElement();
  });

  it("does not claim the estimate is ready when it shows an earlier, complete estimate after a stream that did not finish", () => {
    const { container, rerender } = render(<EstimateView data={{}} streaming />);
    rerender(<EstimateView data={fullEstimate} streaming={false} completed={false} />);
    expect(liveRegions(container)[0]).toBeEmptyDOMElement();
  });

  it("reports hover and focus on a requirement and highlights the active one", async () => {
    const user = userEvent.setup();
    const onRequirementFocus = vi.fn();
    render(<EstimateView data={fullEstimate} streaming={false} activeRequirement="R2" onRequirementFocus={onRequirementFocus} />);
    expect(requirementOf("R2")).toHaveAttribute("data-active");
    expect(requirementOf("R1")).not.toHaveAttribute("data-active");
    await user.hover(screen.getByText(breakdown.requirements[0].statement));
    expect(onRequirementFocus).toHaveBeenLastCalledWith("R1");
    await user.unhover(screen.getByText(breakdown.requirements[0].statement));
    expect(onRequirementFocus).toHaveBeenLastCalledWith(null);
    act(() => screen.getByRole("button", { name: "Evidence for R3" }).focus());
    expect(onRequirementFocus).toHaveBeenLastCalledWith("R3");
  });
});

describe("StatusSteps", () => {
  const streaming = (overrides: Partial<Extract<StreamState, { status: "streaming" }>> = {}): StreamState => ({
    status: "streaming",
    phase: "calling_llm",
    partial: null,
    startedAt: 0,
    ...overrides,
  });
  const currentStep = () => screen.getAllByRole("listitem").filter((li) => li.getAttribute("aria-current") === "step").map((li) => li.textContent);

  it("shows 'Switched to Anthropic' in a polite status region when the stream fell back", () => {
    render(<StatusSteps state={streaming({ phase: "fallback", switchedTo: "anthropic" })} />);
    const status = screen.getByRole("status");
    expect(status).toHaveAttribute("aria-live", "polite");
    expect(within(status).getByText("Switched to Anthropic")).toBeInTheDocument();
  });

  it("marks the current step from the phase and the first partial", () => {
    const { rerender } = render(<StatusSteps state={streaming()} />);
    expect(currentStep()).toEqual(["Contacting the model"]);
    rerender(<StatusSteps state={streaming({ partial: {} })} />);
    expect(currentStep()).toEqual(["Drafting the estimate"]);
    rerender(<StatusSteps state={streaming({ phase: "validating", partial: {} })} />);
    expect(currentStep()).toEqual(["Checking the estimate"]);
    expect(screen.queryByText(/Switched to/)).not.toBeInTheDocument();
  });

  it("completes every step when done and keeps the fallback notice", () => {
    const result: components["schemas"]["EstimateResponse"] = { ...fullResponse, provider: "anthropic", metrics: { ...fullResponse.metrics, fallback_used: true } };
    render(<StatusSteps state={{ status: "done", result }} />);
    expect(currentStep()).toEqual([]);
    expect(screen.getAllByRole("listitem")).toHaveLength(3);
    expect(screen.getByText("Switched to Anthropic")).toBeInTheDocument();
  });

  it("degrades instead of throwing on a malformed result frame", () => {
    const malformed: components["schemas"]["EstimateResponse"] = JSON.parse('{"metrics": null, "provider": 5}');
    const { rerender } = render(<StatusSteps state={{ status: "done", result: malformed }} />);
    expect(screen.getAllByRole("listitem")).toHaveLength(3);
    expect(screen.queryByText(/Switched to/)).not.toBeInTheDocument();
    rerender(<StatusSteps state={{ status: "done", result: JSON.parse('{"metrics": {"fallback_used": true}, "provider": {"name": "x"}}') }} />);
    expect(screen.queryByText(/Switched to/)).not.toBeInTheDocument();
    rerender(<StatusSteps state={streaming({ phase: "fallback", switchedTo: JSON.parse("5") })} />);
    expect(screen.queryByText(/Switched to/)).not.toBeInTheDocument();
    rerender(<StatusSteps state={{ status: "done", result: JSON.parse("null") }} />);
    expect(screen.getByRole("list", { name: "Progress" })).toHaveAttribute("role", "list");
  });

  it("renders nothing when idle", () => {
    const { container } = render(<StatusSteps state={{ status: "idle" }} />);
    expect(container).toBeEmptyDOMElement();
  });
});
