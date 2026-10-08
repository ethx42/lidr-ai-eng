import { act, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ContextMeter } from "./context-meter";

const EXPLANATION = "Older turns are dropped first. Project memory is kept separately and always sent.";

describe("ContextMeter", () => {
  it("shows how many turns of history the next turn sends, as a meter", () => {
    render(
      <TooltipProvider>
        <ContextMeter turns={4} max={6} />
      </TooltipProvider>,
    );
    expect(screen.getByText("History 4 / 6 turns")).toBeInTheDocument();
    const meter = screen.getByRole("meter", { name: "History" });
    expect(meter).toHaveAttribute("aria-valuenow", "4");
    expect(meter).toHaveAttribute("aria-valuemax", "6");
    expect(meter).toHaveAttribute("aria-valuetext", "4 of 6 turns");
  });

  it("explains the window in a tooltip, also given to screen readers as the meter's description", async () => {
    render(
      <TooltipProvider>
        <ContextMeter turns={6} max={6} />
      </TooltipProvider>,
    );
    expect(screen.getByRole("meter", { name: "History" })).toHaveAccessibleDescription(EXPLANATION);
    act(() => screen.getByRole("button", { name: "About the history window" }).focus());
    expect(await screen.findByRole("tooltip")).toHaveTextContent(EXPLANATION);
  });

  it("shows a skeleton until the session is known", () => {
    const { container } = render(<ContextMeter />);
    expect(container.querySelector('[data-slot="skeleton"]')).not.toBeNull();
    expect(screen.queryByRole("meter")).not.toBeInTheDocument();
  });
});
