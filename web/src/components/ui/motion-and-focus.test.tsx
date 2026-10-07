import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { FieldLabel } from "./field";
import { Skeleton } from "./skeleton";

// The token rules (globals.css): motion only when the user allows it, and one focus outline, never a ring halo.
it("pulses a skeleton only when motion is allowed", () => {
  render(<Skeleton data-testid="skeleton" />);
  const classes = screen.getByTestId("skeleton").className.split(" ");
  expect(classes).toContain("motion-safe:animate-pulse");
  expect(classes).not.toContain("animate-pulse");
});

it("draws no ring halo around a field label that wraps a focused field", () => {
  render(<FieldLabel>Project type</FieldLabel>);
  expect(screen.getByText("Project type").className).not.toMatch(/\bring-/);
});
