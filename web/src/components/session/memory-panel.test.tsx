import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MemoryPanel } from "./memory-panel";

const metadata = { project_name: "Clinic portal", assumed_team_size: 4, mentioned_technologies: ["Stripe", "Redsys"], agreed_scope: "Patients book and pay online." };
const valueOf = (label: string) => {
  const value = screen.getByText(label, { selector: "dt *, dt" }).closest("div")?.querySelector("dd");
  if (!(value instanceof HTMLElement)) throw new Error(`no value for ${label}`);
  return value;
};
const termOf = (label: string) => {
  const term = screen.getByText(label, { selector: "dt *, dt" }).closest("dt");
  if (!(term instanceof HTMLElement)) throw new Error(`no term ${label}`);
  return term;
};

describe("MemoryPanel", () => {
  it("shows the four facts the session remembers, technologies as a list", () => {
    render(<MemoryPanel metadata={metadata} />);
    expect(screen.getByRole("heading", { name: "Project memory" })).toBeInTheDocument();
    expect(valueOf("Project name")).toHaveTextContent("Clinic portal");
    expect(valueOf("Team size")).toHaveTextContent("4 people");
    expect(within(valueOf("Technologies")).getAllByRole("listitem").map((item) => item.textContent)).toEqual(["Stripe", "Redsys"]);
    expect(valueOf("Agreed scope")).toHaveTextContent("Patients book and pay online.");
  });

  it("says what is not known yet instead of leaving a blank", () => {
    render(<MemoryPanel metadata={{ project_name: null, assumed_team_size: null, mentioned_technologies: [], agreed_scope: null }} />);
    for (const label of ["Project name", "Team size", "Technologies", "Agreed scope"]) expect(valueOf(label)).toHaveTextContent("Not mentioned yet");
    expect(screen.queryByText("Updated")).not.toBeInTheDocument();
  });

  it("marks the facts this turn changed with a subtle Updated badge, read with the fact", () => {
    render(<MemoryPanel metadata={{ ...metadata, assumed_team_size: 1 }} changed={["mentioned_technologies", "assumed_team_size"]} />);
    expect(within(termOf("Technologies")).getByText("Updated")).toBeInTheDocument();
    expect(within(termOf("Team size")).getByText("Updated")).toBeInTheDocument();
    expect(within(termOf("Project name")).queryByText("Updated")).not.toBeInTheDocument();
    expect(screen.getAllByText("Updated")).toHaveLength(2);
    expect(valueOf("Team size")).toHaveTextContent("1 person");
  });

  it("shows skeletons until the session's memory is known", () => {
    const { container } = render(<MemoryPanel />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
    expect(container.querySelectorAll('[data-slot="skeleton"]').length).toBeGreaterThan(0);
  });

  it("never throws on malformed memory, showing what it cannot read as not known", () => {
    render(<MemoryPanel metadata={{ project_name: 7, assumed_team_size: "four", mentioned_technologies: "Stripe", agreed_scope: ["x"] }} />);
    for (const label of ["Project name", "Team size", "Technologies", "Agreed scope"]) expect(valueOf(label)).toHaveTextContent("Not mentioned yet");
  });
});
