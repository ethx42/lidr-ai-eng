import type { components } from "@/lib/ai-service/schema";

// Snapshots and results are unchecked wire data: whatever the TS types claim, every nested value is read
// through a guard here, and anything missing or malformed becomes `undefined` (rendered as a skeleton).

type Schemas = components["schemas"];
type Wire = Record<string, unknown>;

export type Level = Schemas["Risk"]["impact"];
export type TaskPhase = Schemas["Task"]["phase"];
export type TaskView = Partial<Schemas["EstimatedTask"]>;
export type EstimateModel = {
  project_name?: string;
  summary?: string;
  requirements?: Partial<Schemas["Requirement"]>[];
  assumptions?: Partial<Schemas["Assumption"]>[];
  open_questions?: string[];
  tasks?: TaskView[];
  team?: Partial<Schemas["TeamMember"]>[];
  risks?: Partial<Schemas["Risk"]>[];
  confidence?: Level;
  confidence_rationale?: string;
  totals?: Partial<Schemas["Totals"]>; // only the final result has totals
};
export type GroundingChecks = { ungrounded: Set<string>; invalidBasis: Set<string> };

// Records rather than arrays, so a value added to a schema enum fails type-checking here until it is listed.
const LEVELS: Record<Level, true> = { low: true, medium: true, high: true };
const PHASES: Record<TaskPhase, true> = { discovery: true, ux_ui: true, backend: true, frontend: true, integrations: true, qa: true, devops: true, project_management: true };

const isWire = (value: unknown): value is Wire => typeof value === "object" && value !== null && !Array.isArray(value);
const text = (value: unknown) => (typeof value === "string" && value.trim() !== "" ? value : undefined);
const num = (value: unknown) => (typeof value === "number" && Number.isFinite(value) ? value : undefined);
const bool = (value: unknown) => (typeof value === "boolean" ? value : undefined);
const isMember = <K extends string>(options: Record<K, true>, value: unknown): value is K => typeof value === "string" && Object.hasOwn(options, value);
const oneOf = <K extends string>(options: Record<K, true>, value: unknown) => (isMember(options, value) ? value : undefined);
const list = <T>(value: unknown, read: (item: Wire) => T) => (Array.isArray(value) ? value.filter(isWire).map(read) : undefined);
const texts = (value: unknown) => (Array.isArray(value) ? value.map(text).filter((item) => item !== undefined) : undefined);

const task = (t: Wire): TaskView => ({
  id: text(t.id),
  phase: oneOf(PHASES, t.phase),
  name: text(t.name),
  rationale: text(t.rationale),
  basis: texts(t.basis),
  optimistic_hours: num(t.optimistic_hours),
  likely_hours: num(t.likely_hours),
  pessimistic_hours: num(t.pessimistic_hours),
  expected_hours: num(t.expected_hours),
});

const totals = (t: Wire): Partial<Schemas["Totals"]> => ({
  expected_hours: num(t.expected_hours),
  optimistic_hours: num(t.optimistic_hours),
  pessimistic_hours: num(t.pessimistic_hours),
  team_size: num(t.team_size),
  duration_weeks_min: num(t.duration_weeks_min),
  duration_weeks_max: num(t.duration_weeks_max),
  hourly_rate: num(t.hourly_rate),
  estimated_cost: num(t.estimated_cost),
});

export const readEstimate = (data: unknown): EstimateModel => {
  if (!isWire(data)) return {};
  return {
    project_name: text(data.project_name),
    summary: text(data.summary),
    requirements: list(data.requirements, (r) => ({ id: text(r.id), statement: text(r.statement), evidence: text(r.evidence) })),
    assumptions: list(data.assumptions, (a) => ({ id: text(a.id), statement: text(a.statement), impact_if_wrong: text(a.impact_if_wrong) })),
    open_questions: texts(data.open_questions),
    tasks: list(data.tasks, task),
    team: list(data.team, (m) => ({ role: text(m.role), count: num(m.count) })),
    risks: list(data.risks, (r) => ({ description: text(r.description), impact: oneOf(LEVELS, r.impact), mitigation: text(r.mitigation) })),
    confidence: oneOf(LEVELS, data.confidence),
    confidence_rationale: text(data.confidence_rationale),
    totals: isWire(data.totals) ? totals(data.totals) : undefined,
  };
};

export const readGrounding = (grounding: unknown): GroundingChecks => {
  const report: Wire = isWire(grounding) ? grounding : {};
  return { ungrounded: new Set(texts(report.ungrounded_requirement_ids)), invalidBasis: new Set(texts(report.tasks_without_valid_basis)) };
};

export const readText = text;

// What the inspector shows about a finished call; `undefined` is a value the result did not carry or that was malformed.
export const readCallMetrics = (result: unknown) => {
  const response: Wire = isWire(result) ? result : {};
  const metrics: Wire = isWire(response.metrics) ? response.metrics : {};
  const usage: Wire = isWire(response.usage) ? response.usage : {};
  return {
    projectName: isWire(response.breakdown) ? text(response.breakdown.project_name) : undefined,
    provider: text(response.provider),
    model: text(response.model),
    promptVersion: text(response.prompt_version),
    fallbackUsed: metrics.fallback_used === true,
    cacheHit: bool(metrics.cache_hit),
    inputTokens: num(usage.input_tokens),
    cachedTokens: num(usage.cached_input_tokens),
    outputTokens: num(usage.output_tokens),
    latencyMs: num(metrics.latency_ms),
    ttftMs: num(metrics.ttft_ms),
    costUsd: num(metrics.cost_usd),
  };
};

// What the status steps need from a `result` frame, which is as unchecked as a partial.
export const readCallStatus = (result: unknown) => {
  const { cacheHit, fallbackUsed, provider } = readCallMetrics(result);
  return { cacheHit: cacheHit === true, fallbackProvider: fallbackUsed ? provider : undefined };
};

export type ReferenceModel = { size?: string; meetingSummary: string; projectName?: string; estimation?: Wire };

// `GET /api/context` past the fields the shell checks; a reference without a meeting summary is dropped.
export const readContext = (context: unknown) => {
  const data: Wire = isWire(context) ? context : {};
  const references = list(data.references, (r): ReferenceModel | undefined => {
    const meetingSummary = text(r.meeting_summary);
    const estimation = isWire(r.estimation) ? r.estimation : undefined;
    return meetingSummary ? { size: text(r.size), meetingSummary, projectName: text(estimation?.project_name), estimation } : undefined;
  });
  return {
    promptVersion: text(data.prompt_version),
    systemPrompt: text(data.system_prompt),
    references: references?.filter((r) => r !== undefined) ?? [],
  };
};

// The list to render, or `undefined` while it is pending: missing, or empty only because its first item has not arrived yet.
export const received = <T>(items: T[] | undefined, streaming: boolean) => (items && (items.length > 0 || !streaming) ? items : undefined);
