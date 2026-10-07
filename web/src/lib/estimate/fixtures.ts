import type { components } from "@/lib/ai-service/schema";
import type { PartialBreakdown } from "@/lib/estimate/types";

type Schemas = components["schemas"];

// What the model returns: the last `partial` snapshot of a complete stream (no totals, no expected hours).
export const breakdown: Schemas["EstimationBreakdown"] = {
  project_name: "Physiotherapy patient portal",
  summary:
    "A responsive patient portal for three physiotherapy clinics. Patients log in, see and book appointments, download invoices and watch exercise videos. Data comes from the ClinicCloud practice management system.",
  requirements: [
    {
      id: "R1",
      statement: "Patients log in and see their upcoming appointments.",
      evidence: "We want a web portal where patients log in, see their upcoming appointments, and download invoices as PDF.",
    },
    {
      id: "R2",
      statement: "Patients book a session and cancel up to 24 hours before.",
      evidence: "patients should be able to book a new session with their physiotherapist, and cancel up to 24 hours before.",
    },
    {
      id: "R3",
      statement: "Patients watch their home exercise videos in the portal.",
      evidence: "Patients can stream exercise videos in the app.",
    },
  ],
  assumptions: [
    {
      id: "A1",
      statement: "ClinicCloud's REST API exposes appointments and invoices.",
      impact_if_wrong: "A sync layer would add 40 to 80 hours.",
    },
  ],
  open_questions: [
    "Does the ClinicCloud API allow creating and cancelling bookings?",
    "Who uploads the exercise videos, and how large are they?",
  ],
  tasks: [
    { id: "T1", phase: "discovery", name: "Discovery and API review", rationale: "Confirm booking rules and what the API exposes.", basis: ["R1", "A1"], optimistic_hours: 6, likely_hours: 8, pessimistic_hours: 12 },
    { id: "T2", phase: "integrations", name: "ClinicCloud integration", rationale: "Appointments, invoices and bookings through an API nobody has reviewed yet.", basis: ["R1", "A1"], optimistic_hours: 16, likely_hours: 24, pessimistic_hours: 40 },
    { id: "T3", phase: "backend", name: "Booking and cancellation API", rationale: "The 24-hour cancellation rule and slot checks drive the size.", basis: ["R2"], optimistic_hours: 8, likely_hours: 12, pessimistic_hours: 20 },
    { id: "T4", phase: "frontend", name: "Patient portal screens", rationale: "Login, appointments, booking, invoices and videos, responsive.", basis: ["R1", "R2", "R3"], optimistic_hours: 20, likely_hours: 28, pessimistic_hours: 44 },
    { id: "T5", phase: "integrations", name: "Email reminders", rationale: "A scheduled job and an email provider.", basis: ["R9"], optimistic_hours: 4, likely_hours: 6, pessimistic_hours: 10 },
    { id: "T6", phase: "qa", name: "End-to-end tests", rationale: "Booking, cancellation and invoice download paths.", basis: ["R1", "R2"], optimistic_hours: 8, likely_hours: 12, pessimistic_hours: 18 },
  ],
  team: [
    { role: "Full-stack developer", count: 2 },
    { role: "QA engineer", count: 1 },
  ],
  risks: [
    { description: "The ClinicCloud API documentation may be incomplete.", impact: "high", mitigation: "Spike the API in discovery before committing to dates." },
    { description: "Health data needs GDPR controls.", impact: "medium", mitigation: "Plan a data protection review." },
  ],
  confidence: "medium",
  confidence_rationale: "Core flows are clear, but nobody has reviewed the ClinicCloud API yet.",
};

// PERT rounded to half hours, as the AI service computes it.
const pert = (t: Schemas["Task"]) => Math.floor(((t.optimistic_hours + 4 * t.likely_hours + t.pessimistic_hours) / 6) * 2 + 0.5) / 2;

// The final `result.breakdown`: expected hours per task (95 h in total) and totals for a team of 3 at 30 h/week and $60/h.
export const fullEstimate: Schemas["EnrichedBreakdown"] = {
  ...breakdown,
  tasks: breakdown.tasks.map((task) => ({ ...task, expected_hours: pert(task) })),
  totals: {
    expected_hours: 95,
    optimistic_hours: 62,
    pessimistic_hours: 144,
    team_size: 3,
    weekly_capacity_hours: 30,
    duration_weeks_min: 1,
    duration_weeks_max: 2,
    hourly_rate: 60,
    estimated_cost: 5700,
  },
};

export const groundingWithIssues: Schemas["GroundingReport"] = {
  requirements_total: 3,
  requirements_grounded: 2,
  ungrounded_requirement_ids: ["R3"],
  tasks_without_valid_basis: ["T5"],
  score: 0.67,
};

export const cleanGrounding: Schemas["GroundingReport"] = {
  requirements_total: 3,
  requirements_grounded: 3,
  ungrounded_requirement_ids: [],
  tasks_without_valid_basis: [],
  score: 1,
};

export const fullResponse: Schemas["EstimateResponse"] = {
  estimation: "# Physiotherapy patient portal\n\nExpected effort: 95 h (62–144 h).",
  breakdown: fullEstimate,
  grounding: groundingWithIssues,
  metrics: { latency_ms: 4200, ttft_ms: 650, cost_usd: 0.0012, cache_hit: false, fallback_used: false, attempts: 1 },
  model: "gpt-4o-mini",
  provider: "openai",
  prompt_version: "v1",
  usage: { input_tokens: 5200, output_tokens: 1400, cached_input_tokens: 4096, cache_write_tokens: 0 },
};

// Early snapshots of a stream: each section and item arrives field by field.
export const partials = {
  empty: {},
  projectNameOnly: { project_name: "Yo" },
  taskWithoutHours: { tasks: [{ id: "T1", name: "Back" }] },
  requirementIdOnly: { requirements: [{ id: "R1" }] },
} satisfies Record<string, PartialBreakdown>;
