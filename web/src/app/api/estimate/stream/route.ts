import { matching, proxySse, withQuery } from "@/lib/ai-service/proxy";
import { PROMPT_VERSION } from "@/lib/estimate/choices";

// The single-shot estimate as Server-Sent Events. No page of this app calls it since the session workspace replaced the
// single-shot page (S5-R8); it stays for API clients. Only a well-formed `prompt_version` and `refresh=true` (skips the
// exact-match cache) reach upstream; the choices themselves travel in the JSON body.
export const POST = (request: Request) =>
  proxySse(request, withQuery("/api/v1/estimate/stream", request, { prompt_version: matching(PROMPT_VERSION), refresh: (value) => value === "true" }));
