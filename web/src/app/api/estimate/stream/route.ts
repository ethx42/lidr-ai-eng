import { proxySse } from "@/lib/ai-service/proxy";

const UPSTREAM = "/api/v1/estimate/stream";

// Only `refresh=true` (Regenerate skips the exact-match cache) reaches upstream; no other query string does.
export const POST = (request: Request) =>
  proxySse(request, new URL(request.url).searchParams.get("refresh") === "true" ? `${UPSTREAM}?refresh=true` : UPSTREAM);
