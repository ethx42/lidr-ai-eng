import { describe, expect, it } from "vitest";
import type { components } from "@/lib/ai-service/schema";
import { computeTotalsDelta, describeDelta } from "./totals-delta";

const totals = (expected: number, cost: number | null = null): components["schemas"]["Totals"] => ({
  expected_hours: expected,
  optimistic_hours: expected * 0.8,
  pessimistic_hours: expected * 1.4,
  team_size: 3,
  weekly_capacity_hours: 30,
  duration_weeks_min: 1,
  duration_weeks_max: 2,
  hourly_rate: cost === null ? null : 60,
  estimated_cost: cost,
});

describe("computeTotalsDelta", () => {
  it("returns null on the first turn and the signed change afterwards", () => {
    expect(computeTotalsDelta(null, totals(100))).toBeNull();
    expect(computeTotalsDelta(totals(100), totals(130))).toEqual({ expectedHours: 30 });
  });

  it("includes the cost change only when both turns have a cost, and rounds away float noise", () => {
    expect(computeTotalsDelta(totals(100, 6000), totals(87.7, 5262))).toEqual({ expectedHours: -12.3, costUsd: -738 });
    expect(computeTotalsDelta(totals(100, 6000), totals(130))).toEqual({ expectedHours: 30 });
    expect(computeTotalsDelta(totals(0.1), totals(0.3))).toEqual({ expectedHours: 0.2 });
  });
});

describe("describeDelta", () => {
  it("says the change in hours, and cost when known, against the previous turn", () => {
    expect(describeDelta({ expectedHours: 30 })).toBe("+30 h vs previous turn");
    expect(describeDelta({ expectedHours: -12.3, costUsd: -738 })).toBe("−12.3 h, −$738 vs previous turn");
    expect(describeDelta({ expectedHours: 0, costUsd: 0 })).toBe("No change in hours vs previous turn");
  });
});
