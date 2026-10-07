import { describe, expect, it } from "vitest";
import { formatHours, formatProvider, formatRange, formatUsd } from "./format";

describe("formatHours", () => {
  it.each([
    [24.5, "24.5 h"],
    [24, "24 h"],
    [12.666, "12.7 h"],
    [1240, "1,240 h"],
  ])("%s → %s", (hours, expected) => {
    expect(formatHours(hours)).toBe(expected);
  });
});

describe("formatRange", () => {
  it("joins the bounds with an en dash and the unit (hours by default)", () => {
    expect(formatRange(8, 20)).toBe("8–20 h");
    expect(formatRange(1.5, 3, "weeks")).toBe("1.5–3 weeks");
  });

  it("collapses bounds that format the same", () => {
    expect(formatRange(8, 8)).toBe("8 h");
    expect(formatRange(7.96, 8.04)).toBe("8 h");
  });

  it("singularises a plural unit when the collapsed value is 1", () => {
    expect(formatRange(1, 1, "weeks")).toBe("1 week");
    expect(formatRange(1, 1)).toBe("1 h");
    expect(formatRange(0.5, 1, "weeks")).toBe("0.5–1 weeks");
    expect(formatRange(2, 2, "weeks")).toBe("2 weeks");
  });
});

describe("formatUsd", () => {
  it.each([
    [5700, "$5,700"],
    [5700.5, "$5,701"],
    [0.0012, "$0.0012"],
    [0, "$0.00"],
  ])("%s → %s", (usd, expected) => {
    expect(formatUsd(usd)).toBe(expected);
  });
});

describe("formatProvider", () => {
  it.each([
    ["anthropic", "Anthropic"],
    ["openai", "OpenAI"],
    ["mistral", "Mistral"],
  ])("%s → %s", (provider, expected) => {
    expect(formatProvider(provider)).toBe(expected);
  });
});
