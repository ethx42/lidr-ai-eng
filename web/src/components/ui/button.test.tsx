import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { Button } from "./button";

// A translucent hover (bg-primary/80) blends the primary into the page and drops its text below 4.5:1 (WCAG 1.4.3);
// mixing towards the foreground keeps the hover opaque and raises the contrast in both themes. axe never hovers.
it("darkens or lightens the primary button on hover instead of making it translucent", () => {
  render(<Button>Estimate</Button>);
  const { className } = screen.getByRole("button", { name: "Estimate" });
  expect(className).not.toMatch(/hover:bg-primary\/\d+/);
  expect(className).toContain("hover:bg-[color-mix(in_oklch,var(--primary),var(--foreground)_10%)]");
});
