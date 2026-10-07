import * as z from "zod";
import type { components } from "@/lib/ai-service/schema";
import { DETAIL_LEVELS, OUTPUT_FORMATS, PROJECT_TYPES } from "@/lib/estimate/choices";

type Schemas = components["schemas"];
type ProjectType = Schemas["ProjectType"];
type DetailLevel = Schemas["DetailLevel"];
type OutputFormat = Schemas["OutputFormat"];

// Records keyed by the generated enums: a value the AI service adds is a missing label here, a type error.
export const PROJECT_TYPE_LABELS: Record<ProjectType, string> = {
  mobile_app: "Mobile app",
  web_saas: "Web SaaS",
  internal_tool: "Internal tool",
  data_pipeline: "Data pipeline",
};
export const DETAIL_LEVEL_LABELS: Record<DetailLevel, string> = { summary: "Summary", medium: "Medium", detailed: "Detailed" };
export const OUTPUT_FORMAT_LABELS: Record<OutputFormat, string> = { phases_table: "Phases table", line_items: "Line items", narrative: "Narrative" };

const EMPTY_TRANSCRIPT = "Paste or upload a transcript to estimate.";

// The character limit comes from the AI service at run time, so the form checks it outside the schema.
export const estimateFormSchema = z.object({
  transcription: z.string().trim().min(1, EMPTY_TRANSCRIPT),
  project_type: z.enum(PROJECT_TYPES),
  detail_level: z.enum(DETAIL_LEVELS),
  output_format: z.enum(OUTPUT_FORMATS),
  prompt_version: z.string(), // "" until one is picked: the AI service's default
});

export type EstimateFormValues = z.input<typeof estimateFormSchema>;
export type EstimateParams = Omit<EstimateFormValues, "transcription">;

export const DEFAULT_PARAMS: EstimateParams = { project_type: "web_saas", detail_level: "medium", output_format: "phases_table", prompt_version: "" };
export const DEFAULT_VALUES: EstimateFormValues = { transcription: "", ...DEFAULT_PARAMS };

// The request body: the brief's typed fields and nothing else (an empty `output_language` would fail validation).
export const toRequest = ({ transcription, project_type, detail_level, output_format }: z.output<typeof estimateFormSchema>): Schemas["EstimateRequest"] => ({
  transcription,
  project_type,
  detail_level,
  output_format,
});
