import type { components } from "@/lib/ai-service/schema";

type Schemas = components["schemas"];

// The request's choices, typed against the generated contract: a value the AI service drops fails the `satisfies`
// (and one it adds fails the form's label records), so `pnpm typecheck` catches enum drift. The form offers them and
// the BFF forwards only these exact values.
export const PROJECT_TYPES = ["mobile_app", "web_saas", "internal_tool", "data_pipeline"] as const satisfies readonly Schemas["ProjectType"][];
export const DETAIL_LEVELS = ["summary", "medium", "detailed"] as const satisfies readonly Schemas["DetailLevel"][];
export const OUTPUT_FORMATS = ["phases_table", "line_items", "narrative"] as const satisfies readonly Schemas["OutputFormat"][];

// Prompt versions as the AI service names them (`VERSION_PATTERN` in app/prompts/loader.py): v1, v2, …
export const PROMPT_VERSION = /^v[1-9]\d*$/;
