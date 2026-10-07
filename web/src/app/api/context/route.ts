import { matching, oneOf, proxyJson, withQuery } from "@/lib/ai-service/proxy";
import { DETAIL_LEVELS, OUTPUT_FORMATS, PROJECT_TYPES, PROMPT_VERSION } from "@/lib/estimate/choices";

// The system prompt depends on the three choices and the prompt version: each is forwarded only with a value the AI
// service accepts, and nothing else is.
export const GET = (request: Request) =>
  proxyJson(
    request,
    withQuery("/api/v1/context", request, {
      project_type: oneOf(PROJECT_TYPES),
      detail_level: oneOf(DETAIL_LEVELS),
      output_format: oneOf(OUTPUT_FORMATS),
      prompt_version: matching(PROMPT_VERSION),
    }),
  );
