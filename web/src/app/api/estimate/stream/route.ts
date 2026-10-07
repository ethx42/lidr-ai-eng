import { matching, proxySse, withQuery } from "@/lib/ai-service/proxy";
import { PROMPT_VERSION } from "@/lib/estimate/choices";

// Only a well-formed `prompt_version` (the form's choice) and `refresh=true` (Regenerate skips the exact-match cache)
// reach upstream; the choices themselves travel in the JSON body.
export const POST = (request: Request) =>
  proxySse(request, withQuery("/api/v1/estimate/stream", request, { prompt_version: matching(PROMPT_VERSION), refresh: (value) => value === "true" }));
